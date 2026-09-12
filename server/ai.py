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
* ``wordsync_lrc`` - deterministic (no AI) line→word/syllable sync: turns
  plain line-synced LRC into word-synced (or glued syllable-synced) ELRC
  by distributing times inside each line's slot, weighted by length.
* ``lyrics_align_audio`` - REAL acoustic alignment: the track audio is
  sent to an audio-capable model which returns per-syllable timestamps
  for the stored wording.
"""
import difflib
import math
import os
import re
import threading
import unicodedata

import httpx

from server.integrations import USER_AGENT

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


def ai_effort(config):
    """Reasoning effort for AI calls: HIGH by default (the models are asked
    for maximum thinking — alignment and repair quality beat latency
    here). MINIMAL disables thinking entirely for speed."""
    raw = str(config.get("ai_effort") or "high").strip().lower()
    return raw if raw in ("minimal", "low", "medium", "high") else "high"


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
    # Reasoning effort (OpenAI-style field; Google's OpenAI-compatible
    # endpoint maps it onto thinking budgets). Providers that reject the
    # unknown field get one plain retry.
    effort = ai_effort(config)
    if effort != "minimal":
        body["reasoning_effort"] = effort
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers,
                   timeout=timeout)
    if r.status_code >= 400 and "reasoning_effort" in body:
        body.pop("reasoning_effort")
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


def wordsync_lrc(lrc_text, level="word"):
    """Turn line-synced LRC into word- or syllable-synced ELRC.

    Delegates to mlo.lyrics.elrc_word_sync — the shared builder also powers
    the transliterate/translate script, so transformed lyrics carry the
    same kind of timings. level="syllable" glues per-syllable tags inside
    each word; CJK text sweeps per character (one kana = one syllable).
    """
    from mlo.lyrics import elrc_word_sync
    return elrc_word_sync(lrc_text, level=level)


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


# Transcription of last resort: the model writes the lyrics it knows for a
# song that has no local text and no usable LRCLIB candidate. Any language
# the model knows works — the answer comes back in the song's own script.
_TRANSCRIBE_SYSTEM = (
    "You are a lyrics database. You are given an artist and a song title "
    "(and maybe an album). Write out that song's complete official lyrics "
    "in the original language and script, one line per line, preserving "
    "verse/chorus repetition exactly as sung. Do NOT add section labels "
    "like [Verse] or [Chorus], do not translate, do not add commentary. "
    "If you do not actually know this song's lyrics, respond with exactly "
    "the single word UNKNOWN."
)


def lyrics_transcribe(config, artist="", track="", album="", duration=None):
    """LLM transcription fallback. Returns the lyrics as plain text, or ''
    when the model doesn't know the song."""
    user = f"Artist: {artist}\nTrack: {track}"
    if album:
        user += f"\nAlbum: {album}"
    if duration:
        user += f"\nDuration: {int(duration)} seconds"
    text = ai_chat(config, _TRANSCRIBE_SYSTEM, user, timeout=120.0)
    text = (text or "").strip()
    if not text or text.upper().startswith("UNKNOWN") or text.upper() == "UNKNOWN.":
        return ""
    # strip a stray code fence if the model wrapped the output
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?|\n?```$", "", text, flags=re.IGNORECASE).strip()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 3:
        return ""  # too short to be real lyrics — model likely refused
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Acoustic syllable alignment: the audio itself is sent to an audio-capable
# model (Gemini native inline audio when the base URL is Google's; the
# OpenAI input_audio content part otherwise) together with the lyric lines,
# and the model returns a real start time plus per-syllable timestamps for
# every line. This is genuine alignment against the recording — not the
# deterministic length-proportional distribution of wordsync_lrc, which
# stays as the offline fallback.
# --------------------------------------------------------------------------- #

_ALIGN_SYSTEM = (
    "You are a precise lyrics synchronizer. You HEAR a song and you get its "
    "numbered lyric lines. Find when each line starts in the audio and "
    "timestamp EVERY SYLLABLE as it is actually sung.\n"
    "Respond with ONLY a JSON object: {\"lines\": [{\"i\": <line number>, "
    "\"start\": <seconds>, \"syl\": [{\"t\": <seconds>, \"x\": "
    "\"<syllable text>\"}, ...]}, ...]} covering EVERY line, in order.\n"
    "Rules:\n"
    "- Timestamps are seconds from the start of the audio with TWO decimals "
    "(e.g. 49.95).\n"
    "- syl breaks each word into its SUNG syllables, e.g. the line "
    "\"Conversion, software version 7.0\" becomes: "
    "[{\"t\":49.95,\"x\":\"Con\"},{\"t\":50.10,\"x\":\"ver\"},"
    "{\"t\":50.30,\"x\":\"sion, \"},{\"t\":52.08,\"x\":\"soft\"},"
    "{\"t\":52.30,\"x\":\"ware \"},{\"t\":53.63,\"x\":\"ver\"},"
    "{\"t\":53.85,\"x\":\"sion \"},{\"t\":54.98,\"x\":\"7.0\"}]\n"
    "- The x texts concatenated in order MUST reproduce the line text "
    "exactly, attaching each space to the END of the preceding syllable.\n"
    "- For Japanese/Chinese/Korean give one entry per character.\n"
    "- No commentary — JSON only."
)

# Gemini native schema: forces the exact response shape regardless of model.
_ALIGN_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "start": {"type": "number"},
                    "syl": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "t": {"type": "number"},
                                "x": {"type": "string"},
                            },
                            "required": ["t", "x"],
                        },
                    },
                },
                "required": ["i", "start", "syl"],
            },
        },
    },
    "required": ["lines"],
}


def _align_model(config):
    """The model used for acoustic alignment (override or the chat model)."""
    _base, _key, model = ai_config(config)
    return str(config.get("ai_align_model") or "").strip() or model


def _ffmpeg_bin():
    """The app's managed ffmpeg (full-featured build) when installed, else
    whatever is on PATH."""
    try:
        from mlo.tools import detect_all_tools
        exe = (detect_all_tools().get("ffmpeg") or {}).get("ffmpeg_exe")
        if exe and os.path.isfile(str(exe)):
            return str(exe)
    except Exception:
        pass
    return "ffmpeg"


def _ffmpeg_audio_payload(audio_path):
    """(base64, mime) of a compact mono transcode of the track — small
    enough for an inline-audio request, big enough to align syllables.
    Prefers Opus; falls back to MP3 and then lossless FLAC/WAV for builds
    without the licensed encoders."""
    import base64
    import subprocess
    import tempfile

    ffmpeg = _ffmpeg_bin()

    def _run(args, fmt):
        fd, tmp = tempfile.mkstemp(suffix=".bin")
        os.close(fd)
        try:
            proc = subprocess.run(
                [ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                 "-i", str(audio_path), "-ac", "1", "-ar", "24000", *args,
                 "-f", fmt, tmp],
                capture_output=True)
            if proc.returncode == 0 and os.path.getsize(tmp) > 0:
                with open(tmp, "rb") as fh:
                    return base64.b64encode(fh.read()).decode("ascii")
            return None
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    for enc, fmt, mime in ((["-c:a", "libopus", "-b:a", "48k"], "ogg", "audio/ogg"),
                           (["-c:a", "libmp3lame", "-q:a", "6"], "mp3", "audio/mpeg"),
                           (["-c:a", "flac", "-ar", "16000"], "flac", "audio/flac"),
                           (["-c:a", "pcm_s16le", "-ar", "16000"], "wav", "audio/wav")):
        b64 = _run(enc, fmt)
        if b64:
            return b64, mime
    raise ValueError("ffmpeg could not decode this track for alignment")


def _align_chat(config, prompt, audio_b64, audio_mime, timeout=300.0):
    """One audio+text request to the alignment model; returns its text."""
    base, key, _m = ai_config(config)
    model = _align_model(config)
    if not base or not model:
        raise ValueError("AI is not configured — set base URL and model in Settings → AI")
    if _GEMINI_HOST in base:
        headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
        if key:
            headers["x-goog-api-key"] = key
        effort = ai_effort(config)
        gen = {
            "temperature": 0.1,
            "responseMimeType": "application/json",
            "responseSchema": _ALIGN_RESPONSE_SCHEMA,
        }
        # thinking budgets: 0 = off (minimal), -1 = dynamic maximum
        gen["thinkingConfig"] = {"thinkingBudget": {"minimal": 0, "low": 1024, "medium": 8192}.get(effort, -1)}
        body = {
            "contents": [{"role": "user", "parts": [
                {"text": prompt},
                {"inline_data": {"mime_type": audio_mime, "data": audio_b64}},
            ]}],
            "generationConfig": gen,
        }
        r = httpx.post(
            f"https://{_GEMINI_HOST}/v1beta/models/{model}:generateContent",
            json=body, headers=headers, timeout=timeout)
        if r.status_code >= 400:
            detail = (r.text or "").strip().replace("\n", " ")[:300]
            raise ValueError(f"AI endpoint returned {r.status_code}: {detail}")
        data = r.json()
        try:
            parts = data["candidates"][0]["content"]["parts"]
            text = "".join(str(p.get("text") or "") for p in parts)
        except (KeyError, IndexError, TypeError):
            raise ValueError(f"unexpected AI response shape: {str(data)[:200]}")
        return (text or "").strip()
    # Generic OpenAI-compatible endpoint: audio rides as an input_audio part.
    fmt = "mp3" if "mpeg" in audio_mime else ("wav" if "wav" in audio_mime else "ogg")
    headers = {"User-Agent": USER_AGENT, "Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    effort = ai_effort(config)
    body = {
        "model": model,
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": _ALIGN_SYSTEM},
            {"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "input_audio",
                 "input_audio": {"data": audio_b64, "format": fmt}},
            ]},
        ],
    }
    if effort != "minimal":
        body["reasoning_effort"] = effort
    r = httpx.post(f"{base}/chat/completions", json=body, headers=headers,
                   timeout=timeout)
    if r.status_code >= 400 and "reasoning_effort" in body:
        body.pop("reasoning_effort")
        r = httpx.post(f"{base}/chat/completions", json=body, headers=headers,
                       timeout=timeout)
    if r.status_code >= 400:
        detail = (r.text or "").strip().replace("\n", " ")[:300]
        raise ValueError(f"AI endpoint returned {r.status_code}: {detail}")
    data = r.json()
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ValueError(f"unexpected AI response shape: {str(data)[:200]}")
    if isinstance(content, list):
        content = "".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return (content or "").strip()


def _align_parse_model_json(raw):
    """Model output -> {line_no: {"start": float, "syl": [(t, text)]}}.
    Accepts both syllable pair shapes ([t, "x"] tuples and {"t","x"}
    objects). Lines whose syllables carry no real subdivision (every time
    identical — the model answered line-level only) are dropped so the
    deterministic per-line distribution takes over instead."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?|\n?```$", "", raw, flags=re.IGNORECASE).strip()
    import json as _json
    start = raw.find("{")
    arr_start = raw.find("[")
    if start == -1 or (arr_start != -1 and arr_start < start):
        # a bare top-level array of lines is still usable
        payload = raw[arr_start:] if arr_start != -1 else raw
    else:
        payload = raw[start:]
    try:
        # raw_decode parses ONE complete value and tolerates anything the
        # model appended after it (commentary, a second guess, whitespace).
        data = _json.JSONDecoder().raw_decode(payload)[0]
    except ValueError as e:
        raise ValueError(f"alignment JSON invalid: {e}: {raw[:160]}")
    rows = data.get("lines") if isinstance(data, dict) else data
    out = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            i = int(row.get("i"))
            s = float(row.get("start"))
        except (TypeError, ValueError, KeyError):
            continue
        if not (0 <= s < 7200):
            continue
        syl = []
        for piece in row.get("syl") or []:
            if isinstance(piece, dict):
                try:
                    t, txt = float(piece.get("t")), str(piece.get("x"))
                except (TypeError, ValueError):
                    continue
            elif isinstance(piece, (list, tuple)) and len(piece) >= 2:
                try:
                    t, txt = float(piece[0]), str(piece[1])
                except (TypeError, ValueError):
                    continue
            else:
                continue
            if txt:
                syl.append((max(0.0, t), txt))
        # degenerate: no per-syllable subdivision at all → not real sync
        if syl and len({round(t, 2) for t, _x in syl}) <= 1 and len(syl) > 1:
            continue
        if syl:
            out[i] = {"start": max(0.0, s), "syl": syl}
    if not out:
        raise ValueError(f"alignment model returned no usable lines: {raw[:160]}")
    return out


