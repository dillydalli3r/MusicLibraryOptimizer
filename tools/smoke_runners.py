"""Smoke-run the mlo script runners against a synthetic album.

Verifies the Run All pipeline (scripts 1-5, 7, 9-12) executes without
crashing on real (tiny) FLACs. 13 (network lyrics fetch) and 14 (full beets
import) are environment-dependent and only config-checked.

Run:  python tools/smoke_runners.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

FLAC = os.path.join(ROOT, ".dependencies", "flac v1.5.0", "flac.exe")


def make_flac(path, title, track):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    wav = path + ".tmp.wav"
    with wave.open(wav, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00\x00\x00" * 44100)
    subprocess.run([FLAC, "-f", "-s", "--totally-silent", "-o", path, wav], check=True)
    os.remove(wav)
    from mutagen.flac import FLAC as MFLAC

    f = MFLAC(path)
    f["TITLE"] = title
    f["ARTIST"] = "Smoke Artist"
    f["ALBUMARTIST"] = "Smoke Artist"
    f["ALBUM"] = "Smoke Album"
    f["TRACKNUMBER"] = f"{track:02d}"
    f["DISCNUMBER"] = "1"
    f["DATE"] = "2020"
    f["GENRE"] = "Test"
    f["MEDIA"] = "CD"
    f.save()


def main():
    tmp = tempfile.mkdtemp(prefix="mlo_runners_")
    music = os.path.join(tmp, "music")
    album = os.path.join(music, "Smoke Artist", "Smoke Album")
    os.makedirs(album)
    make_flac(os.path.join(album, "1-01 Song A.flac"), "Song A", 1)
    make_flac(os.path.join(album, "1-02 Song B.flac"), "Song B", 2)
    from PIL import Image

    Image.new("RGB", (600, 600), (200, 60, 60)).save(os.path.join(album, "cover.jpg"), "JPEG")

    from mlo.config import DEFAULT_CONFIG

    base = {
        **DEFAULT_CONFIG,
        "music_folder": music,
        "targets": [album],
        "lyrics_format": "EMBEDDED",
        "reencode_images": False,
        "audit_thorough": False,
    }

    from mlo import (run_format_lyrics, run_format_cues, run_optimize_flacs,
                     run_grade_library, run_process_images, run_audit_library,
                     run_auto_tagging, run_format_all)
    from mlo.loudness import run_calc_dr_replaygain
    from mlo.accurip import run_generate_accurip
    from mlo.remux import run_remux_videos
    from mlo.audiometa import run_analyze_audiometa

    runners = [
        (1, "lyrics", run_format_lyrics),
        (2, "cues", run_format_cues),
        (3, "flac", run_optimize_flacs),
        (5, "images", run_process_images),
        (9, "accurip", run_generate_accurip),
        (11, "remux", run_remux_videos),
        (6, "audit", run_audit_library),
        (7, "dr", run_calc_dr_replaygain),
        (12, "audiometa", run_analyze_audiometa),
        (8, "autotag", run_auto_tagging),
        (4, "grade", run_grade_library),
        (10, "formatall", run_format_all),
    ]
    failures = []
    for sid, name, fn in runners:
        cfg = dict(base)
        cfg["stats"] = {"is_grader": name == "grade"}
        try:
            stats = fn(cfg)
            err = sum(1 for e in stats.get("errors", []) if e)
            print(f"script {sid:>2} {name:<10} OK   (errors in-run: {err})")
            for e in list(stats.get("errors", []))[:3]:
                print("      ", e)
        except Exception as e:
            print(f"script {sid:>2} {name:<10} FAIL {type(e).__name__}: {e}")
            failures.append((sid, name, e))

    # format-all force path exercises the new force wiring
    cfg = dict(base)
    cfg["force_lyrics"] = True
    cfg["force_cue"] = True
    cfg["force_accurip"] = True
    cfg["force_auto_tag"] = True
    try:
        run_format_all(cfg)
        print("formatall force OK")
    except Exception as e:
        print(f"formatall force FAIL {e}")
        failures.append((10, "formatall-force", e))

    # beets config generation (script 14 config path, no import run)
    try:
        from server.beetscfg import generate_config
        txt = generate_config(dict(base))
        assert "mloplugin" in txt and "write:" in txt
        print("script 14 beets    OK   (config generated)")
    except Exception as e:
        print(f"script 14 beets    FAIL {e}")
        failures.append((14, "beets-cfg", e))

    shutil.rmtree(tmp, ignore_errors=True)
    if failures:
        print(f"RUNNERS_FAILED: {failures}")
        sys.exit(1)
    print("RUNNERS_OK")


if __name__ == "__main__":
    main()
