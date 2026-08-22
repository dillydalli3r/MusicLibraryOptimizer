"""Main window: sidebar navigation, run controls, status bar."""
import os
import time

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPushButton, QProgressBar, QScrollArea,
    QStackedWidget, QToolButton, QVBoxLayout, QWidget, QFrame, QSizePolicy,
)

from mlo import (
    load_config, save_config,
    run_format_lyrics, run_format_cues, run_optimize_flacs,
    run_grade_library, run_process_images, run_audit_library,
)
try:  # mlo is mid-merge: the package re-exports may not exist yet.
    from mlo import run_calc_dr_replaygain, run_auto_tagging
except ImportError:  # pragma: no cover - transitional fallback
    from mlo.loudness import run_calc_dr_replaygain
    from mlo.autotag import run_auto_tagging
from mlo import __version__
from mlo import tools as tools_mod
from mlo import fetchdeps
from mlo.deps import HAS_MUTAGEN, HAS_PIL

from .console import ConsolePage
from .deps_dialog import DependenciesDialog
from .dialogs import (CustomRunDialog, GradeDetailsDialog, SAVER_BRIDGE,
                      SettingsDialog, TagEditorDialog)
from .external import launch_external
from .library import LibraryPage
from .theme import (THEME, ACCENT_PRESETS, apply_app_theme, blend,
                    set_window_icon)
from .widgets import ToggleSwitch, section_label

RUNNERS = {
    1: ("Format Lyrics", run_format_lyrics),
    2: ("Format CUEs", run_format_cues),
    3: ("Optimize FLACs", run_optimize_flacs),
    4: ("Grade Library", run_grade_library),
    5: ("Process Images", run_process_images),
    6: ("Audit Library", run_audit_library),
    7: ("DR & ReplayGain", run_calc_dr_replaygain),
    8: ("Auto Tagging", run_auto_tagging),
}

# Scripts that are always part of the automatic Run All sequence when the
# user has not configured an order yet. 7 (DR & ReplayGain) and 8 (Auto
# Tagging) stay opt-in: they are selectable everywhere but never appended
# to a run automatically.
BASE_RUN_ALL = [1, 2, 3, 5, 4]