def _alnum_norm(s):
    """Alignment validation form: case/whitespace/punctuation-insensitive,
    unicode-letter aware (CJK stays)."""
    s = unicodedata.normalize("NFKC", str(s or "")).lower()
    return re.sub(r"[\W_]+", "", s)


def _line_syllable_pieces(body):
    """Canonical syllable pieces of one line: [(text, word_end)] with
    tokens separated by single spaces — the same split the deterministic
    builder and the frontend editor use, so the emitted tags are always
    canonical regardless of how the model spaced its pieces."""
    from mlo.lyrics import _syllabify_token
    pieces = []
    tokens = str(body or "").strip().split()
    for ti, tok in enumerate(tokens):
        syls = _syllabify_token(tok)
        for si, s in enumerate(syls):
            pieces.append((s, si == len(syls) - 1 and ti < len(tokens) - 1))
    return pieces


def _sample_model_times(model_syl, count, line_start, line_end):
    """Map `count` canonical pieces onto the model's acoustic syllable
    times: 1:1 when the counts match, otherwise monotone sampling /
    interpolation across the model's time sequence, clamped to the line
    span."""
    mtimes = [t for t, _x in model_syl]
    if not mtimes:
        return []
    if len(mtimes) == 1:
        return [mtimes[0]] * count
    out = []
    for k in range(count):
        pos = k * (len(mtimes) - 1) / max(count - 1, 1)
        lo = int(math.floor(pos))
        hi = min(int(math.ceil(pos)), len(mtimes) - 1)
        frac = pos - lo
        t = mtimes[lo] + (mtimes[hi] - mtimes[lo]) * frac
        out.append(t)
    for k in range(1, count):
        out[k] = max(out[k], out[k - 1])
    out = [min(max(t, line_start), max(line_start, line_end)) for t in out]
    return out


