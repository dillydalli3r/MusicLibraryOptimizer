"""AI-assisted lyrics tooling.

Two kinds of helpers:

* ``ai_chat`` - a minimal OpenAI-compatible /chat/completions client
  (works with OpenAI, OpenRouter, llama.cpp, oobabooga, LM Studio, ...)
  configured through the ``ai_base_url`` / ``ai_api_key`` / ``ai_model``
  config keys.
* ``lyrics_clean`` / ``lyrics_repair`` - LLM-backed prompt wrappers that
  clean raw lyrics (ads, watermarks, layout garbage) and repair holes in
  imported lyrics using LRCLIB candidates.
* ``wordsync_lrc`` - deterministic (no AI) line→word sync: turns plain
  line-synced LRC into word-synced ELRC by distributing word times inside
  each line's slot, weighted by word length.
"""
import math
import os
import re

import httpx

from server.integrations import USER_AGENT

_WORD_SPLIT_RE = re.compile(r"\s+")
# A line slot should never stretch past the next line by more than this,
# so instrumental gaps don't get crawled by slowly-appearing words.
_MAX_LINE_SPREAD_S = 6.0
_MIN_WORD_SPAN_S = 0.18


def ai_config(config):
    """(base_url, api_key, model) from the flat config keys, normalized."""
    base = str(config.get("ai_base_url") or "").strip().rstrip("/")
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
    r.raise_for_status()
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

_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data",
                          "lyrics_ai_cache")

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
    return os.path.join(_CACHE_DIR, f"{mode}-{lang}-{h[:20]}.json")


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
    try:
        import json
        with open(cache, "r", encoding="utf-8") as fh:
            cached = json.load(fh)
        if isinstance(cached, list) and len(cached) == len(lines):
            return cached
    except OSError:
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

    try:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(_cache_path(mode, lang, lines), "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False)
    except OSError:
        pass
    return out
