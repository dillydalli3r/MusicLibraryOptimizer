# v1.6.1 — CD Must Be 16-bit 44.1 kHz

Tag: v1.6.1  Commit: a5161c8

## CD-DA enforcement

CD is only 16-bit 44.1 kHz. Anything else is a fake rip (hi-res upsampled, 24-bit, 48/96/192 kHz).

- Config: grade_check_cd_format (Grading -> CD, True default) + audit_check_cd_format (Auditing -> Core, True default) — both on by default, in Settings, in v1.6.0 Strict preset, and in Grade Details checklist.
- Grading: mlo/grader.py per MEDIA=CD track checks audio.info.bits_per_sample + sample_rate via mutagen; not 16/44.1 -> CD must be 16-bit 44.1 kHz (found ...) CD_FORMAT (total+fail per track, shown in FAILED and Grade Details)
- Auditing: mlo/audit.py independent check via mutagen (no ffmpeg), marks not 16-bit 44.1 kHz as AUDIT=FAKE (deduped via file_status_map, respects audit_check_cd_format), appears in Grade Details Auditing -> CD Verification

Helps detect fake rips from hi-res sources. Disable the toggle to allow non-16/44.1 for MEDIA=CD.

Also in v1.6.0: Strict defaults (100/100, 0px, 100q, no zero, all PROGRAM on, run order 6->4->7), 29 grade_check_* toggles, track right-click fix, Grade Details full checklist grouped with checkmarks, config menus 01-16, Guide v1.6.0 Strict preset.

Install:
- MusicLibraryOptimizer_Setup_v1.6.1_x64.exe
- MusicLibraryOptimizer_v1.6.1_portable_x64.exe
- mlo.exe
