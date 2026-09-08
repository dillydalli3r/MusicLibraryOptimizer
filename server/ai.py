"""AI-assisted lyrics tooling.

Two kinds of helpers:

* ``ai_chat`` - a minimal OpenAI-compatible /chat/completions client
  (works with OpenAI, OpenRouter, llama.cpp, oobabooga, LM Studio, and
  Google Gemini's OpenAI-compatible endpoint — a bare
  generativelanguage.googleapis.com base URL is auto-routed)
  configured through the ``ai_base_url`` / ``ai_api_key`` / ``ai_model``
  config keys.
* ``lyrics_clean`` / ``lyrics_repair`` - LLM-backed prompt wrappers that
  clean raw lyrics (ads, watermarks, layout garbage) and repair holes in
  imported lyrics using LRCLIB candidates.
* ``wordsync_lrc`` - deterministic (no AI) line→word sync: turns plain
  line-synced LRC into word-synced ELRC by distributing word times inside
  each line's slot, weighted by word length.
"""
import difflib
import math
import os
import re
import threading
import unicodedata

import httpx

from server.integrations import USER_AGENT

_WORD_SPLIT_RE = re.compile(r"\s+")
# A line slot should never stretch past the next line by more than this,
# so instrumental gaps don't get crawled by slowly-appearing words.
_MAX_LINE_SPREAD_S = 6.0
_MIN_WORD_SPAN_S = 0.18


_GEMINI_HOST = "generativelanguage.googleapis.com"


def ai_config(config):
    """(base_url, api_key, model) from the flat config keys, normalized.

    Google's Gemini API speaks the OpenAI protocol on
    ``https://generativelanguage.googleapis.com/v1beta/openai`` — users
    typically paste just the bare host (or the full .../chat/completions
    endpoint), so both are routed to the correct base here."""
    base = str(config.get("ai_base_url") or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    if _GEMINI_HOST in base and not base.endswith("/openai"):
        base = f"https://{_GEMINI_HOST}/v1beta/openai"
    key = str(config.get("ai_api_key") or "").strip()
    model = str(config.get("ai_model") or "").strip()
    return base, key, model


def ai_configured(config):
    base, _key, model = ai_config(config)
    return bool(base and model)


def ai_chat(config, system, user, timeout=90.0):
    """One-shot chat completion; returns the assistant message text."""
    base, key, model = ai_config(config)
    if not base or not model:
        raise ValueError("AI is not configured — set base URL and model in Settings → AI")
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {
        "model": model,
        "temperature": 0.2,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    }
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers,
                   timeout=timeout)
    if r.status_code >= 400:
        # surface the provider's own message (bad key, unknown model, …)
        detail = (r.text or "").strip().replace("\n", " ")[:300]
        raise ValueError(f"AI endpoint returned {r.status_code}: {detail}")
    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"unexpected AI response shape: {str(data)[:200]}")
    return (content or "").strip()


CLEAN_SYSTEM = (
    "You clean up raw song lyrics. Remove advertising, download links, "
    "platform watermarks (e.g. 'Lyrics provided by...'), translator credits, "
    "editorial notes and duplicated blocks. Fix broken line wrapping so each "
    "line is a lyric phrase. Keep the original language, wording, spelling of "
    "words, section structure and line order. Never translate, summarize or "
    "add commentary. Output ONLY the cleaned lyrics, nothing else."
)


def lyrics_clean(config, text):
    """Clean raw (unsynced) lyrics via the configured LLM."""
    return ai_chat(config, CLEAN_SYSTEM, text)


REPAIR_SYSTEM = (
    "You repair corrupted song lyrics. You get the current lyrics and a list "
    "of candidate lines taken from other public sources of the same song. "
    "Fill missing lines, remove intruder lines and fix obviously wrong words "
    "using the candidates as evidence. Keep timestamps exactly where provided. "
    "Keep the original language and structure. Output ONLY the repaired lyrics "
    "in the same format (LRC if timestamps were given, plain text otherwise), "
    "nothing else."
)


def lyrics_repair(config, text, candidates, artist="", track=""):
    """Repair lyrics using LRCLIB candidate lines as evidence."""
    cand_text = "\n".join(
        f"- {c}" for c in candidates[:60] if c
    ) or "(no candidates)"
    header = f"Song: {artist} - {track}\n\n" if artist or track else ""
    user = f"{header}CURRENT LYRICS:\n{text}\n\nCANDIDATE LINES:\n{cand_text}"
    return ai_chat(config, REPAIR_SYSTEM, user)


