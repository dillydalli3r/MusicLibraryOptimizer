"""Unified tag abstraction over FLAC / OGG / Opus / MP3 / MP4 audio files."""
import os

from mutagen.id3 import TextFrame, Frames

from .deps import (
    FLAC, OggVorbis, OggOpus, MP3, MP4, MP4FreeForm,
    TXXX, USLT, Encoding,
)
from .stats import _decode_mp4_value

TAG_MAP = {
    "GENRE": {
        "flac": "GENRE",
        "mp3": ("TCON", None),
        "mp4": "\xa9gen",
    },
    "ITUNESADVISORY": {
        "flac": "ITUNESADVISORY",
        "mp3": ("TXXX", "ITUNESADVISORY"),
        "mp4": ("freeform", "com.apple.iTunes", "ITUNESADVISORY"),
    },
    "ALBUMITUNESADVISORY": {
        "flac": "ALBUMITUNESADVISORY",
        "mp3": ("TXXX", "ALBUMITUNESADVISORY"),
        "mp4": ("freeform", "com.apple.iTunes", "ALBUMITUNESADVISORY"),
    },
    "REPLAYGAIN_TRACK_GAIN": {
        "flac": "REPLAYGAIN_TRACK_GAIN",
        "mp3": ("TXXX", "REPLAYGAIN_TRACK_GAIN"),
        "mp4": ("freeform", "com.apple.iTunes", "replaygain_track_gain"),
    },
    "REPLAYGAIN_TRACK_PEAK": {
        "flac": "REPLAYGAIN_TRACK_PEAK",
        "mp3": ("TXXX", "REPLAYGAIN_TRACK_PEAK"),
        "mp4": ("freeform", "com.apple.iTunes", "replaygain_track_peak"),
    },
    "REPLAYGAIN_ALBUM_GAIN": {
        "flac": "REPLAYGAIN_ALBUM_GAIN",
        "mp3": ("TXXX", "REPLAYGAIN_ALBUM_GAIN"),
        "mp4": ("freeform", "com.apple.iTunes", "replaygain_album_gain"),
    },
    "REPLAYGAIN_ALBUM_PEAK": {
        "flac": "REPLAYGAIN_ALBUM_PEAK",
        "mp3": ("TXXX", "REPLAYGAIN_ALBUM_PEAK"),
        "mp4": ("freeform", "com.apple.iTunes", "replaygain_album_peak"),
    },
    "DYNAMIC RANGE": {
        "flac": "DYNAMIC RANGE",
        "mp3": ("TXXX", "DYNAMIC RANGE"),
        "mp4": ("freeform", "com.apple.iTunes", "dynamic range"),
    },
    "ALBUM DYNAMIC RANGE": {
        "flac": "ALBUM DYNAMIC RANGE",
        "mp3": ("TXXX", "ALBUM DYNAMIC RANGE"),
        "mp4": ("freeform", "com.apple.iTunes", "album dynamic range"),
    },
    "INSTRUMENTAL": {
        "flac": "INSTRUMENTAL",
        "mp3": ("TXXX", "INSTRUMENTAL"),
        "mp4": ("freeform", "com.apple.iTunes", "INSTRUMENTAL"),
    },
    "MEDIA": {
        "flac": "MEDIA",
        "mp3": ("TXXX", "MEDIA"),
        "mp4": ("freeform", "com.apple.iTunes", "MEDIA"),
    },
    "SOURCE": {
        "flac": "SOURCE",
        "mp3": ("TXXX", "SOURCE"),
        "mp4": ("freeform", "com.apple.iTunes", "SOURCE"),
    },
    # AudioAuditor verdict written by the Audit Library script.
    # Values: REAL / FAKE.
    "AUDIT": {
        "flac": "AUDIT",
        "mp3": ("TXXX", "AUDIT"),
        "mp4": ("freeform", "com.apple.iTunes", "AUDIT"),
    },
    # Rip-log score (0-100) from AudioAuditor's cambia grading, written
    # to the tracks of MEDIA=CD releases only.
    "LOG_GRADE": {
        "flac": "LOG_GRADE",
        "mp3": ("TXXX", "LOG_GRADE"),
        "mp4": ("freeform", "com.apple.iTunes", "LOG_GRADE"),
    },
    # Integrity verification tags (see mlo/integrity.py):
    #   AUDIO_MD5  MD5 hex of the audio data (PCM for FLAC via decode,
    #              tag-stable audio region for MP3/MP4/OGG).
    #   INTEGRITY  OK / FAIL verdict of the audio integrity test.
    #   LOG_CRC    CD rips: OK / MISMATCH vs the rip log's per-track CRC.
    "AUDIO_MD5": {
        "flac": "AUDIO_MD5",
        "mp3": ("TXXX", "AUDIO_MD5"),
        "mp4": ("freeform", "com.apple.iTunes", "AUDIO_MD5"),
    },
    "INTEGRITY": {
        "flac": "INTEGRITY",
        "mp3": ("TXXX", "INTEGRITY"),
        "mp4": ("freeform", "com.apple.iTunes", "INTEGRITY"),
    },
    "LOG_CRC": {
        "flac": "LOG_CRC",
        "mp3": ("TXXX", "LOG_CRC"),
        "mp4": ("freeform", "com.apple.iTunes", "LOG_CRC"),
    },
}


