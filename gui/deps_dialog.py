"""Dependencies dialog: download / update the external toolchain."""
import threading

from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtWidgets import (
    QDialog, QGridLayout, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
    QPushButton, QVBoxLayout, QFrame,
)

from mlo import fetchdeps
from mlo.paths import DEPS_DIR
from mlo import tools as tools_mod
from .theme import THEME
from .widgets import section_label


class _Bridge(QObject):
    """Queued bridge from install worker threads to the dialog."""
    latest = Signal(dict)
    neterr = Signal(str)
    status = Signal(str, str)
    installed = Signal(str, str)
    fail = Signal(str, str)
    busy = Signal(bool)
    progress = Signal(int, int, str)
    logline = Signal(str, str)


BRIDGE = _Bridge()


class InstallWorker(QObject):
    """Runs dependency installs off the UI thread."""

    def run(self):
        BRIDGE.busy.emit(True)
        for key in self.keys:
            name = fetchdeps.DISPLAY_NAMES[key]
            BRIDGE.status.emit(key, "Downloading…")
            try:
                def prog(done, total, _name=name):
                    BRIDGE.progress.emit(done, total, f"Downloading {_name}")
                version = fetchdeps.install_dependency(
                    key,
                    log=lambda m: BRIDGE.logline.emit(m, "muted"),
                    progress=prog,
                )
                BRIDGE.installed.emit(key, version)
            except Exception as e:
                BRIDGE.logline.emit(
                    f"Dependency install failed ({name}): {e}", "red")
                BRIDGE.fail.emit(key, str(e))
        fetchdeps.refresh_tool_cache()
        BRIDGE.busy.emit(False)