# --------------------------------------------------------------------------- #
# Deterministic word sync (ELRC builder)
# --------------------------------------------------------------------------- #
_LINE_RE = re.compile(r"^(?:\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\])+(.*)$")
_ALL_TIMES_RE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_WORD_TAG_RE = re.compile(r"<\d{1,2}:\d{1,2}(?:[.:]\d{1,3})?>")


def _ts_to_s(mm, ss, frac="0"):
    """[mm:ss.ff] -> seconds (centiseconds, LRC convention)."""
    return int(mm) * 60 + int(ss) + int((frac or "0").ljust(2, "0")[:2]) / 100.0


def _fmt_ts(t, decimals=2):
    """seconds -> [mm:ss.ff] (centiseconds, LRC convention)."""
    mm = int(t // 60)
    ss = int(t % 60)
    frac = round((t - math.floor(t)) * 10 ** decimals)
    if frac >= 10 ** decimals:
        frac = 10 ** decimals - 1
    return f"[{mm:02d}:{ss:02d}." + str(frac).zfill(decimals) + "]"


def wordsync_lrc(lrc_text):
    """Turn line-synced LRC into word-synced ELRC (deterministic).

    Each line's time slot runs from its own timestamp to the next line's
    timestamp (capped at _MAX_LINE_SPREAD_S). Word start times are spread
    across the slot proportionally to word length. Lines that already carry
    <mm:ss.xx> word tags are left untouched. Empty/instrumental lines
    (no text) pass through unchanged.
    """
    rows = []
    for raw in (lrc_text or "").splitlines():
        m = _ALL_TIMES_RE.findall(raw)
        body = _ALL_TIMES_RE.sub("", raw).strip()
        if not m:
            rows.append((None, raw.strip()))
            continue
        t = _ts_to_s(m[-1][0], m[-1][1], m[-1][2])
        rows.append((t, body))

    out = []
    n = len(rows)
    for i, (t, body) in enumerate(rows):
        if t is None:
            out.append(body)
            continue
        if not body or _WORD_TAG_RE.search(body):
            # empty (instrumental) line or already word-synced: keep as-is
            out.append(f"{_fmt_ts(t)} {body}".rstrip())
            continue
        # resolve the line's end: next timed line, capped spread
        end = None
        for j in range(i + 1, n):
            if rows[j][0] is not None and rows[j][0] > t:
                end = min(rows[j][0], t + _MAX_LINE_SPREAD_S)
                break
        if end is None:
            end = t + min(_MAX_LINE_SPREAD_S, max(1.5, 0.32 * len(body.split())))
        words = _WORD_SPLIT_RE.split(body.strip())
        weights = [max(len(w), 1) for w in words]
        total = sum(weights)
        span = max(end - t, _MIN_WORD_SPAN_S * len(words))
        cursor = t
        pieces = []
        for w, wt in zip(words, weights):
            share = span * (wt / total)
            pieces.append(f"<{_fmt_ts(cursor)[1:-1]}>{w}")
            cursor += share
        out.append(f"{_fmt_ts(t)} " + " ".join(pieces))
    return "\n".join(out)


# --------------------------------------------------------------------------- #
# Line-aligned transforms for the fullscreen player: translation and
# transliteration (romanization). Results are cached on disk per
# (mode, language, content) so a track is only processed once.
# --------------------------------------------------------------------------- #
import hashlib

def _cache_dir():
    """The lyrics-AI cache lives in <music folder>/.data too."""
    from mlo.paths import app_data_dir
    return os.path.join(app_data_dir(), "lyrics_ai_cache")

# Script 15 runs in a worker thread while the fullscreen player may be
# transforming the same track — serialize cache reads/writes so two writers
# can never interleave into the same JSON file.
_CACHE_LOCK = threading.Lock()

XLIT_SYSTEM = (
    "You romanize song lyrics. Convert every line from its original script "
    "(e.g. Japanese kana/kanji, Cyrillic, Hangul, Hanbi, Arabic, Devanagari) "
    "into Latin transliteration. Keep the same language, do NOT translate. "
    "Keep the original line count and order: exactly one output line per "
    "input line, same numbering. Output ONLY the transformed lines."
)

TRANSLATE_SYSTEM = (
    "You translate song lyrics. Translate every line into the requested "
    "target language. Keep the original line count and order: exactly one "
    "output line per input line, same numbering. Keep it singable and "
    "literal enough to follow along; do not add commentary. Output ONLY the "
    "translated lines."
)


def _cache_path(mode, lang, lines):
    h = hashlib.sha1(("|".join([mode, lang] + lines)).encode("utf-8")).hexdigest()
    return os.path.join(_cache_dir(), f"{mode}-{lang}-{h[:20]}.json")


def transform_lines(config, lines, mode, lang=""):
    """Translate ('translate') or transliterate ('transliterate') lyric
    lines, preserving line count. Disk-cached; raises ValueError when AI
    is not configured."""
    lines = [str(line) for line in lines]
    if not lines:
        return []
    base, key, model = ai_config(config)
    if not base or not model:
        raise ValueError("AI is not configured — set base URL and model in Settings → AI")
    if mode not in ("translate", "transliterate"):
        raise ValueError(f"unknown mode: {mode}")
    if not lang:
        lang = str(config.get("ai_translate_lang") or "en").strip() or "en"

    cache = _cache_path(mode, lang, lines)
    with _CACHE_LOCK:
        try:
            import json
            with open(cache, "r", encoding="utf-8") as fh:
                cached = json.load(fh)
            if isinstance(cached, list) and len(cached) == len(lines):
                return cached
        except (OSError, ValueError):
            pass

    system = TRANSLATE_SYSTEM if mode == "translate" else XLIT_SYSTEM
    out = []
    import json
    CHUNK = 40
    for start in range(0, len(lines), CHUNK):
        chunk = lines[start:start + CHUNK]
        numbered = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(chunk))
        user = numbered
        if mode == "translate":
            user = f"Target language: {lang}\n\n{numbered}"
        text = ai_chat(config, system, user)
        got = [re.sub(r"^\s*\d+\.\s*", "", ln).strip()
               for ln in text.splitlines() if ln.strip()]
        # line-count repair: the model must echo one line per input line
        while len(got) < len(chunk):
            got.append("")
        if len(got) > len(chunk):
            got = got[:len(chunk)]
        out.extend(got)

    with _CACHE_LOCK:
        try:
            os.makedirs(_cache_dir(), exist_ok=True)
            import json
            with open(_cache_path(mode, lang, lines), "w", encoding="utf-8") as fh:
                json.dump(out, fh, ensure_ascii=False)
        except OSError:
            pass
    return out