class AudioFile:
    """Unified abstraction over FLAC / OGG / Opus / MP3 / MP4."""

    def __init__(self, path):
        self.path = path
        self.ext = os.path.splitext(path)[1].lower()
        self.kind = self._kind()
        self.audio = None
        self.error = None
        self._tag_cache = None
        self._load()

    def _invalidate_cache(self):
        """Drop the vorbis tag-read cache after any tag write."""
        self._tag_cache = None

    def _kind(self):
        if self.ext == ".flac":
            return "flac"
        if self.ext == ".ogg":
            return "ogg"
        if self.ext == ".opus":
            return "opus"
        if self.ext == ".mp3":
            return "mp3"
        if self.ext == ".aac":
            return "aac"
        if self.ext in (".m4a", ".mp4"):
            return "mp4"
        return None

    def _load(self):
        try:
            if self.kind == "flac":
                self.audio = FLAC(self.path)
            elif self.kind == "ogg":
                self.audio = OggVorbis(self.path)
            elif self.kind == "opus":
                self.audio = OggOpus(self.path)
            elif self.kind == "mp3":
                self.audio = MP3(self.path)
                if self.audio.tags is None:
                    self.audio.add_tags()
            elif self.kind == "mp4":
                self.audio = MP4(self.path)
            elif self.kind == "aac":
                try:
                    from mutagen.aac import AAC
                    self.audio = AAC(self.path)
                except Exception:
                    self.audio = None
        except Exception as e:
            self.audio = None
            self.error = f"{type(e).__name__}: {e}"

    # ------------------------------------------------------------------
    # Tag read
    # ------------------------------------------------------------------
    def get_tag(self, name):
        if self.audio is None:
            return None

        spec = TAG_MAP.get(name)
        if spec is None:
            return None

        kind = self.kind

        try:
            if kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    return None
                if self._tag_cache is None:
                    self._tag_cache = {
                        str(k).lower(): (v[0] if isinstance(v, list) and v else v)
                        for k, v in self.audio.tags.items()
                    }
                return self._tag_cache.get(spec["flac"].lower())

            elif kind == "mp3":
                frame_type, desc = spec["mp3"]

                if frame_type == "TCON":
                    for f in self.audio.tags.getall("TCON"):
                        return f.text[0] if f.text else None
                    return None

                for f in self.audio.tags.getall("TXXX"):
                    if f.desc == desc:
                        return f.text[0] if f.text else None
                return None

            elif kind == "mp4":
                atom = spec["mp4"]

                if isinstance(atom, tuple) and atom[0] == "freeform":
                    _, mean, name2 = atom
                    key = f"----:{mean}:{name2}"
                    vals = self.audio.tags.get(key) if self.audio.tags else None
                    if not vals:
                        return None
                    return _decode_mp4_value(vals[0])

                v = self.audio.get(atom)
                if isinstance(v, list) and v:
                    v = v[0]
                if isinstance(v, bytes):
                    return v.decode("utf-8", "replace")
                return str(v) if v is not None else None

        except Exception:
            return None

        return None

    def has_tag(self, name):
        v = self.get_tag(name)
        return v is not None and str(v).strip() != ""

    # ------------------------------------------------------------------
    # Generic tag enumeration / edit (used by the GUI tag editor)
    # ------------------------------------------------------------------
    def all_tags(self):
        """Return {display_key: value} for every textual tag on the file.

        Keys are the raw container keys (vorbis comment names, ID3 frame
        IDs, MP4 atoms). Binary frames (cover art, unsynced lyrics) are
        skipped.
        """
        if self.audio is None or self.audio.tags is None:
            return {}

        out = {}
        try:
            if self.kind in ("flac", "ogg", "opus"):
                for k, v in self.audio.tags.items():
                    val = v[0] if isinstance(v, list) and v else v
                    if isinstance(val, bytes):
                        continue
                    out[str(k)] = str(val)

            elif self.kind == "mp3":
                for frame in self.audio.tags.values():
                    fid = getattr(frame, "FrameID", None)
                    if not fid:
                        continue
                    if fid == "TXXX":
                        out[f"TXXX:{frame.desc}"] = (
                            str(frame.text[0]) if frame.text else "")
                    elif fid in ("USLT", "APIC", "COMM"):
                        continue
                    elif isinstance(frame, TextFrame):
                        out[fid] = str(frame.text[0]) if frame.text else ""

            elif self.kind == "mp4":
                for k, v in self.audio.tags.items():
                    if k == "covr":
                        continue
                    val = v[0] if isinstance(v, list) and v else v
                    if isinstance(val, MP4FreeForm):
                        val = _decode_mp4_value(val)
                    if isinstance(val, bytes):
                        continue
                    out[str(k)] = str(val)
        except Exception:
            return {}
        return out

    def set_any_tag(self, key, value):
        """Write an arbitrary tag key (raw container key)."""
        self._invalidate_cache()
        if self.audio is None:
            return False
        value = str(value)

        try:
            if self.kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    if hasattr(self.audio, "add_tags"):
                        self.audio.add_tags()
                    else:
                        return False
                self.audio.tags[str(key)] = value
                self.audio.save()
                return True

            elif self.kind == "mp3":
                if self.audio.tags is None:
                    self.audio.add_tags()
                if str(key).startswith("TXXX:"):
                    desc = str(key)[5:]
                    for frame in list(self.audio.tags.getall("TXXX")):
                        if frame.desc == desc:
                            try:
                                del self.audio.tags[frame.HashKey]
                            except Exception:
                                pass
                    self.audio.tags.add(
                        TXXX(encoding=Encoding.UTF8, desc=desc, text=[value])
                    )
                else:
                    self.audio.tags.delall(str(key))
                    frame_cls = Frames.get(str(key))
                    if frame_cls is None:
                        frame_cls = type(
                            str(key), (TextFrame,), {"FrameID": str(key)})
                    self.audio.tags.add(
                        frame_cls(encoding=Encoding.UTF8, text=[value])
                    )
                self.audio.save()
                return True

            elif self.kind == "mp4":
                if str(key).startswith("----:"):
                    _, mean, name = str(key).split(":", 3)
                    fmt = getattr(MP4FreeForm, "FORMAT_UTF8", 1)
                    try:
                        self.audio[str(key)] = [
                            MP4FreeForm(value.encode("utf-8"), dataformat=fmt)
                        ]
                    except TypeError:
                        self.audio[str(key)] = [
                            MP4FreeForm(value.encode("utf-8"))
                        ]
                else:
                    self.audio[str(key)] = [value]
                self.audio.save()
                return True

        except Exception as e:
            self.error = f"set_any_tag: {e}"
            return False
        return False

    def delete_any_tag(self, key):
        """Remove an arbitrary tag key (raw container key)."""
        self._invalidate_cache()
        if self.audio is None:
            return False

        try:
            if self.kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    return True
                target = str(key).lower()
                changed = False
                for k in list(self.audio.tags.keys()):
                    if str(k).lower() == target:
                        del self.audio.tags[k]
                        changed = True
                if changed:
                    self.audio.save()
                return True

            elif self.kind == "mp3":
                if self.audio.tags is None:
                    return True
                if str(key).startswith("TXXX:"):
                    desc = str(key)[5:]
                    for frame in list(self.audio.tags.getall("TXXX")):
                        if frame.desc == desc:
                            try:
                                del self.audio.tags[frame.HashKey]
                            except Exception:
                                pass
                else:
                    self.audio.tags.delall(str(key))
                self.audio.save()
                return True

            elif self.kind == "mp4":
                if str(key) in self.audio:
                    del self.audio[str(key)]
                    self.audio.save()
                return True

        except Exception as e:
            self.error = f"delete_any_tag: {e}"
            return False
        return False

    # ------------------------------------------------------------------
    # Tag write / delete, used for SOURCE normalization
    # ------------------------------------------------------------------
    def set_tag(self, name, value):
        self._invalidate_cache()
        if self.audio is None:
            return False

        spec = TAG_MAP.get(name)
        if spec is None:
            return False

        kind = self.kind
        value = str(value)

        try:
            if kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    if hasattr(self.audio, "add_tags"):
                        self.audio.add_tags()
                    else:
                        return False
                self.audio.tags[spec["flac"]] = value
                self.audio.save()
                return True

            elif kind == "mp3":
                frame_type, desc = spec["mp3"]
                if frame_type != "TXXX":
                    return False

                if self.audio.tags is None:
                    self.audio.add_tags()

                for frame in list(self.audio.tags.getall("TXXX")):
                    if frame.desc == desc:
                        try:
                            del self.audio.tags[frame.HashKey]
                        except Exception:
                            pass

                self.audio.tags.add(
                    TXXX(encoding=Encoding.UTF8, desc=desc, text=[value])
                )
                self.audio.save()
                return True

            elif kind == "mp4":
                atom = spec["mp4"]

                if isinstance(atom, tuple) and atom[0] == "freeform":
                    _, mean, name2 = atom
                    key = f"----:{mean}:{name2}"

                    fmt = getattr(MP4FreeForm, "FORMAT_UTF8", 1)

                    try:
                        self.audio[key] = [
                            MP4FreeForm(
                                value.encode("utf-8"),
                                dataformat=fmt,
                            )
                        ]
                    except TypeError:
                        self.audio[key] = [
                            MP4FreeForm(value.encode("utf-8"))
                        ]
                else:
                    self.audio[atom] = [value]

                self.audio.save()
                return True

        except Exception as e:
            self.error = f"set_tag: {e}"
            return False

        return False

    def delete_tag(self, name):
        self._invalidate_cache()
        if self.audio is None:
            return False

        spec = TAG_MAP.get(name)
        if spec is None:
            return False

        kind = self.kind

        try:
            if kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    return True

                target = spec["flac"].lower()
                changed = False

                for k in list(self.audio.tags.keys()):
                    if str(k).lower() == target:
                        del self.audio.tags[k]
                        changed = True

                if changed:
                    self.audio.save()

                return True

            elif kind == "mp3":
                frame_type, desc = spec["mp3"]
                if frame_type != "TXXX":
                    return False

                if self.audio.tags is None:
                    return True

                changed = False

                for frame in list(self.audio.tags.getall("TXXX")):
                    if frame.desc == desc:
                        try:
                            del self.audio.tags[frame.HashKey]
                            changed = True
                        except Exception:
                            pass

                if changed:
                    self.audio.save()

                return True

            elif kind == "mp4":
                atom = spec["mp4"]

                if isinstance(atom, tuple) and atom[0] == "freeform":
                    _, mean, name2 = atom
                    key = f"----:{mean}:{name2}"
                    if key in self.audio:
                        del self.audio[key]
                        self.audio.save()
                    return True

                if atom in self.audio:
                    del self.audio[atom]
                    self.audio.save()

                return True

        except Exception as e:
            self.error = f"delete_tag: {e}"
            return False

        return False

    # ------------------------------------------------------------------
    # Lyrics
    # ------------------------------------------------------------------
    def get_lyrics(self):
        try:
            if self.kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    return None
                for k, v in self.audio.tags.items():
                    if str(k).lower() in ("lyrics", "unsyncedlyrics"):
                        return "\n".join(v) if isinstance(v, list) else str(v)
                return None

            elif self.kind == "mp3":
                for f in self.audio.tags.getall("USLT"):
                    if isinstance(f.text, list):
                        return "\n".join(f.text) if f.text else None
                    return str(f.text) if f.text else None
                return None

            elif self.kind == "mp4":
                v = self.audio.get("\xa9lyr")
                if isinstance(v, list) and v:
                    v = v[0]
                if isinstance(v, bytes):
                    return v.decode("utf-8", "replace")
                return str(v) if v is not None else None

        except Exception:
            return None

        return None

    def set_lyrics(self, text):
        self._invalidate_cache()
        try:
            if self.kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    if hasattr(self.audio, "add_tags"):
                        self.audio.add_tags()
                    else:
                        return False
                for k in list(self.audio.tags.keys()):
                    if str(k).lower() in ("lyrics", "unsyncedlyrics"):
                        del self.audio.tags[k]

                self.audio.tags["LYRICS"] = text
                self.audio.save()
                return True

            elif self.kind == "mp3":
                self.audio.tags.delall("USLT")
                self.audio.tags.add(
                    USLT(encoding=Encoding.UTF8, lang="eng", desc="", text=text)
                )
                self.audio.save()
                return True

            elif self.kind == "mp4":
                self.audio["\xa9lyr"] = text
                self.audio.save()
                return True

        except Exception as e:
            self.error = f"set_lyrics: {e}"
            return False

        return False

    def delete_lyrics(self):
        self._invalidate_cache()
        try:
            if self.kind in ("flac", "ogg", "opus"):
                if self.audio.tags is None:
                    return True  # nothing to delete
                for k in list(self.audio.tags.keys()):
                    if str(k).lower() in ("lyrics", "unsyncedlyrics"):
                        del self.audio.tags[k]
                self.audio.save()
                return True

            elif self.kind == "mp3":
                self.audio.tags.delall("USLT")
                self.audio.save()
                return True

            elif self.kind == "mp4":
                if "\xa9lyr" in self.audio:
                    del self.audio["\xa9lyr"]
                    self.audio.save()
                return True

        except Exception as e:
            self.error = f"delete_lyrics: {e}"
            return False

        return False