class MainWindow(QMainWindow):
    # Marshals updater results from their worker threads to the GUI
    # thread (auto/queued connection).
    _update_result = Signal(tuple)

    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.running = False
        self._runner_thread = None
        self._current_runner = None
        self._quit_when_done = False
        self._regrade_after = None
        self._pre_save_snapshot = None
        self._update_result.connect(self._on_update_result)

        self.setWindowTitle(f"Music Library Optimizer")
        self.resize(1200, 780)
        self.setMinimumSize(940, 600)
        set_window_icon(self)
        THEME.register_window(self)

        self._build_ui()
        self.apply_theme()

        self.log("Music Library Optimizer ready.", "bold")
        if not HAS_PIL:
            self.log("WARNING: Pillow not found - PNG alpha removal will "
                     "be skipped.", "yellow")
        self.log(f"Library folder: {self.config.get('music_folder', '')}",
                 "muted")
        QTimer.singleShot(60, self.library.refresh)

        # Auto-check for updates on start (configurable). Always performs
        # a real check and reports the outcome to the console.
        if self.config.get("check_updates_on_start", True):
            QTimer.singleShot(4000, self._auto_check_updates)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_sidebar())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)

        body_layout.addWidget(self._build_topbar())

        self.stack = QStackedWidget()
        self.library = LibraryPage(self.config)
        self.console = ConsolePage()
        self.stack.addWidget(self.library)
        self.stack.addWidget(self.console)
        body_layout.addWidget(self.stack, 1)

        body_layout.addWidget(self._build_statusbar())
        root.addWidget(body, 1)

        # wiring ---------------------------------------------------------
        self.library.run_requested.connect(self._optimize_selected)
        self.library.status_message.connect(self.status.setText)
        self.library.log_line.connect(self.log)
        self.library.launch_external.connect(self._on_launch_external)
        self.library.edit_tags.connect(self._open_tag_editor)
        self.library.grade_details.connect(self._show_grade_details)
        SAVER_BRIDGE.status.connect(self.status.setText)
        SAVER_BRIDGE.saved.connect(self._tags_saved)

    def _build_sidebar(self):
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(228)
        lay = QVBoxLayout(side)
        lay.setContentsMargins(14, 16, 14, 14)
        lay.setSpacing(4)

        # brand
        brand_row = QHBoxLayout()
        ico_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "assets", "icon_64.png")
        if os.path.isfile(ico_path):
            brand_icon = QLabel()
            brand_icon.setPixmap(QPixmap(ico_path).scaled(
                30, 30, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            brand_row.addWidget(brand_icon)
        name_col = QVBoxLayout()
        name_col.setSpacing(0)
        name = QLabel("Music Library\nOptimizer")
        name.setStyleSheet(f"font-weight: 700; font-size: 10pt;"
                           f" color: {THEME.c('bright')};")
        name_col.addWidget(name)
        ver = QLabel(f"v{__version__}")
        ver.setProperty("role", "version")
        name_col.addWidget(ver)
        brand_row.addSpacing(4)
        brand_row.addLayout(name_col)
        brand_row.addStretch(1)
        lay.addLayout(brand_row)
        lay.addSpacing(14)

        lay.addWidget(section_label("View"))
        self.nav_buttons = {}
        for key, label, page in (("library", "Library", 0),
                                 ("console", "Console", 1)):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("role", "nav")
            btn.setChecked(key == "library")
            btn.clicked.connect(
                lambda _c=False, p=page, k=key: self._switch_page(p, k))
            lay.addWidget(btn)
            self.nav_buttons[key] = btn
        self.stack_page = 0

        lay.addSpacing(16)
        lay.addWidget(section_label("Run Scripts"))
        self.run_buttons = []
        self.script_buttons = []
        for sid, (name, _runner) in RUNNERS.items():
            btn = QPushButton(name)
            btn.setProperty("role", "side")
            btn.setProperty("scriptId", sid)
            btn.clicked.connect(
                lambda _c=False, s=sid: self._run_scripts(
                    [s], f"RUN — {RUNNERS[s][0]}"))
            lay.addWidget(btn)
            self.run_buttons.append(btn)
            self.script_buttons.append(btn)

        lay.addSpacing(16)
        lay.addWidget(section_label("Batch"))
        run_all = QPushButton("Run All")
        run_all.setProperty("role", "side")
        run_all.setToolTip("Run every script in order.\n"
                           "Enable Force in the Library tab to force "
                           "re-encoding.")
        run_all.clicked.connect(self._run_all)
        lay.addWidget(run_all)
        self.run_buttons.append(run_all)

        run_custom = QPushButton("Run Custom…")
        run_custom.setProperty("role", "side")
        run_custom.clicked.connect(self._run_custom)
        lay.addWidget(run_custom)
        self.run_buttons.append(run_custom)

        lay.addSpacing(16)
        lay.addWidget(section_label("Manage"))
        updates_btn = QPushButton("Check for Updates…")
        updates_btn.setProperty("role", "side")
        updates_btn.clicked.connect(self._check_updates)
        lay.addWidget(updates_btn)
        self.run_buttons.append(updates_btn)

        deps_btn = QPushButton("Dependencies…")
        deps_btn.setProperty("role", "side")
        deps_btn.clicked.connect(self._open_deps)
        lay.addWidget(deps_btn)
        self.run_buttons.append(deps_btn)

        settings_btn = QPushButton("Settings…")
        settings_btn.setProperty("role", "side")
        settings_btn.clicked.connect(self._open_config)
        lay.addWidget(settings_btn)
        self.run_buttons.append(settings_btn)

        lay.addStretch(1)

        self.dep_label = QLabel("")
        self.dep_label.setProperty("role", "version")
        lay.addWidget(self.dep_label)
        self._update_dep_label()
        return side

    def _build_topbar(self):
        bar = QFrame()
        bar.setObjectName("TopBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(20, 10, 16, 10)
        h.setSpacing(10)

        h.addWidget(section_label("Library Folder"))
        self.folder_edit = QLineEdit(self.config.get("music_folder", ""))
        self.folder_edit.setProperty("role", "path")
        self.folder_edit.editingFinished.connect(self._folder_edited)
        h.addWidget(self.folder_edit, 1)

        browse = QPushButton("Browse…")
        browse.clicked.connect(self._pick_folder)
        h.addWidget(browse)

        h.addSpacing(14)

        theme_btn = QToolButton()
        theme_btn.setText("Theme")
        theme_btn.setPopupMode(QToolButton.ToolButtonPopupMode.
                               InstantPopup)
        menu = QMenu(theme_btn)

        self._theme_group = []
        for label, mode in (("Dark", "dark"), ("Light", "light"),
                            ("Follow system", "system")):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self.config.get("theme", "dark") == mode)
            act.triggered.connect(
                lambda _c=False, m=mode: self._set_theme_mode(m))
            self._theme_group.append(act)
        menu.addSeparator()

        accent_menu = menu.addMenu("Accent color")
        current = (self.config.get("accent_color") or "").lower()
        for name, hexval in ACCENT_PRESETS:
            act = accent_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(current == hexval.lower())
            act.triggered.connect(lambda _c=False, h_=hexval:
                                  self._set_accent(h_))
            self._theme_group.append(act)
        custom = accent_menu.addAction("Custom…")
        custom.triggered.connect(self._pick_custom_accent)
        default = accent_menu.addAction("Theme default")
        default.triggered.connect(lambda: self._set_accent(""))

        theme_btn.setMenu(menu)
        h.addWidget(theme_btn)
        return bar

    def _build_statusbar(self):
        bar = QFrame()
        bar.setObjectName("StatusBar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 8, 16, 8)
        h.setSpacing(12)

        self.status = QLabel("Ready")
        h.addWidget(self.status, 1)

        self.continue_btn = QPushButton("Continue ▶")
        self.continue_btn.setProperty("variant", "accent")
        self.continue_btn.clicked.connect(self._continue)
        self.continue_btn.hide()
        h.addWidget(self.continue_btn)

        self.prog_label = QLabel("")
        self.prog_label.setProperty("role", "muted")
        h.addWidget(self.prog_label)

        self.progress = QProgressBar()
        self.progress.setFixedWidth(240)
        self.progress.setTextVisible(False)
        h.addWidget(self.progress)
        return bar

    # ------------------------------------------------------------------
    # Theming
    # ------------------------------------------------------------------
    def apply_theme(self):
        apply_app_theme(self.config)

    def _switch_page(self, page, key):
        self.stack.setCurrentIndex(page)
        for k, btn in self.nav_buttons.items():
            btn.setChecked(k == key)

    def _set_theme_mode(self, mode):
        self.config["theme"] = mode
        save_config(self.config)
        apply_app_theme(self.config)

    def _set_accent(self, hexval):
        self.config["accent_color"] = hexval
        save_config(self.config)
        apply_app_theme(self.config)

    def _pick_custom_accent(self):
        from PySide6.QtWidgets import QColorDialog
        color = QColorDialog.getColor(self, "Custom accent color")
        if color.isValid():
            self._set_accent(color.name())

    # ------------------------------------------------------------------
    # Console / logging
    # ------------------------------------------------------------------
    def log(self, text, tag=None):
        self.console.append_line(text, tag)

    # ------------------------------------------------------------------
    # Folder handling
    # ------------------------------------------------------------------
    def _pick_folder(self):
        path = QFileDialog.getExistingDirectory(
            self, "Choose Library Folder",
            self.folder_edit.text() or "/")
        if path:
            self.folder_edit.setText(path)
            self._folder_edited()

    def _folder_edited(self):
        path = self.folder_edit.text().strip()
        if path == self.config.get("music_folder", ""):
            return
        self.config["music_folder"] = path
        save_config(self.config)
        self.log(f"Library folder set to: {path}")
        self.library.refresh(regrade=True)

    # ------------------------------------------------------------------
    # Settings / deps dialogs
    # ------------------------------------------------------------------
    def _open_config(self):
        if self.running:
            QMessageBox.information(self, "Busy",
                                    "Wait for the current operation to "
                                    "finish.")
            return
        self._pre_save_snapshot = (
            self.config.get("music_folder", ""),
            str(self.config.get("lyrics_format", "EMBEDDED")).upper(),
        )
        dlg = SettingsDialog(self, self.config, self._config_saved)
        dlg.exec()

    def _config_saved(self, cfg):
        self.config = cfg
        self.folder_edit.setText(cfg.get("music_folder", ""))
        self.log("Settings saved.", "green")
        old_folder, old_fmt = self._pre_save_snapshot or (None, None)
        folder_changed = cfg.get("music_folder", "") != old_folder
        fmt_changed = str(
            cfg.get("lyrics_format", "EMBEDDED")).upper() != old_fmt
        self.library.refresh(regrade=folder_changed or fmt_changed)

    def _open_deps(self):
        if self.running:
            QMessageBox.information(self, "Busy",
                                    "Wait for the current operation to "
                                    "finish.")
            return
        dlg = DependenciesDialog(self, self.log,
                                 on_installed=self._update_dep_label)
        dlg.exec()

    def _update_dep_label(self):
        n = len(tools_mod.detect_all_tools())
        total = len(fetchdeps.DISPLAY_NAMES)
        self.dep_label.setText(
            f"{n}/{total} tools detected" if n else "No tools detected")

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------
    def _import_updater(self):
        """mlo.updater is stdlib-only (no tkinter); import lazily anyway
        so a missing/broken module can never take the GUI down."""
        from mlo import updater
        return updater

    def _check_updates(self):
        self.status.setText("Checking for updates…")
        self.log("Checking for updates…", "muted")
        try:
            updater = self._import_updater()
        except ImportError as e:
            self.log(f"Update check unavailable: {e}", "yellow")
            return
        # updater spawns its own worker thread; results come back through
        # the queued _update_result signal.
        updater.check_for_updates(
            silent=False,
            callback=lambda *res: self._update_result.emit(tuple(res)))

    def _auto_check_updates(self):
        # Skip in headless/offscreen runs (tests): the check writes
        # last_update_check back to config.json, which could race the
        # test's own config restore.
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return
        try:
            updater = self._import_updater()
        except ImportError:
            return
        updater.maybe_auto_check(
            force=True,
            callback=lambda *res: self._update_result.emit(tuple(res)))

    def _on_update_result(self, result):
        if len(result) != 5:
            return
        has_update, version, url, _notes, error = result
        if error:
            self.log(f"Update check failed: {error}", "red")
        elif has_update:
            self.log(f"Update available: v{version} "
                     f"(current: v{__version__})", "yellow")
            self.log("Get it from github.com/dillydalli3r/"
                     "MusicLibraryOptimizer/releases", "muted")
        else:
            self.log(f"Update check: already on latest version "
                     f"(v{__version__})", "green")
        self.status.setText("Ready")

    # ------------------------------------------------------------------
    # Library interactions
    # ------------------------------------------------------------------
    def _on_launch_external(self, key, dirs):
        launch_external(key, dirs, self.config, self.log, parent=self)

    def _show_grade_details(self, album_dir, res, track_file):
        dlg = GradeDetailsDialog(
            self, album_dir, res,
            str(self.config.get("lyrics_format", "EMBEDDED")).upper(),
            track_file=track_file)
        dlg.exec()

    def _open_tag_editor(self, album_dir, track_path):
        dlg = TagEditorDialog(self, album_dir, track_path)
        dlg.exec()

    def _tags_saved(self, album_dir, modified, errors):
        if errors:
            self.log("Tag edit errors: " + "; ".join(errors), "red")
        if modified:
            self.log(f"Edited tags in {modified} file(s): "
                     f"{os.path.basename(album_dir)}", "green")
            self.library.regrade_albums([album_dir])
        else:
            self.status.setText("No tag changes saved.")

    def _optimize_selected(self, targets):
        if not targets:
            return
        order = list(self.config.get("run_all_order", BASE_RUN_ALL))
        if 6 not in order:
            order.append(6)
        self._run_scripts(
            order, f"OPTIMIZE SELECTED ({len(targets)} items)",
            targets=targets)

    # ------------------------------------------------------------------
    # Script runs
    # ------------------------------------------------------------------
    def _run_all(self):
        # Uses the user's configured Run All order verbatim; scripts 7/8
        # are never appended here (they run only when explicitly picked).
        self._run_scripts(
            list(self.config.get("run_all_order", BASE_RUN_ALL)),
            "RUN ALL SCRIPTS")

    def _run_custom(self):
        if self.running:
            return
        dlg = CustomRunDialog(self)
        if dlg.exec() and dlg.result_order:
            self._run_scripts(dlg.result_order, "CUSTOM RUN ORDER")

    def _run_scripts(self, script_ids, title, targets=None):
        if self.running:
            QMessageBox.information(self, "Busy",
                                    "An operation is already running.")
            return

        folder = self.folder_edit.text().strip()
        if folder:
            self.config["music_folder"] = folder

        self._set_running(True, title)
        self._switch_page(1, "console")

        if targets:
            self._regrade_after = list(targets)
        else:
            self._regrade_after = "all"

        force_flac, force_images, force_audit = self.library.force_settings()

        from .workers import ScriptRunner
        runner = ScriptRunner(RUNNERS, self.config, script_ids, title,
                              targets, force_flac, force_images,
                              force_audit)
        runner.sig_output.connect(self._on_run_output, Qt.ConnectionType.
                                  QueuedConnection)
        runner.sig_progress.connect(self._on_run_progress)
        runner.sig_pause.connect(self._on_run_pause)
        runner.sig_done.connect(self._on_run_done)
        self._current_runner = runner

        self._runner_thread = QThread()
        runner.moveToThread(self._runner_thread)
        self._runner_thread.started.connect(runner.run)
        self._runner_thread.start()

    def _on_run_output(self, event):
        kind, payload = event
        if kind == "out":
            self.console.append_segments(payload)
        elif kind == "nl":
            self.console.append_segments([], newline=True)
            if self.console.auto_switch.isChecked():
                self.console.console.scrollToBottom()

    def _on_run_progress(self, done, total, desc):
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(min(done, total))
            self.prog_label.setText(f"{desc}  {done}/{total}")
        else:
            self.progress.setValue(0)
            self.prog_label.setText("")

    def _on_run_pause(self, name):
        self.continue_btn.show()
        self.status.setText(f"Paused — Continue to run {name}")

    def _continue(self):
        self.continue_btn.hide()
        self.status.setText("Running…")
        if self._current_runner is not None:
            self._current_runner.proceed()

    def _on_run_done(self, elapsed):
        self._set_running(False)
        self.status.setText(f"Ready — completed in {elapsed:.1f}s")
        self.progress.setValue(0)
        self.prog_label.setText("")

        if self._runner_thread is not None:
            self._runner_thread.quit()
            if not self._runner_thread.wait(2000):
                # Still finishing (paused edge): keep the reference so
                # the QThread is never destroyed while running.
                self._zombie_thread = self._runner_thread
            self._runner_thread = None
        self._current_runner = None

        if self._quit_when_done:
            QApplication.quit()
            return

        # Runs may have changed tags (audit verdicts, lyrics,
        # MEDIA/SOURCE): refresh the library so grades, the AUDIT column
        # and row colors stay current.
        pending = self._regrade_after
        self._regrade_after = None
        if pending == "all":
            self.library.refresh(regrade=True)
        elif pending:
            albums = set()
            full = False
            for t in pending:
                if not t:
                    continue
                d = os.path.dirname(t) if os.path.isfile(t) else t
                if d in self.library._grade_cache:
                    albums.add(d)
                elif d in (self.library._artists or {}):
                    albums.update(self.library._artists[d])
                else:
                    full = True
            if full or not albums:
                self.library.refresh(regrade=True)
            else:
                self.library.regrade_albums(sorted(albums))

    def _set_running(self, flag, label=""):
        self.running = flag
        for b in self.run_buttons:
            b.setEnabled(not flag)
        self.library.set_running(flag)
        self.status.setText(f"Running: {label}" if flag else "Ready")
        if flag:
            self.progress.setRange(0, 100)
            self.progress.setValue(0)
            self.prog_label.setText("")

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        if self.running:
            ret = QMessageBox.question(
                self, "Operation in progress",
                "An operation is still running. The app will stay in the "
                "background and exit automatically once it finishes.\n\n"
                "Close anyway?")
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            # Never destroy a running QThread (hard process abort):
            # stop the sequence, hide now, and quit from _on_run_done
            # once the current script finishes.
            if self._current_runner is not None:
                self._current_runner.abort()
            self._quit_when_done = True
            self.hide()
            event.ignore()
            return

        # Give background scanners a chance to stop cleanly.
        self.library.shutdown()
        event.accept()