def _progress_fn(progress):
    """Wrap an optional progress(stage, pct) callback so pipeline code can
    fire updates without None checks, and callback errors never break the
    alignment."""
    if progress is None:
        return lambda stage, pct: None

    def _safe(stage, pct):
        try:
            progress(stage, pct)
        except Exception:
            pass
    return _safe


def lyrics_align_audio(config, lrc_text, audio_path, timeout=300.0,
                       progress=None):
    """Acoustically align lyrics to the track audio at syllable level.

    The model listens to the track and returns a real start time plus
    per-syllable timestamps for every line. The STORED WORDING is never
    changed: the model's times are mapped onto the canonical syllable
    split of the stored text (1:1 when the counts match, monotone
    sampling otherwise), so spacing and punctuation always stay perfect.
    Lines the model missed, mis-ordered, or mismatched beyond
    punctuation differences keep their slot with deterministic
    distribution. Returns (elrc_text, {"aligned": k, "total": n}).
    """
    if not audio_path or not os.path.isfile(str(audio_path)):
        raise ValueError("no audio file to align against")
    progress = _progress_fn(progress)
    rows = []  # (previous start or None, body)
    for raw_line in (lrc_text or "").splitlines():
        stamps = _ALL_TIMES_RE.findall(raw_line)
        body = _ALL_TIMES_RE.sub("", raw_line)
        body = _WORD_TAG_RE.sub("", body).strip()
        if not body and not stamps:
            continue
        start = None
        if stamps:
            start = _ts_to_s(stamps[-1][0], stamps[-1][1], stamps[-1][2])
        if body:
            rows.append([start, body])
    if not rows:
        raise ValueError("no lyric lines to align")

    numbered = "\n".join(f"{i + 1}. {body}" for i, (_s, body) in enumerate(rows))
    progress("transcode", 8)
    audio_b64, audio_mime = _ffmpeg_audio_payload(audio_path)
    progress("listen", 30)
    raw = _align_chat(config, f"LYRIC LINES:\n{numbered}", audio_b64,
                      audio_mime, timeout=timeout)
    progress("align", 85)
    got = _align_parse_model_json(raw)

    # The model's line NUMBERS are untrustworthy (they drift, skip intros,
    # shift by one) — its TEXTS are not. Assign each returned row to the
    # stored line carrying the same words: exact (punctuation/case/spacing
    # insensitive) first, then fuzzy; repeated lines (chorus, "disorder
    # disorder disorder") are consumed in time order against the stored
    # order, which is chronological.
    used: set = set()
    assign = {}  # stored row index -> hit

    def _assign(hit):
        key = _alnum_norm("".join(x for _t, x in hit["syl"]))
        if not key:
            return
        cands = [i for i, body in enumerate(rows) if i not in used
                 and _alnum_norm(body) == key]
        if not cands:
            import difflib as _difflib
            best_i, best_r = None, 0.0
            for i, body in enumerate(rows):
                if i in used:
                    continue
                r = _difflib.SequenceMatcher(None, key, _alnum_norm(body)).ratio()
                if r > best_r:
                    best_r, best_i = r, i
            if best_i is not None and best_r >= 0.72:
                cands = [best_i]
        if cands:
            used.add(cands[0])
            assign[cands[0]] = hit

    for _i, hit in sorted(got.items(), key=lambda kv: kv[1]["start"]):
        _assign(hit)

    out = []
    aligned = 0
    last_known = None
    pending: list = []

    def _flush_pending(next_t):
        """Rows the model missed get interpolated times between the last
        known line and the next known one (never 0:00.00 — the formatter's
        canonical form forbids a tight zero stamp)."""
        nonlocal last_known
        if not pending:
            return
        seg_start = last_known if last_known is not None else 0.0
        if next_t is None or next_t <= seg_start + 0.2:
            next_t = seg_start + max(2.0, 3.0 * len(pending))
        k = len(pending)
        for j, body in enumerate(pending):
            t = max(seg_start + (next_t - seg_start) * ((j + 1) / (k + 1)), 0.01)
            out.append(f"{_fmt_ts(t)}{body}")
        pending.clear()

    for i, (prev_start, body) in enumerate(rows):
        hit = assign.get(i)
        used_model = False
        if hit and hit["syl"]:
            s = hit["start"]
            # reject out-of-order hits (the model shuffling verses): a real
            # start can repeat a previous one (duets) but never jump far back
            if last_known is None or s >= last_known - 0.05:
                # the next ASSIGNED line bounds this line's window
                nxt = None
                for j in range(i + 1, len(rows)):
                    h2 = assign.get(j)
                    if h2 and (last_known is None or h2["start"] >= s - 0.05):
                        nxt = h2["start"]
                        break
                _flush_pending(max(s, 0.01))
                # a real line can start at 0:00 (cold open), but a tight
                # [00:00.00] stamp collides with the formatter's zero-
                # timestamp canonical form — keep the first centisecond
                s = max(s, 0.01)
                pieces = _line_syllable_pieces(body)
                times = _sample_model_times(hit["syl"], len(pieces), s,
                                            nxt if nxt and nxt > s else s + min(6.0, 0.35 * max(len(pieces), 1)))
                # group pieces into words; glue the tags inside a word
                word_groups = []
                for (ptext, wend), t in zip(pieces, times):
                    if word_groups and not word_groups[-1][1]:
                        word_groups[-1][0].append((t, ptext))
                        word_groups[-1][1] = wend
                    else:
                        word_groups.append([[(t, ptext)], wend])
                line_tags = []
                for group, _wend in word_groups:
                    tags = "".join(f"<{_fmt_ts(t)[1:-1]}>{txt}" for t, txt in group)
                    line_tags.append(tags)
                out.append(f"{_fmt_ts(s)}" + " ".join(line_tags))
                aligned += 1
                used_model = True
                last_known = s
        if not used_model:
            pending.append(body)

    _flush_pending(None)

    # Re-positioned lines (the model finding a chorus later in the song
    # than the stale stored copy had it) can leave the list non-chronological;
    # LRC files are time-ordered, so sort stably by line time (ties —
    # background vocals at the same moment — keep their stored order).
    def _line_time(ln):
        m = re.match(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]", ln)
        return _ts_to_s(m.group(1), m.group(2), m.group(3)) if m else 0.0

    out.sort(key=_line_time)
    text = "\n".join(out)
    # Canonicalize: acoustically-aligned syllable lines pass through
    # elrc_word_sync untouched; any fallback line-synced leftovers get
    # deterministic syllable distribution inside their slots.
    from mlo.lyrics import elrc_word_sync
    text = elrc_word_sync(text, level="syllable")
    return text, {"aligned": aligned, "total": len(rows)}


