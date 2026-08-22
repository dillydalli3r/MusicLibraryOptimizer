"""Library page: background scan + grade, interactive album tree."""
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
    QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from mlo import save_config
from mlo.grader import summarize_audits
from mlo.stats import _find_albums, is_audio_file
from .theme import THEME
from .widgets import ToggleSwitch

# Library tree columns: id -> (heading, width, visible-by-default).
# The TAGS heading doubles as the key for its compact layout:
# G=Genre A=Advisory I=Instrumental L=Lyrics AA=Album Advisory.
TREE_COLUMNS = {
    "grade": ("GRADE", 78, True),
    "audit": ("AUDIT", 82, True),
    "checks": ("CHECKS", 92, False),
    "tracks": ("TRACKS", 60, True),
    "media": ("MEDIA", 104, True),
    "cover": ("COVER", 112, True),
    "tags": ("TAGS · G A I L AA", 320, True),
}

ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_STATE = Qt.ItemDataRole.UserRole + 1
ROLE_OTHER = Qt.ItemDataRole.UserRole + 2   # non-audio file rows

AUDIT_BAD = ("FAKE",)
AUDIT_WARN = ("MIX", "WARN", "UNKNOWN")


def row_state(grade_ok, audit):
    """Pick the row color state from (grade passed?, audit verdict)."""
    audit = str(audit).upper() if audit else None
    if audit in AUDIT_BAD:
        return "fail"
    if audit == "REAL":
        return "both" if grade_ok else "audited"
    if audit in AUDIT_WARN:
        return "mixed" if grade_ok else "fail"
    if grade_ok is None:
        return "mixed"
    return "pass" if grade_ok else "fail"