# --------------------------------------------------------------------------- #
# Detect & sync: pick the best LRCLIB match for a track and give the lyrics
# timestamps. Existing unsynced wording is preserved by aligning it to the
# matched candidate's synced timestamps (AI when configured, deterministic
# fuzzy matching otherwise); a track with no lyrics gets the candidate's
# synced lyrics. Already-synced input is upgraded to ELRC word sync.
# --------------------------------------------------------------------------- #
_SYNC_SYSTEM = (
    "You align song lyrics to timestamps. You get numbered EXISTING LINES "
    "(the wording that must be kept) and a SYNCED REFERENCE of the same song "
    "with [mm:ss.xx] timestamps. For each existing line, find the reference "
    "line carrying the same words (minor spelling/punctuation differences "
    "allowed) and answer with its timestamp. Respond with ONLY a JSON array "
    "of numbers/nulls, one entry per existing line in order: the timestamp in "
    "seconds (number) or null when there is no plausible match. The array "
    "length MUST equal the number of existing lines. No commentary."
)


def _norm_line(s):
    """Normalize a lyric line for fuzzy comparison."""
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    s = _ALL_TIMES_RE.sub("", s)
    s = _WORD_TAG_RE.sub("", s)
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _candidate_rows(candidates):
    """LRCLIB search hits -> [{artist, track, duration, synced, sync_lines}]."""
    rows = []
    for c in candidates or []:
        if not isinstance(c, dict):
            continue
        sync = c.get("syncedLyrics") or ""
        sync_lines = []
        if sync:
            for raw in sync.splitlines():
                m = _ALL_TIMES_RE.search(raw)
                body = _ALL_TIMES_RE.sub("", raw)
                body = _WORD_TAG_RE.sub("", body).strip()
                if m and body:
                    sync_lines.append((_ts_to_s(m.group(1), m.group(2), m.group(3)), body))
        rows.append({
            "artist": str(c.get("artistName") or ""),
            "track": str(c.get("trackName") or ""),
            "duration": c.get("duration"),
            "synced": bool(sync),
            "sync_lines": sync_lines,
            "plain": c.get("plainLyrics") or "",
        })
    return rows


def _best_candidate(rows, duration=None):
    """Prefer synced candidates, then the closest duration."""
    if not rows:
        return None
    def score(r):
        s = 100.0 if r["synced"] else 0.0
        if duration:
            try:
                s -= min(abs(float(r.get("duration") or 0) - float(duration)), 30.0)
            except (TypeError, ValueError):
                pass
        return s
    return max(rows, key=score)