class DependenciesDialog(QDialog):
    KEYS = ("flac", "libjxl", "libjpeg_turbo", "oxipng", "audioauditor")

    def __init__(self, parent, app_log, on_installed=None):
        super().__init__(parent)
        self.app_log = app_log
        self.on_installed = on_installed
        self.busy = False
        self.latest = {}
        self._worker = None

        self.setWindowTitle("Dependencies")
        self.setModal(True)
        self.setMinimumSize(760, 480)
        THEME.register_window(self)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(10)

        lay.addWidget(section_label("Toolchain"))
        desc = QLabel(
            "Downloads the latest official Windows builds from GitHub "
            "releases into the .dependencies folder next to the app. "
            "AudioAuditor provides the Audit Library script.")
        desc.setProperty("role", "muted")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        grid_host = QFrame()
        grid_host.setObjectName("Card")
        grid = QGridLayout(grid_host)
        grid.setContentsMargins(14, 10, 14, 12)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)

        for col, text in enumerate(("Tool", "Installed", "Latest",
                                    "", "Status")):
            lbl = QLabel(text.upper())
            lbl.setProperty("role", "section")
            grid.addWidget(lbl, 0, col)

        self.rows = {}
        installed = fetchdeps.installed_versions()
        for i, key in enumerate(self.KEYS, start=1):
            inst = installed.get(key, "")
            self.rows[key] = {
                "installed_lbl": QLabel(inst or "—"),
                "latest_lbl": QLabel("…"),
                "status_lbl": QLabel(""),
                "button": QPushButton("…"),
                "installed_version": inst,
            }
            row = self.rows[key]
            if inst:
                row["installed_lbl"].setStyleSheet(
                    f"color: {THEME.c('success')};")
            else:
                row["installed_lbl"].setStyleSheet(
                    f"color: {THEME.c('muted')};")
            row["button"].setProperty("variant", "small")
            row["button"].clicked.connect(
                lambda _c=False, k=key: self._install([k]))
            grid.addWidget(QLabel(fetchdeps.DISPLAY_NAMES[key]), i, 0)
            grid.addWidget(row["installed_lbl"], i, 1)
            grid.addWidget(row["latest_lbl"], i, 2)
            grid.addWidget(row["button"], i, 3)
            grid.addWidget(row["status_lbl"], i, 4)
        lay.addWidget(grid_host)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(7)
        lay.addWidget(self.progress)
        lay.addStretch(1)

        btns = QHBoxLayout()
        btns.addStretch(1)
        folder = QPushButton("Open Folder")
        folder.clicked.connect(self._open_folder)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._check_latest)
        install_all = QPushButton("Install / Update All")
        install_all.setProperty("variant", "accent")
        install_all.clicked.connect(
            lambda: self._install(list(self.KEYS)))
        btns.addWidget(folder)
        btns.addWidget(refresh)
        btns.addWidget(install_all)
        lay.addLayout(btns)

        BRIDGE.latest.connect(self._on_latest)
        BRIDGE.neterr.connect(self._on_neterr)
        BRIDGE.status.connect(self._on_status)
        BRIDGE.installed.connect(self._on_installed)
        BRIDGE.fail.connect(self._on_fail)
        BRIDGE.busy.connect(self._on_busy)
        BRIDGE.progress.connect(self._on_progress)
        BRIDGE.logline.connect(
            lambda text, tag: self.app_log(text, tag))

        self._check_latest()

    # ------------------------------------------------------------------
    def closeEvent(self, event):
        if self.busy:
            ret = QMessageBox.question(
                self, "Download in progress",
                "A download is still running. Close anyway? The remaining "
                "tools will not be installed.")
            if ret != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()

    def _open_folder(self):
        import os
        if not os.path.isdir(DEPS_DIR):
            QMessageBox.information(
                self, "Not created yet",
                "The .dependencies folder does not exist yet.")
            return
        try:
            os.startfile(DEPS_DIR)  # Windows convenience
        except (AttributeError, OSError):
            pass

    def _set_busy(self, flag):
        self.busy = flag
        for row in self.rows.values():
            row["button"].setEnabled(not flag)

    def _on_busy(self, flag):
        self._set_busy(flag)

    def _check_latest(self):
        def work():
            try:
                BRIDGE.latest.emit(fetchdeps.latest_versions())
            except Exception as e:
                BRIDGE.neterr.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _install(self, keys):
        if self.busy:
            return
        self._set_busy(True)   # synchronous: no double-click race
        self._worker = InstallWorker(keys)
        threading.Thread(target=self._worker.run, daemon=True).start()

    def _row_button_text(self, key):
        row = self.rows[key]
        inst = row["installed_version"]
        latest = self.latest.get(key)
        if not inst:
            return "Download"
        if latest and tools_mod._version_is_older(inst, latest):
            return "Update"
        return "Reinstall"

    # slots -------------------------------------------------------------
    def _on_latest(self, latest):
        self.latest = latest
        for key in self.KEYS:
            row = self.rows[key]
            row["latest_lbl"].setText(self.latest.get(key, "?"))
            row["button"].setText(self._row_button_text(key))

    def _on_neterr(self, message):
        for key in self.KEYS:
            self.rows[key]["latest_lbl"].setText("unavailable")
            self.rows[key]["status_lbl"].setText("")
        self.app_log(
            f"Could not query GitHub for latest versions: {message}",
            "yellow")

    def _on_status(self, key, text):
        self.rows[key]["status_lbl"].setText(text)

    def _on_installed(self, key, version):
        row = self.rows[key]
        row["installed_version"] = version
        row["installed_lbl"].setText(version)
        row["installed_lbl"].setStyleSheet(
            f"color: {THEME.c('success')};")
        row["status_lbl"].setText("Installed")
        row["button"].setText(self._row_button_text(key))
        if self.on_installed:
            self.on_installed()

    def _on_fail(self, key, err):
        self.rows[key]["status_lbl"].setText(f"Failed: {err[:60]}")

    def _on_progress(self, done, total, desc):
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(min(done, total))
        else:
            self.progress.setRange(0, 1)
            self.progress.setValue(0)
