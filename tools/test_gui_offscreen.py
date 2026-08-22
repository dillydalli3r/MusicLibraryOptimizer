#!/usr/bin/env python3
"""Offscreen functional test of the GUI library page (no display needed)."""
import os
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QApplication

app = QApplication([])
app.setStyle("Fusion")

from gui.theme import apply_app_theme
from mlo import load_config, save_config

out = subprocess.run(
    [sys.executable, os.path.join(os.path.dirname(__file__),
                                  "make_test_library.py")],
    capture_output=True, text=True).stdout.strip().splitlines()[-1]
lib = out
cfg = load_config()
_original_folder = cfg.get("music_folder", "")
cfg["music_folder"] = lib
cfg["library_show_all_files"] = False
save_config(cfg)
apply_app_theme(cfg)

import atexit
atexit.register(lambda: (cfg.__setitem__("music_folder", _original_folder),
                         cfg.__setitem__("library_show_all_files", False),
                         save_config(cfg)))

from gui.main_window import MainWindow

w = MainWindow()
w.show()

loop = QEventLoop()


def wait_busy():
    if not w.library.busy:
        loop.quit()
    else:
        QTimer.singleShot(100, wait_busy)


QTimer.singleShot(300, wait_busy)
loop.exec()

ok = True


def check(label, cond):
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    ok = ok and bool(cond)


tree = w.library.tree
root = tree.topLevelItem(0)
check("root label", root.text(0).startswith("All Folders (TestLib)"))
check("3 artists", root.childCount() == 3)

a0 = root.child(0)
check("artist name", a0.text(0) == "Artist Alpha")
check("artist grade agg", a0.text(1) == "0/1")

alb = a0.child(0)
check("album name", alb.text(0) == "2020 - First Album")
check("album grade", alb.text(1) == "FAIL")
check("album checks", alb.text(3).endswith("/39"))
check("3 tracks (audio view)", alb.childCount() == 3)

tr0 = alb.child(0)
check("track name", tr0.text(0) == "01 - Intro.flac")

# all-files view adds non-audio children
w.library.file_view.setCurrentIndex(1)
alb2 = tree.topLevelItem(0).child(0).child(0)
names = [alb2.child(i).text(0) for i in range(alb2.childCount())]
check("all-files adds extras", len(names) == 7 and "cover.jpg" in names)
w.library.file_view.setCurrentIndex(0)
alb3 = tree.topLevelItem(0).child(0).child(0)
check("back to audio view", alb3.childCount() == 3)

# selection cascade
a0b = tree.topLevelItem(0).child(0)
a0b.setCheckState(0, Qt.CheckState.Checked)
check("artist check selects 1 album dir",
      w.library.selected_dirs() ==
      [os.path.join(lib, "Artist Alpha", "2020 - First Album")])
w.library.unselect_all()
check("unselect all clears", w.library.selected_paths() == [])

alb3.setCheckState(0, Qt.CheckState.Checked)
check("album check -> 3 track targets", len(w.library.selected_paths()) == 3)
w.library.unselect_all()

# bad-only filter hides nothing here (all failing) but shouldn't crash
w.library.bad_only.setChecked(True)
check("bad-only keeps failing albums", tree.topLevelItem(0).childCount() > 0)
w.library.bad_only.setChecked(False)

# filter text
w.library.filter_edit.setText("Gamma")
check("filter narrows to 1 artist", tree.topLevelItemCount() == 1
      or tree.topLevelItem(0).childCount() == 1)
w.library.filter_edit.clear()

# sorting shouldn't crash
w.library.sort_combo.setCurrentIndex(1)
w.library.sort_combo.setCurrentIndex(0)

# run Grade Library through the worker thread (console path)
w._run_scripts([4], "TEST RUN — Grade Library")
loop2 = QEventLoop()


def wait_run():
    if not w.running:
        loop2.quit()
    else:
        QTimer.singleShot(100, wait_run)


QTimer.singleShot(200, wait_run)
loop2.exec()
console_text = w.console.console.toPlainText()
check("console captured grader output", "Grade Library" in console_text
      or "LIBRARY GRADER" in console_text.upper())
check("run finished status", "completed" in console_text
      or "Scanning" in w.status.text())

w.grab().save(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "shot_library.png"))

print("FUNCTIONAL " + ("OK" if ok else "FAILED"))
sys.exit(0 if ok else 1)