def _fuzzy_matched_times(existing, sync_lines):
    """Deterministic alignment: fuzzy-match each existing line to a candidate
    line, require enough confidence, return {index: time} or None."""
    cand = [(_norm_line(txt), t) for t, txt in sync_lines if txt]
    if not cand:
        return None
    matched = {}
    used = set()
    for i, line in enumerate(existing):
        nl = _norm_line(line)
        if not nl:
            continue
        best_j, best_r = None, 0.0
        for j, (ctxt, _t) in enumerate(cand):
            if j in used:
                continue
            r = difflib.SequenceMatcher(None, nl, ctxt).ratio()
            if r > best_r:
                best_r, best_j = r, j
        if best_j is not None and best_r >= 0.72:
            matched[i] = cand[best_j][1]
            used.add(best_j)
    if len(matched) < max(2, math.ceil(0.4 * len(existing))):
        return None
    return matched


def _sync_matched_times_ai(config, existing, sync_lines):
    """AI alignment: ask the LLM to map existing line numbers to reference
    timestamps. Returns {index: time} or None on any failure."""
    ref = "\n".join(f"{_fmt_ts(t)} {txt}" for t, txt in sync_lines if txt)
    ext = "\n".join(f"{i + 1}. {ln}" for i, ln in enumerate(existing))
    user = f"SYNCED REFERENCE:\n{ref}\n\nEXISTING LINES:\n{ext}"
    text = ai_chat(config, _SYNC_SYSTEM, user)
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    import json as _json
    try:
        arr = _json.loads(m.group(0))
    except ValueError:
        return None
    if not isinstance(arr, list) or len(arr) != len(existing):
        return None
    matched = {}
    for i, v in enumerate(arr):
        if isinstance(v, (int, float)) and 0 <= float(v) < 3600:
            matched[i] = float(v)
    return matched or None


def _build_timed_lrc(existing, matched, duration=None):
    """{index: time} -> full LRC text; unmatched lines get interpolated
    timestamps between their matched neighbours instead of being dropped."""
    out = []
    last_t = -1.0
    pending = []
    def flush_pending(next_t):
        if not pending:
            return
        seg_start = max(last_t, 0.0)
        if next_t is None:
            next_t = seg_start + max(2.0, 3.0 * len(pending))
            if duration:
                next_t = min(next_t, max(seg_start + 1.0, float(duration) - 2.0))
        k = len(pending)
        for j, ptext in enumerate(pending):
            t = seg_start + (next_t - seg_start) * ((j + 1) / (k + 1))
            out.append((max(0.0, t), ptext))
        pending.clear()
    for i, line in enumerate(existing):
        t = matched.get(i)
        if t is not None and t >= last_t:
            flush_pending(t)
            out.append((t, line))
            last_t = t
        else:
            pending.append(line)
    flush_pending(None)
    out.sort(key=lambda x: x[0])
    return "\n".join(f"{_fmt_ts(t)} {txt}" for t, txt in out)


def lyrics_detect_sync(config, artist="", track="", album="", duration=None,
                       existing_text="", candidates=None):
    """One-stop lyrics detection & syncing for a track.

    Returns (lrc_text, source) where source is one of:
      * "candidate"  - track had no lyrics; matched candidate inserted
      * "ai-sync"    - existing wording aligned via the LLM
      * "aligned"    - existing wording aligned via fuzzy matching
      * "wordsync"   - input was already line-synced; upgraded to ELRC
      * "unchanged"  - only unsynced lyrics available and nothing to do
    """
    rows = _candidate_rows(candidates)
    existing = [ln.strip() for ln in (existing_text or "").splitlines() if ln.strip()]

    # Already carries timestamps: keep the wording, upgrade word-level sync.
    if existing_text and re.search(r"\[\d{1,2}:\d{1,2}", existing_text):
        return wordsync_lrc(existing_text), "wordsync"

    best = _best_candidate(rows, duration)

    if existing:
        if best and best["sync_lines"]:
            det = _fuzzy_matched_times(existing, best["sync_lines"])
            if ai_configured(config):
                try:
                    ai = _sync_matched_times_ai(config, existing, best["sync_lines"])
                except Exception:
                    ai = None
                if ai:
                    return wordsync_lrc(_build_timed_lrc(existing, ai, duration)), "ai-sync"
            if det:
                return wordsync_lrc(_build_timed_lrc(existing, det, duration)), "aligned"
        # nothing to align against — keep the user's wording untouched
        return existing_text.strip(), "unchanged"

    if best:
        if best["sync_lines"]:
            lrc = "\n".join(f"{_fmt_ts(t)} {txt}" for t, txt in best["sync_lines"])
            return wordsync_lrc(lrc), "candidate"
        if best["plain"].strip():
            return best["plain"].strip(), "candidate"
    return "", "unchanged"