# --------------------------------------------------------------------------
# Scanner threads
# --------------------------------------------------------------------------
class LibraryScanner(QThread):
    """Walks the library folder and grades every album concurrently.

    Signals carry a generation counter; the page ignores stale results
    from scans superseded by a newer Refresh.
    """

    sig_data = Signal(int, dict, list, dict)
    sig_grade = Signal(int, str, object)
    sig_done = Signal(int)
    sig_failed = Signal(int, str)

    def __init__(self, folder, lyrics_format, generation, skip_paths=(),
                 parent=None):
        super().__init__(parent)
        self.folder = folder
        self.lyrics_format = lyrics_format
        self.generation = generation
        self.skip_paths = set(skip_paths)
        self.stop_flag = False

    def stop(self):
        self.stop_flag = True

    def run(self):
        gen = self.generation
        try:
            from mlo.grader import _grade_album

            albums = _find_albums(self.folder)
            artists = {}
            root_albums = []
            other_files = {}

            album_set = set(albums)
            for album_dir in albums:
                parent = os.path.dirname(album_dir)
                # A folder holding both loose tracks and sub-albums is
                # itself an album - its children are shown at the root
                # instead of grouping under a duplicate row.
                if parent == self.folder or parent in album_set:
                    root_albums.append(album_dir)
                else:
                    artists.setdefault(parent, []).append(album_dir)
                try:
                    others = sorted(
                        f for f in os.listdir(album_dir)
                        if not is_audio_file(f) and not f.startswith(".")
                    )
                    if others:
                        other_files[album_dir] = others
                except OSError:
                    pass

            self.sig_data.emit(gen, artists, root_albums, other_files)

            todo = [a for albs in artists.values() for a in albs]
            todo.extend(root_albums)
            todo = [a for a in todo if a not in self.skip_paths]

            def grade_one(album_dir):
                try:
                    return album_dir, _grade_album(album_dir,
                                                   self.lyrics_format)
                except Exception:
                    return album_dir, None

            workers = max(2, min(8, (os.cpu_count() or 2)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(grade_one, a) for a in todo]
                for fut in as_completed(futures):
                    if self.stop_flag:
                        for f in futures:
                            f.cancel()
                        break
                    album_dir, result = fut.result()
                    if result is None:
                        result = {"error": True, "path": album_dir}
                    self.sig_grade.emit(gen, album_dir, result)
        except Exception as e:
            self.sig_failed.emit(gen, f"{type(e).__name__}: {e}")
        self.sig_done.emit(gen)


class RegradeWorker(QThread):
    """Re-grades a handful of albums (e.g. after tag edits)."""

    sig_grade = Signal(str, object)
    sig_done = Signal()

    def __init__(self, albums, lyrics_format, parent=None):
        super().__init__(parent)
        self.albums = list(albums)
        self.lyrics_format = lyrics_format

    def run(self):
        from mlo.grader import _grade_album
        for album_dir in self.albums:
            try:
                result = _grade_album(album_dir, self.lyrics_format)
            except Exception:
                result = None
            if result is None:
                result = {"error": True, "path": album_dir}
            self.sig_grade.emit(album_dir, result)
        self.sig_done.emit()


# --------------------------------------------------------------------------
# Library page
# --------------------------------------------------------------------------
class LibraryPage(QWidget):
    run_requested = Signal(list)          # targets for Optimize Selected
    status_message = Signal(str)
    log_line = Signal(str, str)           # text, tag
    launch_external = Signal(str, list)   # tool key, dirs
    edit_tags = Signal(str, object)       # album_dir, track_path|None
    grade_details = Signal(str, object, object)  # album_dir, res, track_file

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self._artists = {}
        self._root_albums = []
        self._other_files = {}
        self._folder_artist = {}
        self._grade_cache = {}
        self._checked = {}          # path -> Qt.CheckState (int) for rebuilds
        self._agg = {}
        self._agg_total = {}
        self._root_item = None
        self._scanner = None
        self._regrade_worker = None
        self._scan_gen = 0
        self._library_busy = False
        self._updating = False

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(220)
        self._filter_timer.timeout.connect(self._rebuild_tree)

        self._build_ui()
        THEME.changed.connect(self._on_theme_changed)

    # ------------------------------------------------------------------
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(8)

        # --- toolbar -----------------------------------------------------
        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)

        self.optimize_btn = QPushButton("Optimize Selected")
        self.optimize_btn.setProperty("variant", "accent")
        self.optimize_btn.setToolTip(
            "Run the full pipeline on the checked items (finishes with an\n"
            "audit so AUDIT tags stay current). Enable Force to re-process\n"
            "everything regardless of state.")
        self.optimize_btn.setEnabled(False)
        self.optimize_btn.clicked.connect(self._optimize_selected)
        toolbar.addWidget(self.optimize_btn)

        # Force: master pill + per-feature menu
        self.force_flac = bool(self.config.get("force_flac_ui", False))
        self.force_images = bool(self.config.get("force_images_ui", False))
        self.force_audit = bool(self.config.get("force_audit_ui", False))
        self.force_switch = ToggleSwitch(
            self.force_flac and self.force_images and self.force_audit)
        self.force_switch.setToolTip(
            "Force: re-process everything regardless of state.\n"
            "Use the ▾ menu to toggle each force option individually.\n"
            "Applies to Optimize Selected, Run All and Run Custom.")
        self.force_switch.toggled.connect(self._on_force_master)

        force_label = QLabel("Force")
        force_label.setProperty("role", "muted")

        self.force_menu_btn = QToolButton()
        self.force_menu_btn.setText("▾")
        self.force_menu_btn.setToolTip("Configure individual force options.")
        self.force_menu_btn.clicked.connect(self._show_force_menu)

        toolbar.addWidget(self.force_switch)
        toolbar.addWidget(force_label)
        toolbar.addWidget(self.force_menu_btn)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setProperty("variant", "small")
        self.refresh_btn.clicked.connect(lambda: self.refresh(regrade=True))
        toolbar.addWidget(self.refresh_btn)

        self.unselect_btn = QPushButton("Unselect All")
        self.unselect_btn.setProperty("variant", "small")
        self.unselect_btn.setToolTip("Clear every checkbox in the tree.")
        self.unselect_btn.clicked.connect(self.unselect_all)
        toolbar.addWidget(self.unselect_btn)

        self.sel_label = QLabel("0 selected")
        self.sel_label.setProperty("role", "muted")
        toolbar.addSpacing(6)
        toolbar.addWidget(self.sel_label)

        toolbar.addStretch(1)

        # File-type view: audio only, or every file inside the albums.
        self.file_view = QComboBox()
        self.file_view.addItem("Audio files", "audio")
        self.file_view.addItem("All files", "all")
        show_all = bool(self.config.get("library_show_all_files", False))
        self.file_view.setCurrentIndex(1 if show_all else 0)
        self.file_view.setToolTip(
            "All files also lists the non-audio contents of every album\n"
            "(artwork, logs, cues, playlists…).")
        self.file_view.currentIndexChanged.connect(self._on_file_view)
        show_lbl = QLabel("Show:")
        toolbar.addWidget(show_lbl)
        toolbar.addWidget(self.file_view)

        # external tools (act on the checked selection)
        self.mp3tag_btn = QPushButton("Mp3tag")
        self.mp3tag_btn.setProperty("variant", "small")
        self.mp3tag_btn.setToolTip(
            "Open every checked folder/track in Mp3tag.")
        self.mp3tag_btn.clicked.connect(
            lambda: self.launch_external.emit("mp3tag", self.selected_dirs()))
        toolbar.addWidget(self.mp3tag_btn)

        self.picard_btn = QPushButton("Picard")
        self.picard_btn.setProperty("variant", "small")
        self.picard_btn.setToolTip(
            "Open every checked folder/track in MusicBrainz Picard.")
        self.picard_btn.clicked.connect(
            lambda: self.launch_external.emit("picard", self.selected_dirs()))
        toolbar.addWidget(self.picard_btn)

        self.foobar_btn = QPushButton("Enqueue in foobar2000")
        self.foobar_btn.setProperty("variant", "small")
        self.foobar_btn.setToolTip(
            "Enqueue every checked folder in foobar2000 (/add).")
        self.foobar_btn.clicked.connect(
            lambda: self.launch_external.emit(
                "foobar2000", self.selected_dirs()))
        toolbar.addWidget(self.foobar_btn)

        self.compact_switch = ToggleSwitch(
            bool(self.config.get("compact_ui", False)))
        self.compact_switch.setToolTip("Hide the column headers for a "
                                       "compact, name-only view.")
        self.compact_switch.toggled.connect(self._on_compact_toggle)
        compact_label = QLabel("Compact")
        compact_label.setProperty("role", "muted")
        toolbar.addWidget(self.compact_switch)
        toolbar.addWidget(compact_label)

        layout.addLayout(toolbar)

        # --- filter row ----------------------------------------------------
        filter_card = QFrame()
        filter_card.setObjectName("FilterCard")
        fl = QHBoxLayout(filter_card)
        fl.setContentsMargins(12, 8, 12, 8)
        fl.setSpacing(10)

        fl.addWidget(QLabel("Album Artist:"))
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by artist tag or folder…")
        self.filter_edit.textChanged.connect(
            lambda _: self._filter_timer.start())
        fl.addWidget(self.filter_edit, 1)

        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("variant", "small")
        clear_btn.clicked.connect(self._clear_filter)
        fl.addWidget(clear_btn)

        self.bad_only = ToggleSwitch(False)
        self.bad_only.setToolTip(
            "Hide passing albums — show only failed / ungraded ones.")
        self.bad_only.toggled.connect(lambda _on: self._rebuild_tree())
        bad_label = QLabel("Bad only")
        fl.addWidget(self.bad_only)
        fl.addWidget(bad_label)

        self.sort_combo = QComboBox()
        self._sort_labels = {
            "name": "Name (A–Z)",
            "grade_bad": "Grade — worst first",
            "grade_good": "Grade — best first",
        }
        for key, label in self._sort_labels.items():
            self.sort_combo.addItem(label, key)
        sort_key = self.config.get("library_sort", "name")
        if sort_key not in self._sort_labels:
            sort_key = "name"
        self.sort_combo.setCurrentIndex(
            list(self._sort_labels).index(sort_key))
        self.sort_combo.currentIndexChanged.connect(self._on_sort_change)
        fl.addWidget(self.sort_combo)

        layout.addWidget(filter_card)

        # --- tree card -------------------------------------------------------
        tree_card = QFrame()
        tree_card.setObjectName("Card")
        tl = QVBoxLayout(tree_card)
        tl.setContentsMargins(1, 1, 1, 1)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(TREE_COLUMNS))
        self.tree.setHeaderLabels([h for h, _w, _d in TREE_COLUMNS.values()])
        self.tree.setRootIsDecorated(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.NoSelection)
        self.tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self.tree.header().setSectionsMovable(False)
        self.tree.header().setStretchLastSection(True)
        self.tree.header().setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.header().customContextMenuRequested.connect(
            self._show_column_menu)

        for col, (_h, width, _d) in enumerate(TREE_COLUMNS.values()):
            self.tree.header().resizeSection(col, width)

        self._col_visible = {
            c: default for c, (_h, _w, default) in TREE_COLUMNS.items()}
        saved = self.config.get("library_columns") or {}
        for c in self._col_visible:
            self._col_visible[c] = bool(saved.get(c, self._col_visible[c]))
        self._apply_column_visibility()
        self.tree.setHeaderHidden(bool(self.config.get("compact_ui", False)))

        self.tree.itemChanged.connect(self._on_item_changed)

        tl.addWidget(self.tree)
        layout.addWidget(tree_card, 1)

        self._lib_folder = str(self.config.get("music_folder", "")).strip()
        self._lyrics_format = str(
            self.config.get("lyrics_format", "EMBEDDED")).upper()
        self._update_selection_label()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------
    def refresh(self, regrade=True):
        """Start (or restart) a background scan + grade of the library."""
        folder = str(self.config.get("music_folder", "")).strip()
        if folder != self._lib_folder:
            # New library: selection, filters and grade state do not
            # carry over.
            self._checked.clear()
            self._folder_artist.clear()
            self._grade_cache.clear()
        self._lib_folder = folder
        self._lyrics_format = str(
            self.config.get("lyrics_format", "EMBEDDED")).upper()
        if regrade:
            self._grade_cache.clear()

        if not folder or not os.path.isdir(folder):
            self._artists = {}
            self._root_albums = []
            self._other_files = {}
            self._rebuild_tree()
            self.status_message.emit("")
            return

        if self._scanner is not None:
            old = self._scanner
            old.stop()
            # Stale results are ignored via the generation counters in
            # the _on_scan_* slots; keep the retiring thread referenced
            # until it finishes so Python doesn't collect (and crash)
            # a running QThread.
            self._retired = getattr(self, "_retired", [])
            self._retired.append(old)
            old.finished.connect(lambda t=old: self._retired.remove(t))
        self._scan_gen += 1
        self._library_busy = True
        self.status_message.emit("Scanning library…")
        skip = () if regrade else set(self._grade_cache)
        self._scanner = LibraryScanner(
            folder, self._lyrics_format, self._scan_gen, skip_paths=skip)
        self._scanner.sig_data.connect(self._on_scan_data)
        self._scanner.sig_grade.connect(self._on_scan_grade)
        self._scanner.sig_done.connect(self._on_scan_done)
        self._scanner.sig_failed.connect(self._on_scan_failed)
        self._scanner.start()

    def regrade_albums(self, albums):
        albums = [a for a in albums if a]
        if not albums:
            return
        self.status_message.emit("Re-grading albums…")
        self._retired = getattr(self, "_retired", [])
        worker = RegradeWorker(albums, self._lyrics_format)
        self._retired.append(worker)
        worker.finished.connect(lambda t=worker: self._retired.remove(t))
        worker.sig_grade.connect(self._on_direct_grade)
        # One rebuild at the end refreshes the ancestor aggregates
        # (artist / root rows) that per-album updates leave stale.
        worker.finished.connect(self._on_regrades_done)
        worker.start()
        self._regrade_worker = worker

    def _on_regrades_done(self):
        self._rebuild_tree()
        self.status_message.emit("Library updated")

    def shutdown(self):
        """Stop background work so the app can exit cleanly."""
        if self._scanner is not None:
            self._scanner.stop()
        for t in getattr(self, "_retired", []):
            t.stop() if hasattr(t, "stop") else None
            t.wait(3000)

    # Generation-guarded slots --------------------------------------------
    def _on_scan_data(self, gen, artists, root_albums, other_files):
        if gen != self._scan_gen:
            return
        self._artists = artists
        self._root_albums = root_albums
        self._other_files = other_files
        self._rebuild_tree()

    def _on_scan_grade(self, gen, album_dir, result):
        if gen != self._scan_gen:
            return
        self._apply_grade(album_dir, result)

    def _on_direct_grade(self, album_dir, result):
        self._apply_grade(album_dir, result)

    def _on_scan_done(self, gen):
        if gen != self._scan_gen:
            return
        self._library_busy = False
        self.status_message.emit("Library scan complete")
        if self._sort_mode() != "name" or self.bad_only.isChecked():
            self._rebuild_tree()

    def _on_scan_failed(self, gen, message):
        if gen != self._scan_gen:
            return
        self._library_busy = False
        self.status_message.emit("Library scan failed")
        self.log_line.emit(f"Library scan failed: {message}", "red")

    @property
    def busy(self):
        return self._library_busy

    # ------------------------------------------------------------------
    # Tree building
    # ------------------------------------------------------------------
    def _iter_items(self):
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            for i in range(item.childCount()):
                stack.append(item.child(i))

    def _collect_open(self):
        return {
            item.data(0, ROLE_PATH)
            for item in self._iter_items() if item.isExpanded()
        }

    def _rebuild_tree(self):
        self._updating = True
        try:
            scroll = self.tree.verticalScrollBar().value()
            open_paths = self._collect_open()
            self.tree.clear()
            self._path_items = {}
            self._agg = {}
            self._agg_total = {}

            folder = self._lib_folder
            if not folder or not os.path.isdir(folder):
                msg = QTreeWidgetItem(
                    ["No library folder set — use Browse to pick one"])
                msg.setFlags(Qt.ItemFlag.NoItemFlags)
                self.tree.addTopLevelItem(msg)
                self._root_item = None
                self._update_selection_label()
                return

            filter_text = self.filter_edit.text().strip().lower()

            root_text = f"All Folders ({os.path.basename(folder)})"
            self._root_item = self._make_item(root_text, folder, parent=True)
            self.tree.addTopLevelItem(self._root_item)
            self._root_item.setExpanded(True)
            self._agg[self._root_item] = self._new_agg()
            self._agg_total[self._root_item] = 0

            shown_any = False
            for parent_dir, album_dirs in sorted(
                    self._artists.items(),
                    key=lambda kv: self._artist_sort_key(kv[0])):
                artist_name = os.path.basename(parent_dir) or parent_dir
                tag_artist = self._folder_artist.get(parent_dir, "")
                if filter_text and filter_text not in artist_name.lower() \
                        and filter_text not in tag_artist.lower():
                    continue
                visible = [d for d in album_dirs if self._album_visible(d)]
                if self.bad_only.isChecked() and not visible:
                    continue
                shown_any = True
                artist_item = self._make_item(artist_name, parent_dir,
                                              parent=True)
                self._root_item.addChild(artist_item)
                self._agg[artist_item] = self._new_agg()
                count = len(visible) if self.bad_only.isChecked() \
                    else len(album_dirs)
                self._agg_total[artist_item] = count
                self._agg_total[self._root_item] += count
                for album_dir in sorted(visible, key=self._album_sort_key):
                    self._insert_album(artist_item, album_dir)

            root_visible = [d for d in self._root_albums
                            if self._album_visible(d)]
            for album_dir in sorted(root_visible, key=self._album_sort_key):
                shown_any = True
                self._insert_album(self._root_item, album_dir)
                self._agg_total[self._root_item] += 1

            self._root_item.setText(
                0, f"{root_text} — {len(self._grade_cache)} graded")

            for item in self._iter_items():
                path = item.data(0, ROLE_PATH)
                item.setExpanded(bool(path and path in open_paths))
            self._root_item.setExpanded(True)

            # aggregate cached grades up the tree
            self._accumulate(self._root_item)

            if filter_text and not shown_any:
                msg = QTreeWidgetItem(["No albums match the filter"])
                msg.setFlags(Qt.ItemFlag.NoItemFlags)
                self.tree.addTopLevelItem(msg)

            self.tree.verticalScrollBar().setValue(scroll)
        finally:
            self._updating = False
        self._update_selection_label()

    def _make_item(self, text, path, parent=False):
        item = QTreeWidgetItem([text])
        item.setFlags(Qt.ItemFlag.ItemIsUserCheckable
                      | Qt.ItemFlag.ItemIsEnabled)
        state = self._checked.get(path)
        item.setCheckState(
            0, Qt.CheckState(state) if state is not None
            else Qt.CheckState.Unchecked)
        item.setData(0, ROLE_PATH, path)
        self._path_items.setdefault(path, set()).add(id(item))
        return item

    def _insert_album(self, parent_item, album_dir):
        base = os.path.basename(album_dir)
        item = self._make_item(base, album_dir)
        parent_item.addChild(item)

        res = self._grade_cache.get(album_dir)
        if res is None:
            for c in range(1, len(TREE_COLUMNS)):
                item.setText(c, "…")
            self._paint_row(item, "pending")
        else:
            self._apply_album(item, album_dir, res)
        return item

    def _new_agg(self):
        return {"albums": 0, "passed": 0, "checks": 0, "pass_checks": 0,
                "tracks": 0, "media": set(), "covers": 0, "aa": set(),
                "ta": set(), "genre": set(), "inst": set(), "lyrics": 0,
                "track_total": 0, "audit": set()}

    def _accumulate(self, item):
        """Bottom-up aggregation of cached grades into container rows."""
        for i in range(item.childCount()):
            child = item.child(i)
            path = child.data(0, ROLE_PATH)
            res = self._grade_cache.get(path) if path else None
            if res is not None:
                self._add_agg(item, res)
            self._accumulate(child)
        if item is not self._root_item:
            self._apply_agg(item)

    # ------------------------------------------------------------------
    # Grade application
    # ------------------------------------------------------------------
    def _apply_grade(self, album_dir, result):
        was_cached = album_dir in self._grade_cache
        self._grade_cache[album_dir] = result
        artist = (result or {}).get("album_artist")
        if artist:
            parent = os.path.dirname(album_dir)
            if parent and parent not in self._folder_artist:
                self._folder_artist[parent] = artist

        items = [it for it in self._iter_items()
                 if it.data(0, ROLE_PATH) == album_dir]
        if not items:
            return
        item = items[0]
        self._apply_album(item, album_dir, result)
        if not was_cached:
            parent = item.parent()
            while parent is not None:
                self._add_agg(parent, result)
                parent = parent.parent()

    def _apply_album(self, item, album_dir, res):
        if "error" in res:
            self._updating = True
            try:
                for c in range(1, len(TREE_COLUMNS)):
                    item.setText(c, "ERR" if c == 1 else "")
            finally:
                self._updating = False
            self._paint_row(item, "fail")
            return

        self._updating = True
        try:
            ok = res["pass_count"] == res["total_checks"]
            audit = res.get("audit_summary")
            aa_value = (res.get("album_values") or {}
                        ).get("ALBUMITUNESADVISORY")

            values = [
                "PASS" if ok else "FAIL",
                audit or "—",
                f"{res['pass_count']}/{res['total_checks']}",
                str(res["track_count"]),
                res["media"],
                res["cover_file"] or "MISSING",
                self._album_tags_txt(res),
            ]
            for c, v in enumerate(values, start=1):
                item.setText(c, v)
            self._paint_row(item, row_state(ok, audit))

            # rebuild children
            while item.childCount():
                item.removeChild(item.child(0))
            for tr in res["tracks"]:
                self._insert_track(item, album_dir, tr, aa_value)
            if self.show_all_files():
                for fn in self._other_files.get(album_dir, []):
                    self._insert_other_file(item, album_dir, fn)
        finally:
            self._updating = False

    def _insert_track(self, album_item, album_dir, tr, aa_value=None):
        path = os.path.join(album_dir, tr["file"])
        issues = tr.get("issues") or []
        ok = not issues and not tr.get("unreadable")
        audit = tr.get("audit")
        item = self._make_item(tr["file"], path)
        values = [
            "OK" if ok else "FAIL",
            audit or "—",
            str(len(issues)) if issues else "",
            "—",
            tr["values"].get("MEDIA") or "",
            "—",
            self._track_tags_txt(tr, aa_value),
        ]
        for c, v in enumerate(values, start=1):
            item.setText(c, v)
        self._paint_row(item, row_state(ok, audit))
        album_item.addChild(item)

    def _insert_other_file(self, album_item, album_dir, fn):
        path = os.path.join(album_dir, fn)
        item = QTreeWidgetItem([fn])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)   # informational only
        item.setData(0, ROLE_PATH, path)
        item.setData(0, ROLE_OTHER, True)
        self._path_items.setdefault(path, set()).add(id(item))
        for c in range(1, len(TREE_COLUMNS)):
            item.setText(c, "—")
        self._paint_row(item, "other")
        album_item.addChild(item)

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------
    def _add_agg(self, item, res):
        agg = self._agg.get(item)
        if agg is None:
            return
        agg["albums"] += 1
        if "error" not in res:
            if res["pass_count"] == res["total_checks"]:
                agg["passed"] += 1
            agg["checks"] += res["total_checks"]
            agg["pass_checks"] += res["pass_count"]
            agg["tracks"] += res["track_count"]
            if res.get("media"):
                agg["media"].add(str(res["media"]))
            if res.get("cover_file"):
                agg["covers"] += 1
            av = res.get("album_values") or {}
            aa = av.get("ALBUMITUNESADVISORY")
            if aa is not None and str(aa).strip():
                agg["aa"].add(str(aa).strip())
            for tr in res.get("tracks") or []:
                v = tr.get("values") or {}
                for key, target in (("ITUNESADVISORY", "ta"),
                                    ("GENRE", "genre"),
                                    ("INSTRUMENTAL", "inst")):
                    val = v.get(key)
                    if val is not None and str(val).strip():
                        agg[target].add(str(val).strip())
                if tr.get("lyrics_embedded") or tr.get("lyrics_lrc"):
                    agg["lyrics"] += 1
            agg["track_total"] += res.get("track_count") or 0
            if res.get("audit_summary"):
                agg["audit"].add(str(res["audit_summary"]))
        self._apply_agg(item)

    def _apply_agg(self, item):
        agg = self._agg.get(item)
        if agg is None:
            return
        albums = agg["albums"]
        grade_txt = f"{agg['passed']}/{albums}" if albums else "—"
        audit_txt = summarize_audits(agg["audit"]) or "—"
        checks_txt = f"{agg['pass_checks']}/{agg['checks']}" \
            if agg["checks"] else "—"
        media_txt = "Mixed" if len(agg["media"]) > 1 \
            else (next(iter(agg["media"]), "") or "—")
        cover_txt = f"{agg['covers']}/{albums}" if albums else "—"
        tags_txt = ""
        if albums:
            tags_txt = (
                f"G:{self._fmt_vals(agg['genre'])} "
                f"A:{self._fmt_vals(agg['ta'])} "
                f"I:{self._fmt_vals(agg['inst'])} "
                f"L:{agg['lyrics']}/{agg['track_total']} "
                f"AA:{self._fmt_vals(agg['aa'])}"
            )
        for c, v in enumerate([
                grade_txt, audit_txt, checks_txt,
                str(agg["tracks"]) if agg["tracks"] else "—",
                media_txt, cover_txt, tags_txt], start=1):
            item.setText(c, v)

        expected = self._agg_total.get(item, albums)
        if albums and albums >= expected:
            if agg["passed"] == albums:
                grade_ok = True
            elif agg["passed"] == 0:
                grade_ok = False
            else:
                grade_ok = None
            self._paint_row(item, row_state(grade_ok, audit_txt))

    # ------------------------------------------------------------------
    # Cell formatting helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _fmt_tag_val(v, max_len=10):
        s = str(v).strip() if v is not None else ""
        if not s or s == "INCONSISTENT":
            return "—"
        return s[:max_len]

    @staticmethod
    def _fmt_vals(vals, max_n=3, max_len=10):
        clean = sorted(
            str(v).strip() for v in vals
            if v is not None and str(v).strip()
            and str(v).strip() != "INCONSISTENT"
        )
        if not clean:
            return "—"
        out = "|".join(v[:max_len] for v in clean[:max_n])
        if len(clean) > max_n:
            out += f"+{len(clean) - max_n}"
        return out

    def _sum_key(self, res, key):
        vals = set()
        for tr in res.get("tracks") or []:
            v = (tr.get("values") or {}).get(key)
            if v is not None and str(v).strip():
                vals.add(str(v).strip())
        return self._fmt_vals(vals)

    def _track_tags_txt(self, tr, aa_value=None):
        v = tr.get("values") or {}
        lyr = 1 if (tr.get("lyrics_embedded") or tr.get("lyrics_lrc")) else 0
        return (
            f"G:{self._fmt_tag_val(v.get('GENRE'), 12)} "
            f"A:{self._fmt_tag_val(v.get('ITUNESADVISORY'), 8)} "
            f"I:{self._fmt_tag_val(v.get('INSTRUMENTAL'), 4)} "
            f"L:{lyr} "
            f"AA:{self._fmt_tag_val(aa_value, 8)}"
        )

    def _album_tags_txt(self, res):
        av = res.get("album_values") or {}
        tracks = res.get("tracks") or []
        lyr = sum(1 for tr in tracks
                  if tr.get("lyrics_embedded") or tr.get("lyrics_lrc"))
        tot = res.get("track_count") or 0
        return (
            f"G:{self._sum_key(res, 'GENRE')} "
            f"A:{self._sum_key(res, 'ITUNESADVISORY')} "
            f"I:{self._sum_key(res, 'INSTRUMENTAL')} "
            f"L:{lyr}/{tot} "
            f"AA:{self._fmt_tag_val(av.get('ALBUMITUNESADVISORY'), 8)}"
        )

    # ------------------------------------------------------------------
    # Row painting
    # ------------------------------------------------------------------
    def _paint_row(self, item, state):
        p = THEME.palette()
        item.setData(0, ROLE_STATE, state)
        if state == "other":
            fg = QBrush(QColor(p["faint"]))
            for c in range(len(TREE_COLUMNS)):
                item.setForeground(c, fg)
            return
        if state == "pending":
            bg = None
            fg = QBrush(QColor(p["muted"]))
        else:
            bg_hex, fg_hex = p[f"row_{state}"]
            bg = QBrush(QColor(bg_hex))
            fg = QBrush(QColor(fg_hex))
        for c in range(len(TREE_COLUMNS)):
            if bg is not None:
                item.setBackground(c, bg)
            item.setForeground(c, fg)

    def _on_theme_changed(self):
        self._updating = True
        try:
            for item in self._iter_items():
                state = item.data(0, ROLE_STATE)
                if state:
                    self._paint_row(item, state)
        finally:
            self._updating = False

    # ------------------------------------------------------------------
    # Selection / checkboxes
    # ------------------------------------------------------------------
    def _on_item_changed(self, item, column):
        if self._updating or column != 0:
            return
        path = item.data(0, ROLE_PATH)
        if not path:
            return
        self._updating = True
        try:
            on = item.checkState(0) != Qt.CheckState.Unchecked
            # cascade down to every descendant
            stack = [item]
            while stack:
                cur = stack.pop()
                cp = cur.data(0, ROLE_PATH)
                if cp:
                    self._checked[cp] = (
                        Qt.CheckState.Checked.value if on
                        else Qt.CheckState.Unchecked.value)
                    cur.setCheckState(
                        0, Qt.CheckState.Checked if on
                        else Qt.CheckState.Unchecked)
                for i in range(cur.childCount()):
                    stack.append(cur.child(i))
            # recompute ancestors
            parent = item.parent()
            while parent is not None:
                pp = parent.data(0, ROLE_PATH)
                state = self._parent_state(parent)
                if pp:
                    self._checked[pp] = state.value
                    parent.setCheckState(0, state)
                parent = parent.parent()
        finally:
            self._updating = False
        self._update_selection_label()

    @staticmethod
    def _parent_state(item):
        n = item.childCount()
        if n == 0:
            return Qt.CheckState.Unchecked
        checked = sum(
            1 for i in range(n)
            if item.child(i).checkState(0) == Qt.CheckState.Checked)
        if checked == 0:
            return Qt.CheckState.Unchecked
        if checked == n:
            return Qt.CheckState.Checked
        return Qt.CheckState.PartiallyChecked

    def selected_paths(self):
        """Deepest fully-checked paths (tracks, albums or artist dirs)."""
        out = []

        def visit(item):
            path = item.data(0, ROLE_PATH)
            checked = bool(item.flags() & Qt.ItemFlag.ItemIsUserCheckable) \
                and item.checkState(0) == Qt.CheckState.Checked
            appended_below = False
            for i in range(item.childCount()):
                if visit(item.child(i)):
                    appended_below = True
            if checked and not appended_below and path:
                out.append(path)
                return True
            return appended_below

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))
        return sorted(out)

    def selected_dirs(self):
        """Unique directories covered by the checked tree items."""
        dirs = []
        seen = set()
        for path in self.selected_paths():
            d = os.path.dirname(path) if os.path.isfile(path) else path
            if d and d not in seen and os.path.isdir(d):
                seen.add(d)
                dirs.append(d)
        return sorted(dirs)

    def unselect_all(self):
        self._checked.clear()
        self._updating = True
        try:
            for item in self._iter_items():
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(0, Qt.CheckState.Unchecked)
        finally:
            self._updating = False
        self._update_selection_label()

    def _update_selection_label(self):
        self.sel_label.setText(f"{len(self.selected_paths())} selected")

    def _optimize_selected(self):
        targets = self.selected_paths()
        if targets:
            self.run_requested.emit(targets)

    def set_running(self, running):
        self.optimize_btn.setEnabled(
            not running and bool(self.selected_paths()))
        self.refresh_btn.setEnabled(not running)

    # ------------------------------------------------------------------
    # Filters / sorting / view options
    # ------------------------------------------------------------------
    def _clear_filter(self):
        self.filter_edit.clear()
        self._rebuild_tree()

    def _on_sort_change(self):
        self.config["library_sort"] = self.sort_combo.currentData() or "name"
        save_config(self.config)
        self._rebuild_tree()

    def _sort_mode(self):
        key = self.sort_combo.currentData() or "name"
        return key if key in ("grade_bad", "grade_good") else "name"

    def _on_file_view(self):
        show_all = self.file_view.currentData() == "all"
        if bool(self.config.get("library_show_all_files")) != show_all:
            self.config["library_show_all_files"] = show_all
            save_config(self.config)
        self._rebuild_tree()

    def show_all_files(self):
        return self.file_view.currentData() == "all"

    def _on_compact_toggle(self, on):
        self.config["compact_ui"] = bool(on)
        save_config(self.config)
        self.tree.setHeaderHidden(bool(on))

    def _album_visible(self, album_dir):
        if not self.bad_only.isChecked():
            return True
        res = self._grade_cache.get(album_dir)
        if not res or "error" in res:
            return True
        return res["pass_count"] != res["total_checks"]

    def _album_sort_key(self, d):
        res = self._grade_cache.get(d)
        name = os.path.basename(d).lower()
        mode = self._sort_mode()
        if mode == "name":
            return (0, 0.0, name)
        if not res or "error" in res:
            return (1, 0.0, name)
        frac = res["pass_count"] / max(1, res["total_checks"])
        if mode == "grade_good":
            frac = -frac
        return (0, frac, name)

    def _artist_sort_key(self, parent_dir):
        albums = (self._artists or {}).get(parent_dir, [])
        name = os.path.basename(parent_dir).lower()
        mode = self._sort_mode()
        if mode == "name":
            return (0, 0.0, name)
        worst = 1.0
        graded_any = False
        for d in albums:
            res = self._grade_cache.get(d)
            if res and "error" not in res:
                graded_any = True
                worst = min(worst,
                            res["pass_count"] / max(1, res["total_checks"]))
        if not graded_any:
            return (1, 0.0, name)
        if mode == "grade_good":
            worst = -worst
        return (0, worst, name)

    # ------------------------------------------------------------------
    # Force options
    # ------------------------------------------------------------------
    def force_settings(self):
        return (self.force_flac, self.force_images, self.force_audit)

    def _on_force_master(self, on):
        self.force_flac = self.force_images = self.force_audit = bool(on)
        self._save_force_config()

    def _on_force_option(self):
        self.force_switch.toggled.disconnect(self._on_force_master)
        try:
            self.force_switch.setChecked(
                self.force_flac and self.force_images and self.force_audit)
        finally:
            self.force_switch.toggled.connect(self._on_force_master)
        self._save_force_config()

    def _save_force_config(self):
        self.config["force_ui"] = self.force_switch.isChecked()
        self.config["force_flac_ui"] = self.force_flac
        self.config["force_images_ui"] = self.force_images
        self.config["force_audit_ui"] = self.force_audit
        save_config(self.config)

    def _show_force_menu(self):
        menu = QMenu(self)
        head = menu.addAction("Force options")
        head.setEnabled(False)
        menu.addSeparator()
        for attr, label in (
            ("force_flac", "Re-encode FLACs"),
            ("force_images", "Re-encode images"),
            ("force_audit", "Audit"),
        ):
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(getattr(self, attr))
            act.toggled.connect(
                lambda on, a=attr: (setattr(self, a, on),
                                    self._on_force_option()))
        menu.addSeparator()

        def all_on():
            self.force_flac = self.force_images = self.force_audit = True
            self.force_switch.setChecked(True)

        def all_off():
            self.force_flac = self.force_images = self.force_audit = False
            self.force_switch.setChecked(False)

        menu.addAction("All on", all_on)
        menu.addAction("All off", all_off)
        menu.exec(self.force_menu_btn.mapToGlobal(
            self.force_menu_btn.rect().bottomLeft()))

    # ------------------------------------------------------------------
    # Columns
    # ------------------------------------------------------------------
    def _apply_column_visibility(self):
        for c, col_id in enumerate(TREE_COLUMNS):
            self.tree.setColumnHidden(c, not self._col_visible[col_id])

    def _toggle_column(self, col_id):
        self._col_visible[col_id] = not self._col_visible[col_id]
        self.config["library_columns"] = dict(self._col_visible)
        save_config(self.config)
        self._apply_column_visibility()

    def _show_column_menu(self, pos):
        menu = QMenu(self)
        head = menu.addAction("Columns")
        head.setEnabled(False)
        menu.addSeparator()
        for col_id, (heading, _w, _d) in TREE_COLUMNS.items():
            label = heading.replace(" · G A I L AA", "")
            act = menu.addAction(label)
            act.setCheckable(True)
            act.setChecked(self._col_visible[col_id])
            act.toggled.connect(lambda _on, c=col_id: self._toggle_column(c))
        menu.addSeparator()
        key = menu.addAction("TAGS key: G Genre · A Advisory · I Instrumental"
                             " · L Lyrics · AA Album Advisory")
        key.setEnabled(False)
        menu.exec(self.tree.header().mapToGlobal(pos))

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------
    def _find_album_for_item(self, item):
        path = item.data(0, ROLE_PATH)
        if not path:
            return None, None
        res = self._grade_cache.get(path)
        if res is not None:
            return path, res
        parent = item.parent()
        while parent is not None:
            p = parent.data(0, ROLE_PATH)
            if p and p in self._grade_cache:
                return p, self._grade_cache[p]
            parent = parent.parent()
        return None, None

    def _on_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        header = self.tree.header()
        if pos.y() < header.height() or item is None:
            return

        path = item.data(0, ROLE_PATH)
        album_dir, res = self._find_album_for_item(item)
        sel_dirs = self.selected_dirs()
        n_sel = len(sel_dirs)

        menu = QMenu(self)

        if res is not None:
            menu.addAction("Grade details…",
                           lambda: self._emit_grade_details(item))
        if album_dir:
            is_track = path is not None and path != album_dir
            menu.addAction(
                "Edit track tags…" if is_track else "Edit album tags…",
                lambda: self.edit_tags.emit(
                    album_dir, path if is_track else None))
            target_dir = path if (path and os.path.isdir(path)) else album_dir
            menu.addSeparator()
            # Selection-aware external tools: with items checked, act on
            # the whole selection (plus this row when it is not in it).
            dirs = list(sel_dirs)
            if target_dir not in dirs:
                dirs.append(target_dir)
            n = len(dirs)
            menu.addAction(
                f"Open selection in Mp3tag ({n} folder{'s' if n != 1 else ''})"
                if n > 1 else "Open in Mp3tag",
                lambda: self.launch_external.emit("mp3tag", dirs))
            menu.addAction("Open in Picard",
                           lambda: self.launch_external.emit("picard", dirs))
            menu.addAction("Enqueue in foobar2000",
                           lambda: self.launch_external.emit(
                               "foobar2000", dirs))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _emit_grade_details(self, item):
        album_dir, res = self._find_album_for_item(item)
        if res is None:
            return
        path = item.data(0, ROLE_PATH)
        track_file = path if (album_dir and path != album_dir) else None
        self.grade_details.emit(album_dir, res, track_file)
