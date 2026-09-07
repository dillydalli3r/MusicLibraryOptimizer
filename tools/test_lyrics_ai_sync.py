import sys

sys.path.insert(0, ".")
from server.ai import lyrics_detect_sync, wordsync_lrc

CFG = {}  # AI unconfigured -> deterministic paths only

CAND_SYNC = {
    "artistName": "Artist",
    "trackName": "Song",
    "duration": 200,
    "syncedLyrics": "[00:10.00]First line of the song\n[00:14.50]Second line follows here\n[00:20.00]Third and final line",
    "plainLyrics": "First line of the song\nSecond line follows here\nThird and final line",
}
CAND_PLAIN = {"artistName": "Artist", "trackName": "Song", "duration": 200, "plainLyrics": "a\nb"}

# 1. no existing lyrics -> candidate synced, word-synced output
lrc, src = lyrics_detect_sync(CFG, track="Song", candidates=[CAND_SYNC])
print("1:", src, "|", lrc.replace("\n", " // ")[:120])
assert src == "candidate" and "[00:10.00]" in lrc and "<00:10.00>" in lrc

# 2. existing unsynced wording -> aligned to candidate timestamps
existing = "First line of the song!\nsecond line follows HERE\nThird and final line"
lrc, src = lyrics_detect_sync(CFG, track="Song", existing_text=existing, candidates=[CAND_SYNC])
print("2:", src, "|", lrc.replace("\n", " // ")[:160])
assert src == "aligned" and "song!" in lrc and "[00:14.50]" in lrc and "HERE" in lrc

# 3. already synced input -> wordsync upgrade only
timed = "[00:01.00]Alpha beta\n[00:05.00]Gamma delta"
lrc, src = lyrics_detect_sync(CFG, track="Song", existing_text=timed, candidates=[CAND_SYNC])
print("3:", src, "|", lrc.replace("\n", " // "))
assert src == "wordsync" and "<00:01.00>Alpha" in lrc

# 4. existing wording, only plain candidate -> unchanged
lrc, src = lyrics_detect_sync(CFG, track="Song", existing_text=existing, candidates=[CAND_PLAIN])
print("4:", src)
assert src == "unchanged" and lrc == existing

# 5. nothing anywhere -> empty
lrc, src = lyrics_detect_sync(CFG, track="Song", candidates=[])
print("5:", src, repr(lrc))
assert src == "unchanged" and lrc == ""

# 6. fuzzy: reworded lines still align
rewritten = "The first line of the song\nA second line that follows right here\nFinal line, third and last"
lrc, src = lyrics_detect_sync(CFG, track="Song", existing_text=rewritten, candidates=[CAND_SYNC])
print("6:", src, "|", lrc.replace("\n", " // ")[:160])
assert src == "aligned"

print("\nAI sync deterministic pipeline OK")