def _cfg_sync_level(config):
    return str(config.get("lrc_sync_level") or "SYLLABLE").lower()


def _maybe_align(config, lrc_text, audio_path, progress=None):
    """Acoustic syllable alignment when AI + audio are available; returns
    (lrc, aligned?). Failures fall back silently to the caller's path."""
    if not audio_path or not ai_configured(config):
        return lrc_text, False
    try:
        aligned, _info = lyrics_align_audio(config, lrc_text, audio_path,
                                            progress=progress)
        return aligned, True
    except Exception:
        return lrc_text, False


def lyrics_detect_sync(config, artist="", track="", album="", duration=None,
                       existing_text="", candidates=None, audio_path=None,
                       progress=None):
    """One-stop lyrics detection & syncing for a track.

    Returns (lrc_text, source). When an audio file is supplied and AI is
    configured, every timed result is acoustically aligned to syllable
    level first (source gains "+align"); without audio the deterministic
    builder applies at the configured lrc_sync_level. source is one of:
      * "candidate"      - track had no lyrics; matched candidate inserted
      * "ai-sync"        - existing wording aligned via the LLM
      * "aligned"        - existing wording aligned via fuzzy matching
      * "wordsync"       - input was already line-synced; upgraded to
                           word/syllable ELRC
      * "ai-transcribe"  - nothing local or on LRCLIB; the LLM wrote the
                           lyrics from its own knowledge of the song
      * "unchanged"      - only unsynced lyrics available and nothing to do
    """
    progress = _progress_fn(progress)
    rows = _candidate_rows(candidates)
    existing = [ln.strip() for ln in (existing_text or "").splitlines() if ln.strip()]
    level = _cfg_sync_level(config)

    # Already carries timestamps: keep the wording, re-sync word/syllable
    # level — acoustically when the audio is available.
    if existing_text and re.search(r"\[\d{1,2}:\d{1,2}", existing_text):
        aligned, ok = _maybe_align(config, existing_text, audio_path,
                                   progress=progress)
        if ok:
            return aligned, "ai-align"
        progress("build", 90)
        return wordsync_lrc(existing_text, level=level), "wordsync"

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
                    lrc = _build_timed_lrc(existing, ai, duration)
                    aligned, ok = _maybe_align(config, lrc, audio_path, progress=progress)
                    return (aligned, "ai-sync+align") if ok else (wordsync_lrc(lrc, level=level), "ai-sync")
            if det:
                lrc = _build_timed_lrc(existing, det, duration)
                aligned, ok = _maybe_align(config, lrc, audio_path, progress=progress)
                return (aligned, "aligned+align") if ok else (wordsync_lrc(lrc, level=level), "aligned")
        # nothing to align against on LRCLIB — the audio itself is the
        # reference: acoustically timestamp the user's own lines. When
        # alignment is impossible keep the wording untouched.
        aligned, ok = _maybe_align(config, "\n".join(existing), audio_path,
                                   progress=progress)
        if ok:
            return aligned, "ai-align"
        return existing_text.strip(), "unchanged"

    if best:
        if best["sync_lines"]:
            lrc = "\n".join(f"{_fmt_ts(t)} {txt}" for t, txt in best["sync_lines"])
            aligned, ok = _maybe_align(config, lrc, audio_path, progress=progress)
            return (aligned, "candidate+align") if ok else (wordsync_lrc(lrc, level=level), "candidate")
        if best["plain"].strip():
            aligned, ok = _maybe_align(config, best["plain"].strip(), audio_path, progress=progress)
            if ok:
                return aligned, "candidate+align"
            return best["plain"].strip(), "candidate"

    # Last resort: nothing stored and LRCLIB has nothing usable — ask the
    # AI to transcribe the lyrics from its own knowledge of the song, then
    # align that transcription against the audio so it still arrives
    # syllable-synced when the audio is available.
    if ai_configured(config):
        try:
            text = lyrics_transcribe(config, artist, track, album, duration)
        except Exception:
            text = ""
        if text:
            aligned, ok = _maybe_align(config, text, audio_path, progress=progress)
            if ok:
                return aligned, "ai-transcribe+align"
            return text, "ai-transcribe"
    return "", "unchanged"
