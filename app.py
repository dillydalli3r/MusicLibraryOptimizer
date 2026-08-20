#!/usr/bin/env python3
"""
Music Library Optimizer - Desktop Application
=============================================
Modern dark-themed GUI front-end for the `mlo` core package.

Layout
------
    mlo/            organized core package (all processing logic)
    app.py          this GUI entry point
    config.json     persisted settings (created on first save)
    .dependencies/  external encoder toolchain (flac, libjxl,
                    libjpeg-turbo, oxipng)

Requires:  pip install mutagen
Optional:  pip install Pillow tqdm
"""

import os
import re
import shutil
import subprocess
import sys
import queue
import time
import threading
import traceback
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox

from mlo import (
    load_config, save_config,
    run_auto_tagging,
    run_format_lyrics, run_format_cues, run_optimize_flacs,
    run_grade_library, run_process_images, run_audit_library,
    run_calc_dr_replaygain,
)
from mlo import stats as stats_mod
from mlo import tools as tools_mod
from mlo import fetchdeps
from mlo import updater
from mlo.config import DEFAULT_CONFIG, DEFAULT_RUN_ALL_ORDER, normalize_config
from mlo.paths import DEFAULT_DIGITAL_SOURCE, DEPS_DIR, SCRIPT_DIR
from mlo.deps import HAS_MUTAGEN, HAS_PIL
from mlo.report import print_results, print_grade_results, print_combined_results
from mlo.subproc import active_process_count
from mlo.ui import set_file_lines


from mlo.gui import (
    BG, PANEL, SIDEBAR, CARD, FIELD, BORDER, BORDER_STRONG, TEXT, BRIGHT,
    MUTED, ACCENT, ACCENT_DARK, GREEN, RED, YELLOW, UI_FAMILY, MONO_FAMILY,
    SCRIPT_NAMES, SIDEBAR_ICONS, TREE_COLUMNS, CONFIG_FIELDS,
    FIELD_DESCRIPTIONS, EXTERNAL_TOOLS, find_external_tool, _font, _sfont,
    _pick_ui_family, ToggleSwitch, ToolTip, WrapFrame, QueueStream,
    apply_window_chrome,
)
from mlo.gui_dialogs import (
    DependenciesDialog, ConfigDialog, CustomRunDialog, FirstRunWizard,
)


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


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        from mlo import __version__
        self.title(f"Music Library Optimizer v{__version__}")
        self.configure(background=BG)
        self.geometry("1180x760")
        self.minsize(880, 580)
        # Keep the window at its current size when switching Library/Console
        # tabs (the tabs already highlight the active one) instead of the
        # notebook resizing the whole window to fit its content.
        self.pack_propagate(False)

        if not HAS_MUTAGEN:
            self.withdraw()
            messagebox.showerror(
                "Missing dependency",
                "mutagen is required.\n\nInstall it with:\n    pip install mutagen",
            )
            self.destroy()
            return

        self.config = load_config()
        self.log_q = queue.Queue()
        self._instance_state_path = updater.register_instance()
        self._busy_reasons = set()
        self.running = False
        self._run_thread = None
        self._deps_busy = False
        self._shutdown_for_update = False
        self._update_result = None
        self.run_buttons = []
        self._continue_event = threading.Event()
        self._continue_event.set()

        # Portable/self-contained: create .dependencies/ next to the app and
        # verify the app folder is writable (config.json lives there too).
        from mlo.paths import ensure_data_dirs
        self._data_dir_error = ensure_data_dirs()

        global UI_FAMILY
        UI_FAMILY = _pick_ui_family()

        # Set up styles before anything renders (wizard or main window).
        self._setup_style()
        self._monospace = self._pick_monospace()
        self._build_ui()

        try:
            icon_file = os.path.join(SCRIPT_DIR, "app_icon.ico")
            if os.path.isfile(icon_file):
                self.iconbitmap(default=icon_file)
        except tk.TclError:
            pass

        # Start the console plumbing (stdout redirect + log drain).
        self._start_console()

        # First-run wizard: the main window is always shown; the wizard is
        # a modal on top of it. Creating the modal against a *visible* root
        # maps reliably (a transient/grab on a withdrawn root may never
        # display, leaving the app with no visible window).
        if not self.config.get("first_run_done", False):
            self.after(150, self._show_first_run_wizard)

    def _show_first_run_wizard(self):
        """Create the first-run wizard inside the running event loop.

        Creation is guarded: if the wizard fails for any reason the main
        window stays fully usable rather than the app appearing to hang.
        """
        try:
            FirstRunWizard(self, self.config, self._after_first_run)
        except Exception:
            import traceback as _tb
            traceback.print_exc()
            self.log("First-run wizard could not be shown; you can configure "
                     "everything from ⚙ Settings.", tag="red")

    def _start_console(self):
        """Redirect stdout/stderr to the GUI console and start draining."""
        self.stdout_stream = QueueStream(self.log_q)
        self._real_stdout, self._real_stderr = sys.stdout, sys.stderr
        sys.stdout = self.stdout_stream
        sys.stderr = self.stdout_stream
        self.after(80, self._drain_log)
        self.after(150, lambda: apply_window_chrome(self))
        self.log("Music Library Optimizer ready.")
        if not HAS_PIL:
            self.log("WARNING: Pillow not found - PNG alpha removal will be skipped.",
                     tag="yellow")
        self.log(f"Library folder: {self.config.get('music_folder', '')}", tag="muted")
        if getattr(self, "_data_dir_error", None):
            self.log("WARNING: The app folder is not writable - config.json and "
                     f".dependencies cannot be saved here. ({self._data_dir_error})",
                     tag="yellow")
        # Auto-check for updates on start (configurable; respects interval).
        if self.config.get("check_updates_on_start", True):
            self.after(
                5000,
                lambda: updater.maybe_auto_check(
                    callback=lambda *result: self.log_q.put(
                        ("update_auto", result)
                    )
                ),
            )

    # ------------------------------------------------------------------
    @staticmethod
    def _pick_monospace():
        try:
            families = set(tkfont.families())
            for name in ("Cascadia Code", "Cascadia Mono", "Consolas",
                         "Courier New"):
                if name in families:
                    return name
        except Exception:
            pass
        return "TkFixedFont"

    def _after_first_run(self):
        """Called when first-run wizard completes. Main window is already
        visible; just refresh the library with the chosen folder."""
        self.config = normalize_config(self.config)
        self.folder_var.set(self.config.get("music_folder", ""))
        self._lib_folder = self.folder_var.get().strip()
        self._refresh_library(regrade=True)

    def _show_setup_guide(self):
        """Reopen the first-run introduction without resetting settings."""
        if self._has_active_work():
            messagebox.showinfo(
                "Busy", "Wait for the current operation to finish before opening the guide.",
                parent=self,
            )
            return
        FirstRunWizard(self, self.config, self._after_first_run, reopen=True)

    # ------------------------------------------------------------------
    def _setup_style(self):
        style = ttk.Style(self)
        style.theme_use("clam")

        base_font = _font(10)
        self.option_add("*Font", base_font)
        style.configure(".", background=BG, foreground=TEXT, borderwidth=0,
                        focuscolor=ACCENT)

        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("Card.TFrame", background=CARD)
        style.configure("Side.TFrame", background=SIDEBAR)

        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Card.TLabel", background=CARD, foreground=TEXT)
        style.configure("Side.TLabel", background=SIDEBAR, foreground=TEXT)
        style.configure("Muted.TLabel", foreground=MUTED)
        style.configure("Muted.Panel.TLabel", background=PANEL, foreground=MUTED)
        style.configure("Muted.Card.TLabel", background=CARD, foreground=MUTED)
        style.configure("Muted.Side.TLabel", background=SIDEBAR, foreground=MUTED)
        style.configure("Accent.TLabel", foreground=ACCENT)
        style.configure("H1.TLabel", foreground=BRIGHT, font=_sfont(15))
        style.configure("H1.Panel.TLabel", background=PANEL, foreground=BRIGHT,
                        font=_sfont(15))
        style.configure("H2.TLabel", foreground=ACCENT, font=_sfont(10))
        style.configure("H2.Panel.TLabel", background=PANEL, foreground=ACCENT,
                        font=_sfont(10))
        # Small-caps style section headers. Two variants because the same
        # style is used on the sidebar (SIDEBAR bg) and over the window
        # background / cards (BG bg) - clam would otherwise paint a
        # mismatched rectangle behind the text.
        style.configure("Section.TLabel", background=BG, foreground=MUTED,
                        font=_sfont(8))
        style.configure("Section.Side.TLabel", background=SIDEBAR,
                        foreground=MUTED, font=_sfont(8))
        style.configure("Section.Card.TLabel", background=CARD,
                        foreground=MUTED, font=_sfont(8))

        # Buttons: flat surfaces with a visible hover ramp.
        style.configure("TButton", background="#1f1f1f", foreground=TEXT,
                        borderwidth=0, focusthickness=0, padding=(14, 8))
        style.map("TButton",
                  background=[("pressed", "#2e2e2e"), ("active", "#2a2a2a"),
                              ("disabled", "#181818")],
                  foreground=[("disabled", "#4a4a4a")])
        style.configure("Accent.TButton", background=ACCENT, foreground="#0a0a0a")
        style.map("Accent.TButton",
                  background=[("pressed", "#cfcfcf"), ("active", BRIGHT),
                              ("disabled", "#2a2a2a")],
                  foreground=[("disabled", "#6a6a6a")])
        # Compact sidebar buttons: shorter padding, centered icon+label.
        style.configure("Side.TButton", anchor="center", padding=(8, 6))
        style.configure("Side.Accent.TButton", anchor="center", padding=(8, 6),
                        background="#2e2e2e", foreground=BRIGHT)
        style.map("Side.Accent.TButton",
                  background=[("pressed", "#3d3d3d"), ("active", "#3a3a3a"),
                              ("disabled", "#181818")],
                  foreground=[("disabled", "#4a4a4a")])
        style.map("Side.TButton",
                  background=[("pressed", "#262626"), ("active", "#222222"),
                              ("disabled", "#161616")])
        style.configure("Small.TButton", padding=(10, 4), font=_font(9))

        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, lightcolor=BORDER,
                        darkcolor=BORDER, borderwidth=1, padding=(8, 6))
        style.map("TEntry",
                  bordercolor=[("focus", "#6f6f6f")],
                  lightcolor=[("focus", "#6f6f6f")],
                  darkcolor=[("focus", "#6f6f6f")],
                  fieldbackground=[("readonly", FIELD)])

        style.configure("TSpinbox", fieldbackground=FIELD, foreground=TEXT,
                        insertcolor=TEXT, bordercolor=BORDER, arrowcolor=TEXT,
                        background="#1f1f1f", borderwidth=1,
                        lightcolor=BORDER, darkcolor=BORDER, arrowsize=11,
                        padding=(8, 5))
        style.map("TSpinbox", bordercolor=[("focus", "#6f6f6f")],
                  arrowcolor=[("disabled", MUTED)])

        style.configure("TCombobox", fieldbackground=FIELD, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        borderwidth=1, arrowsize=11, padding=(8, 5))
        style.map("TCombobox",
                  fieldbackground=[("readonly", FIELD)],
                  foreground=[("readonly", TEXT)],
                  bordercolor=[("focus", "#6f6f6f")],
                  lightcolor=[("focus", "#6f6f6f")],
                  darkcolor=[("focus", "#6f6f6f")])
        self.option_add("*TCombobox*Listbox*Background", FIELD)
        self.option_add("*TCombobox*Listbox*Foreground", TEXT)
        self.option_add("*TCombobox*Listbox*selectBackground", ACCENT_DARK)
        self.option_add("*TCombobox*Listbox*selectForeground", "#ffffff")
        self.option_add("*TCombobox*Listbox*BorderWidth", 1)
        self.option_add("*TCombobox*Listbox*HighlightThickness", 0)
        self.option_add("*TCombobox*Listbox*relief", "flat")

        # Note: booleans are rendered with ToggleSwitch (custom canvas),
        # not ttk checkbuttons - clam indicators render poorly on dark
        # themes.

        style.configure("TSeparator", background=BORDER)
        style.configure("Side.TSeparator", background="#1d1d1d")

        style.configure("TScrollbar", troughcolor="#121212", background="#2a2a2a",
                        bordercolor="#121212", arrowcolor=MUTED,
                        lightcolor="#2a2a2a", darkcolor="#2a2a2a",
                        relief="flat", gripcount=0)
        style.map("TScrollbar", background=[("active", "#3a3a3a")])

        style.configure("TNotebook", background=BG, borderwidth=0,
                        tabmargins=(2, 4, 0, 0))
        # Compact tab buttons. Every tab shares an identical 1px border so
        # all buttons are always exactly the same size; only the SELECTED
        # tab's border is drawn white so it clearly pops. The label is
        # inset past the border (padding), and a 2px left margin keeps the
        # first tab's white border from being clipped at the strip edge.
        style.configure("TNotebook.Tab", background="#141414",
                        foreground=MUTED, borderwidth=1, relief="flat",
                        padding=(12, 7), font=_sfont(9),
                        lightcolor="#141414", darkcolor="#141414",
                        bordercolor="#141414")
        style.map("TNotebook.Tab",
                  background=[("selected", CARD), ("active", "#1d1d1d")],
                  foreground=[("selected", BRIGHT), ("active", TEXT)],
                  padding=[("selected", (12, 7)), ("!selected", (12, 7))],
                  borderwidth=[("selected", 1), ("!selected", 1)],
                  bordercolor=[("selected", "#ffffff"), ("!selected", "#141414")],
                  lightcolor=[("selected", CARD), ("!selected", "#141414")],
                  darkcolor=[("selected", CARD), ("!selected", "#141414")])

        style.configure("Treeview", background="#121212", fieldbackground="#121212",
                        foreground=TEXT, borderwidth=0, rowheight=28,
                        font=_font(9))
        style.map("Treeview", background=[("selected", ACCENT_DARK)],
                  foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=CARD, foreground=MUTED,
                        borderwidth=0, padding=(10, 7), relief="flat",
                        font=_sfont(8))
        style.map("Treeview.Heading",
                  background=[("active", "#1f1f1f")])

        style.configure("TLabelframe", background=BG, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, relief="flat")
        style.configure("TLabelframe.Label", background=BG, foreground=MUTED,
                        font=_sfont(8))

        style.configure("Horizontal.TProgressbar", troughcolor="#1d1d1d",
                         background=ACCENT, lightcolor=ACCENT, darkcolor=ACCENT,
                         borderwidth=0, thickness=5)

        style.configure("TCheckbutton", background=BG, foreground=TEXT,
                        focuscolor=BG)

    # ------------------------------------------------------------------
    def _build_ui(self):
        # --- Folder bar ---------------------------------------------------
        folder_bar = ttk.Frame(self, padding=(12, 16, 18, 8))
        folder_bar.pack(fill=tk.X)
        folder_bar.columnconfigure(2, weight=1)
        # Sidebar toggle (always visible, outside the collapsible sidebar).
        self.sidebar_visible = tk.BooleanVar(
            value=self.config.get("sidebar_visible", True))
        toggle_btn = ttk.Button(
            folder_bar, text="\u2261", style="Small.TButton", width=2,
            command=self._toggle_sidebar)
        toggle_btn.grid(row=0, column=0, sticky="w", padx=(0, 10))
        ToolTip(toggle_btn, "Toggle the sidebar (Ctrl+B)")
        self.bind("<Control-b>", self._toggle_sidebar)
        self.bind("<Control-B>", self._toggle_sidebar)
        ttk.Label(folder_bar, text="LIBRARY FOLDER", style="Section.TLabel").grid(
            row=0, column=1, sticky="w", padx=(0, 12)
        )
        self.folder_var = tk.StringVar(value=self.config.get("music_folder", ""))
        ttk.Entry(folder_bar, textvariable=self.folder_var).grid(
            row=0, column=2, sticky="ew"
        )
        ttk.Button(folder_bar, text="Browse…", command=self._pick_folder).grid(
            row=0, column=3, padx=(10, 0)
        )

        # --- Main area ------------------------------------------------------
        main = ttk.Frame(self)
        main.pack(fill=tk.BOTH, expand=True)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)

        self._sidebar = sidebar = ttk.Frame(main, style="Side.TFrame")
        sidebar.grid(row=0, column=0, sticky="nswe")
        sidebar.rowconfigure(0, weight=1)
        sidebar.columnconfigure(0, weight=1)

        # Scrollable sidebar: the settings buttons gain a vertical scrollbar
        # when the window gets too short for them.
        self._side_canvas = tk.Canvas(
            sidebar, highlightthickness=0, background=SIDEBAR, width=230)
        self._side_scroll = ttk.Scrollbar(
            sidebar, orient=tk.VERTICAL, command=self._side_canvas.yview)
        self._side_canvas.configure(yscrollcommand=self._side_scroll.set)
        self._side_canvas.grid(row=0, column=0, sticky="nswe")
        self._side_scroll.grid(row=0, column=1, sticky="ns")

        inner = ttk.Frame(self._side_canvas, style="Side.TFrame",
                          padding=(16, 16))
        self._side_inner = inner
        inner_id = self._side_canvas.create_window((0, 0), window=inner,
                                                   anchor="nw")
        inner.bind(
            "<Configure>",
            lambda e: (self._side_canvas.configure(
                scrollregion=self._side_canvas.bbox("all")),
                self._sync_side_scrollbar()))
        self._side_canvas.bind(
            "<Configure>",
            lambda e: (self._side_canvas.itemconfigure(inner_id, width=e.width),
                       self._sync_side_scrollbar()))
        self._side_canvas.bind(
            "<Enter>",
            lambda e: self._side_canvas.bind_all(
                "<MouseWheel>", self._side_on_wheel))
        self._side_canvas.bind(
            "<Leave>", lambda e: self._side_canvas.unbind_all("<MouseWheel>"))

        # Branded header
        brand = ttk.Frame(inner, style="Side.TFrame")
        brand.pack(fill=tk.X, pady=(0, 16))
        brand_text = ttk.Frame(brand, style="Side.TFrame")
        brand_text.pack(side=tk.LEFT)
        ttk.Label(brand_text, text="Music Library",
                  style="Side.TLabel", font=_sfont(13), foreground=BRIGHT).pack(anchor="w")
        ttk.Label(brand_text, text="Optimizer",
                  style="Side.TLabel", font=_sfont(13), foreground=BRIGHT).pack(anchor="w")

        ttk.Label(inner, text="RUN SCRIPTS", style="Section.Side.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        for sid, name in SCRIPT_NAMES.items():
            icon = SIDEBAR_ICONS.get(sid, "")
            b = ttk.Button(
                inner, text=f"{icon}  {name}" if icon else name,
                style="Side.TButton",
                command=lambda s=sid: self._run_scripts([s], f"RUN — {SCRIPT_NAMES[s]}"),
            )
            b.pack(fill=tk.X, pady=1)
            self.run_buttons.append(b)

        ttk.Label(inner, text="BATCH", style="Section.Side.TLabel").pack(
            anchor="w", pady=(18, 8)
        )
        b = ttk.Button(inner, text="\u25b6  Run All", style="Side.Accent.TButton",
                       command=self._run_all)
        b.pack(fill=tk.X, pady=1)
        ToolTip(b, "Run every script in order.\n"
                "Enable ⚡ Force in the Library tab to force re-encoding.")
        self.run_buttons.append(b)
        b = ttk.Button(inner, text="\u29c9  Run Custom", style="Side.TButton",
                       command=self._run_custom)
        b.pack(fill=tk.X, pady=1)
        self.run_buttons.append(b)

        ttk.Label(inner, text="MANAGE", style="Section.Side.TLabel").pack(
            anchor="w", pady=(18, 8)
        )
        b = ttk.Button(inner, text="\u2b07  Dependencies", style="Side.TButton",
                       command=self._open_deps)
        b.pack(fill=tk.X, pady=1)
        self.run_buttons.append(b)

        # Size the canvas to the widest button (after fonts are laid out,
        # with a small margin so button text is never clipped horizontally),
        # and pin the tool-status label below the scrollable area.
        self.update_idletasks()
        self._side_canvas.configure(
            width=max(inner.winfo_reqwidth() + 8, 204))
        self.dep_label = ttk.Label(sidebar, text="", style="Muted.Side.TLabel",
                                   font=_font(8))
        self.dep_label.grid(row=1, column=0, columnspan=2, sticky="w",
                            padx=16, pady=(8, 0))
        self._update_dep_label()

        # Restore a hidden sidebar (persisted toggle state).
        if not self.sidebar_visible.get():
            sidebar.grid_remove()

        # --- Notebook (Library + Console tabs) ------------------------------
        self.notebook = ttk.Notebook(main)
        self.notebook.grid(row=0, column=1, sticky="nswe", padx=16, pady=(8, 8))
        notebook = self.notebook

        # --- Library tab ---------------------------------------------------
        library_frame = ttk.Frame(notebook, padding=(16, 12))
        notebook.add(library_frame, text="Library")
        library_frame.columnconfigure(0, weight=1)
        library_frame.rowconfigure(3, weight=1)

        toolbar = ttk.Frame(library_frame)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        # Right-side cluster is packed first (fixed width), then the left
        # action cluster wraps into the remaining space.
        toolbar_right = ttk.Frame(toolbar)
        toolbar_right.pack(side=tk.RIGHT)

        # Left action cluster wraps onto new rows when the window is narrow,
        # so it never overlaps the right-side controls.
        self.toolbar_left = WrapFrame(toolbar, gap=4)
        self.toolbar_left.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.opt_selected_btn = ttk.Button(
            self.toolbar_left, text="Optimize Selected", style="Accent.TButton",
            command=self._optimize_selected)
        self.toolbar_left.add(self.opt_selected_btn)
        ToolTip(self.opt_selected_btn, "Run the full pipeline on the checked items.\n"
                "Enable ⚡ Force options to re-process everything regardless "
                "of state.")
        # Force: master pill + per-feature menu.
        force_box = ttk.Frame(self.toolbar_left)
        self.toolbar_left.add(force_box)
        self.force_flac_var = tk.BooleanVar(
            value=self.config.get("force_flac_ui", False))
        self.force_images_var = tk.BooleanVar(
            value=self.config.get("force_images_ui", False))
        self.force_audit_var = tk.BooleanVar(
            value=self.config.get("force_audit_ui", False))
        self.force_dr_var = tk.BooleanVar(
            value=self.config.get("force_dr_ui", False))
        self.force_autotag_var = tk.BooleanVar(
            value=self.config.get("force_auto_tag_ui", False))
        self.force_lyrics_var = tk.BooleanVar(
            value=self.config.get("force_lyrics_ui", False))
        self.force_cue_var = tk.BooleanVar(
            value=self.config.get("force_cue_ui", False))
        self.force_var = tk.BooleanVar(
            value=(self.force_flac_var.get() and self.force_images_var.get()
                   and self.force_audit_var.get() and self.force_dr_var.get()
                   and self.force_autotag_var.get()
                   and self.force_lyrics_var.get()
                   and self.force_cue_var.get()))
        force_toggle = ToggleSwitch(
            force_box, self.force_var, bg=BG, command=self._on_force_master)
        force_toggle.pack(side=tk.LEFT)
        force_hint = ("Force: re-process everything regardless of state.\n"
                      "Use the ▾ menu to toggle each force option "
                      "individually.\nApplies to Optimize Selected, Run All "
                      "and Run Custom.")
        ToolTip(force_toggle, force_hint)
        ttk.Label(force_box, text="Force", style="Muted.TLabel").pack(
            side=tk.LEFT, padx=(8, 2))
        force_menu_btn = ttk.Button(force_box, text="▾", style="Small.TButton",
                                    width=2, command=self._show_force_menu)
        force_menu_btn.pack(side=tk.LEFT)
        ToolTip(force_menu_btn, "Configure individual force options.")
        self.refresh_btn = ttk.Button(
            self.toolbar_left, text="Refresh", style="Small.TButton",
            command=lambda: self._refresh_library(regrade=True))
        self.toolbar_left.add(self.refresh_btn)
        self.clear_sel_btn = ttk.Button(
            self.toolbar_left, text="Clear Sel", style="Small.TButton",
            command=self._clear_selection)
        self.toolbar_left.add(self.clear_sel_btn)
        self.select_all_btn = ttk.Button(
            self.toolbar_left, text="Select All", style="Small.TButton",
            command=self._select_all)
        self.toolbar_left.add(self.select_all_btn)

        self.sel_label_var = tk.StringVar(value="0 selected")
        sel_label = ttk.Label(self.toolbar_left, textvariable=self.sel_label_var,
                              style="Muted.TLabel")
        self.toolbar_left.add(sel_label)

        # External tools: enqueue the checked folders in foobar2000, or
        # open them in Mp3tag / Picard.
        self.foobar_btn = ttk.Button(
            toolbar_right, text="Enqueue", style="Small.TButton",
            command=lambda: self._open_in_external("foobar2000"))
        self.foobar_btn.pack(side=tk.RIGHT)
        ToolTip(self.foobar_btn, "Enqueue the selected folder(s) in "
                                 "foobar2000 (/add).")
        self.mp3tag_btn = ttk.Button(toolbar_right, text="Mp3tag",
                                     style="Small.TButton",
                                     command=lambda: self._open_in_external("mp3tag"))
        self.mp3tag_btn.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.mp3tag_btn, "Open the selected folder(s) in Mp3tag.")
        self.picard_btn = ttk.Button(toolbar_right, text="Picard",
                                     style="Small.TButton",
                                     command=lambda: self._open_in_external("picard"))
        self.picard_btn.pack(side=tk.RIGHT, padx=(0, 8))
        ToolTip(self.picard_btn, "Open the selected folder(s) in MusicBrainz "
                                 "Picard.")

        self.compact_var = tk.BooleanVar(value=self.config.get("compact_ui", False))
        compact_toggle = tk.Checkbutton(
            toolbar_right, text="Compact grades", variable=self.compact_var,
            command=self._on_compact_toggle,
            background=BG, foreground=TEXT, selectcolor=BG,
            activebackground=BG, activeforeground=TEXT,
            highlightthickness=0, bd=0, font=_font(9),
        )
        compact_toggle.pack(side=tk.RIGHT, padx=(0, 14))

        # Filter row
        filter_frame = ttk.Frame(library_frame, style="Card.TFrame",
                                 padding=(12, 8))
        filter_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        filter_frame.columnconfigure(1, weight=1)
        ttk.Label(filter_frame, text="Album Artist:", style="Card.TLabel").grid(
            row=0, column=0, sticky="w", padx=(0, 8))
        self.albumartist_var = tk.StringVar(value="")
        self.albumartist_entry = ttk.Entry(filter_frame,
                                           textvariable=self.albumartist_var)
        self.albumartist_entry.grid(row=0, column=1, sticky="ew")
        self.albumartist_entry.bind("<KeyRelease>", self._on_albumartist_change)
        ttk.Button(filter_frame, text="Clear", style="Small.TButton",
                   command=self._clear_filter).grid(row=0, column=2, padx=(8, 0))

        self.bad_only_var = tk.BooleanVar(value=False)
        bad_box = ttk.Frame(filter_frame, style="Card.TFrame")
        bad_box.grid(row=0, column=3, sticky="e", padx=(14, 0))
        bad_toggle = ToggleSwitch(bad_box, self.bad_only_var, bg=CARD,
                                  command=self._on_filter_change)
        bad_toggle.pack(side=tk.LEFT)
        ToolTip(bad_toggle, "Hide passing albums — show only failed / ungraded ones.")
        ttk.Label(bad_box, text="Bad only",
                  style="Card.TLabel").pack(side=tk.LEFT, padx=(8, 0))

        self.show_files_var = tk.BooleanVar(
            value=self.config.get("show_sidecar_files", False))
        files_box = ttk.Frame(filter_frame, style="Card.TFrame")
        files_box.grid(row=0, column=4, sticky="e", padx=(14, 0))
        files_toggle = ToggleSwitch(files_box, self.show_files_var, bg=CARD,
                                    command=self._on_show_files_toggle)
        files_toggle.pack(side=tk.LEFT)
        ToolTip(files_toggle, "Show non-audio files (.cue/.log/.lrc/.jxl/"
                              ".jpg/.png) with their own grades.")
        ttk.Label(files_box, text="Show files",
                  style="Card.TLabel").pack(side=tk.LEFT, padx=(8, 0))

        self.sort_var = tk.StringVar()
        self._sort_labels = {
            "name": "Name (A–Z)",
            "grade_bad": "Grade — worst first",
            "grade_good": "Grade — best first",
        }
        self._sort_rev = {v: k for k, v in self._sort_labels.items()}
        sort_key = self.config.get("library_sort", "name")
        if sort_key not in self._sort_labels:
            sort_key = "name"
        self.sort_var.set(self._sort_labels[sort_key])
        sort_box = ttk.Combobox(
            filter_frame, state="readonly", width=22, textvariable=self.sort_var,
            values=list(self._sort_labels.values()),
        )
        sort_box.grid(row=0, column=4, sticky="e", padx=(14, 0))
        sort_box.bind("<<ComboboxSelected>>", self._on_sort_change)

        # Directory tree + grades inside a bordered card
        tree_card = tk.Frame(library_frame, background=BORDER,
                             highlightthickness=1, highlightbackground=BORDER)
        tree_card.grid(row=3, column=0, sticky="nswe")
        tree_card.rowconfigure(0, weight=1)
        tree_card.columnconfigure(0, weight=1)

        tree_box = ttk.Frame(tree_card, style="Card.TFrame")
        tree_box.grid(row=0, column=0, sticky="nswe")
        tree_box.rowconfigure(0, weight=1)
        tree_box.columnconfigure(0, weight=1)

        self.library_tree = ttk.Treeview(
            tree_box, show="tree headings", selectmode="none"
        )
        self.library_tree.configure(columns=tuple(TREE_COLUMNS))
        for col_id, (heading, width, _default) in TREE_COLUMNS.items():
            self.library_tree.heading(col_id, text=heading)
            self.library_tree.column(col_id, width=width, anchor="w",
                                     stretch=False)

        # Row states: green = graded pass, purple = audited only,
        # blue = graded + audited, yellow = warnings/mixed, red = failing.
        self.library_tree.tag_configure(
            "pass", background="#132018", foreground="#a8dc8c")
        self.library_tree.tag_configure(
            "audited", background="#221532", foreground="#c9a2f2")
        self.library_tree.tag_configure(
            "both", background="#101f38", foreground="#93b8e8")
        self.library_tree.tag_configure(
            "mixed", background="#211f14", foreground="#e3cf95")
        self.library_tree.tag_configure(
            "fail", background="#241417", foreground="#e58a93")
        self.library_tree.tag_configure("pending", background="#141414")

        # Restore persisted column visibility (right-click a column
        # heading to toggle; the choice is saved to config.json).
        self._col_visible = dict(
            (c, default) for c, (_h, _w, default) in TREE_COLUMNS.items())
        saved_cols = self.config.get("library_columns") or {}
        for c in self._col_visible:
            self._col_visible[c] = bool(saved_cols.get(c, self._col_visible[c]))
        self._apply_column_visibility()

        v_scroll = ttk.Scrollbar(tree_box, orient=tk.VERTICAL,
                                 command=self.library_tree.yview)
        h_scroll = ttk.Scrollbar(tree_box, orient=tk.HORIZONTAL,
                                 command=self.library_tree.xview)
        self.library_tree.configure(yscrollcommand=v_scroll.set,
                                    xscrollcommand=h_scroll.set)
        self.library_tree.grid(row=0, column=0, sticky="nswe")
        v_scroll.grid(row=0, column=1, sticky="ns")
        h_scroll.grid(row=1, column=0, sticky="ew")

        self.library_tree.bind("<Button-1>", self._on_tree_click)
        self.library_tree.bind("<Double-1>", self._on_tree_double)
        self.library_tree.bind("<Button-3>", self._on_tree_menu)
        self.library_tree.bind("<Control-a>", self._select_all)
        self.library_tree.bind("<Control-A>", self._select_all)
        self.bind("<Control-a>", self._select_all_global)
        self.bind("<Control-A>", self._select_all_global)
        self._last_anchor = None
        ToolTip(self.library_tree, "Ctrl+A select all · Ctrl+click toggle · Shift+click range")

        # Library model state
        self._lib_folder = self.folder_var.get().strip()
        self._lyrics_format = str(
            self.config.get("lyrics_format", "EMBEDDED")
        ).upper()
        self._artists = {}
        self._folder_artist = {}
        self._grade_cache = {}
        self._checked = {}
        self._folder_state = {}
        self._item_paths = {}
        self._item_base = {}
        self._path_items = {}
        self._agg = {}
        self._root_item = None
        self._scan_q = queue.Queue()
        self._scan_generation = 0
        self._scan_pending = False
        self._library_busy = False
        self._filter_job = None
        self._scan_draining = False

        # Populate library initially
        self._refresh_library()

        # --- Console tab ---------------------------------------------------
        console_tab = ttk.Frame(notebook, padding=(16, 12))
        console_tab.columnconfigure(0, weight=1)
        console_tab.rowconfigure(0, weight=1)
        notebook.add(console_tab, text="Console")

        # Keep the window size stable when switching tabs (the tab buttons
        # already share identical padding via the style, so they never resize).
        notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        # Determine compact mode
        compact = self.compact_var.get()

        # Adjust padding based on compact mode
        panel_inner_pad = (8, 4, 8, 8) if compact else (14, 10, 14, 12)
        button_pad = (4, 6) if compact else (6, 12)
        label_font = _font(8) if compact else _font(9)
        text_font = (self._monospace, 8) if compact else (self._monospace, 10)

        # Recreate the console inside the tab (same as before but in a tab)
        console_panel = ttk.Frame(console_tab, padding=panel_inner_pad)
        console_panel.grid(row=0, column=0, sticky="nswe")
        console_panel.rowconfigure(1, weight=1)
        console_panel.columnconfigure(0, weight=1)

        bar = ttk.Frame(console_panel)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6 if compact else 8))
        ttk.Label(bar, text="CONSOLE", style="Section.TLabel").pack(side=tk.LEFT)

        self.autoscroll_var = tk.BooleanVar(value=True)
        auto = ttk.Frame(bar)
        auto.pack(side=tk.RIGHT)
        ToggleSwitch(auto, self.autoscroll_var, bg=BG).pack(side=tk.LEFT)
        ttk.Label(auto, text="Auto-scroll", style="Muted.TLabel",
                  font=label_font).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(bar, text="Clear", style="Small.TButton",
                   command=self._clear_console).pack(side=tk.RIGHT, padx=button_pad)
        ttk.Button(bar, text="Copy All", style="Small.TButton",
                   command=self._copy_console).pack(side=tk.RIGHT, padx=button_pad)

        console_card = tk.Frame(console_panel, background=BORDER,
                                highlightthickness=1,
                                highlightbackground=BORDER)
        console_card.grid(row=1, column=0, sticky="nswe")
        console_card.rowconfigure(0, weight=1)
        console_card.columnconfigure(0, weight=1)

        console_box = ttk.Frame(console_card, style="Card.TFrame")
        console_box.grid(row=0, column=0, sticky="nswe")
        console_box.rowconfigure(0, weight=1)
        console_box.columnconfigure(0, weight=1)

        self.console = tk.Text(
            console_box, wrap="none", state=tk.DISABLED,
            background="#111111", foreground=TEXT, borderwidth=0,
            insertbackground=TEXT, highlightthickness=0, padx=12, pady=10,
            font=text_font, undo=False,
        )
        ysb = ttk.Scrollbar(console_box, orient=tk.VERTICAL, command=self.console.yview)
        xsb = ttk.Scrollbar(console_box, orient=tk.HORIZONTAL, command=self.console.xview)
        self.console.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        self.console.grid(row=0, column=0, sticky="nswe")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        self._console_bold_font = tkfont.Font(
            family=self._monospace, size=10, weight="bold")
        tag_colors = {
            "fg": TEXT, "bold": BRIGHT, "grey": MUTED, "red": RED,
            "green": GREEN, "yellow": YELLOW, "blue": "#d6d6d6",
            "magenta": "#c9c9c9", "cyan": "#a6a6a6",
        }
        for tag, color in tag_colors.items():
            if tag == "bold":
                self.console.tag_configure(tag, foreground=color,
                                           font=self._console_bold_font)
            else:
                self.console.tag_configure(tag, foreground=color)
        for tag in ("muted",):
            self.console.tag_configure(tag, foreground=MUTED)

        menu = tk.Menu(self.console, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        menu.add_command(label="Copy", command=lambda: self.console.event_generate("<<Copy>>"))
        menu.add_command(label="Select All", command=lambda: self.console.tag_add("sel", "1.0", "end"))
        menu.add_separator()
        menu.add_command(label="Clear", command=self._clear_console)
        self.console.bind("<Button-3>", lambda e: menu.tk_popup(e.x_root, e.y_root))

        # --- Status bar --------------------------------------------------------
        ttk.Separator(self).pack(fill=tk.X, side=tk.BOTTOM)
        status = ttk.Frame(self, style="Panel.TFrame", padding=(16, 8))
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.columnconfigure(1, weight=1)

        self.status_var = tk.StringVar(value="Ready")
        left = ttk.Frame(status, style="Panel.TFrame")
        left.grid(row=0, column=0, sticky="w")
        ttk.Button(left, text="\u2699  Settings", style="Small.TButton",
                   command=self._open_config).pack(side=tk.LEFT)
        ttk.Button(left, text="\u2726  Guide", style="Small.TButton",
                   command=self._show_setup_guide).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(left, text="\u24d8  About", style="Small.TButton",
                   command=self._show_about).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(status, textvariable=self.status_var,
                  style="Panel.TLabel").grid(row=0, column=1, sticky="w",
                                             padx=(12, 0))
        right = ttk.Frame(status, style="Panel.TFrame")
        right.grid(row=0, column=2, sticky="e")
        self.continue_btn = ttk.Button(
            right, text="Continue ▶", style="Accent.TButton",
            command=self._continue
        )
        self.prog_label_var = tk.StringVar(value="")
        ttk.Label(right, textvariable=self.prog_label_var,
                  style="Muted.Panel.TLabel").pack(side=tk.LEFT, padx=(0, 10))
        self.progress = ttk.Progressbar(right, mode="determinate", length=240)
        self.progress.pack(side=tk.LEFT)

    # ------------------------------------------------------------------
    # Console plumbing
    # ------------------------------------------------------------------
    def log(self, msg, tag=None):
        self.log_q.put(("out", [(msg.rstrip("\n"), tag or "fg")]))

    def _clear_console(self):
        self.console.configure(state=tk.NORMAL)
        self.console.delete("1.0", tk.END)
        self.console.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Library view
    # ------------------------------------------------------------------
    _CHECK_GLYPH = {0: "\u2610", 1: "\u25d0", 2: "\u2611"}  # ☐ ◐ ☑

    def _item_state(self, item):
        """0 = unchecked, 1 = some descendants checked, 2 = fully checked."""
        if self.library_tree.get_children(item):
            return self._folder_state.get(item, 0)
        path = self._item_paths.get(item)
        return 2 if self._checked.get(path, False) else 0

    def _set_row_text(self, item):
        """Re-render a row's checkbox glyph from its current state."""
        base = self._item_base.get(item)
        if base is None:
            return
        glyph = self._CHECK_GLYPH.get(self._item_state(item), "\u2610")
        self.library_tree.item(item, text=glyph + " " + base)

    def _branch_items(self, item):
        """[item] + all descendants in display order (parents first)."""
        out = []

        def walk(i):
            out.append(i)
            for c in self.library_tree.get_children(i):
                walk(c)

        walk(item)
        return out

    def _recompute_folder_state(self, item):
        """Derive a folder's check state from its immediate children.

        A folder reads as fully checked (2) only when every child is
        checked; unchecked (0) when none are; otherwise partial (1).
        Returns the new state and mirrors it into ``_checked[path]``.
        """
        children = self.library_tree.get_children(item)
        if not children:
            return 0
        checked = sum(1 for c in children if self._item_state(c))
        total = len(children)
        if checked == total:
            st = 2
        elif checked:
            st = 1
        else:
            st = 0
        self._folder_state[item] = st
        path = self._item_paths.get(item)
        if path is not None:
            self._checked[path] = (st == 2)
        return st

    def _refresh_ancestors(self, item):
        """Recompute folder states upward from ``item`` and re-render them,
        stopping as soon as a folder's state stops changing."""
        parent = self.library_tree.parent(item)
        while parent:
            old = self._folder_state.get(parent)
            new = self._recompute_folder_state(parent)
            self._set_row_text(parent)
            if old is not None and old == new:
                return
            parent = self.library_tree.parent(parent)

    def _set_branch(self, item, state):
        """Check (state=True) or uncheck (state=False) every path under a
        folder, then recompute and re-render the whole branch."""
        def walk(i):
            path = self._item_paths.get(i)
            if path is not None:
                self._checked[path] = bool(state)
            for c in self.library_tree.get_children(i):
                walk(c)

        walk(item)
        for i in reversed(self._branch_items(item)):
            if self.library_tree.get_children(i):
                self._recompute_folder_state(i)
            self._set_row_text(i)

    def _reconcile_all(self):
        """Bottom-up recompute of every folder state + re-render all rows."""
        self._folder_state = {}
        order = self._tree_items_in_order()
        for item in reversed(order):
            if self.library_tree.get_children(item):
                self._recompute_folder_state(item)
        for item in order:
            self._set_row_text(item)

    def _refresh_library(self, regrade=False):
        """Start a background scan + grade of the library folder."""
        if getattr(self, "_library_busy", False):
            self._scan_pending = self._scan_pending or regrade
            return
        folder = self.folder_var.get().strip()
        self._lib_folder = folder
        self._lyrics_format = str(
            self.config.get("lyrics_format", "EMBEDDED")
        ).upper()
        if regrade:
            self._grade_cache.clear()
        if not folder or not os.path.isdir(folder):
            self._artists = {}
            self._folder_artist = {}
            self._root_albums = []
            self._rebuild_tree()
            return
        self._scan_generation += 1
        generation = self._scan_generation
        self._scan_q = queue.Queue()
        self._library_busy = True
        self._set_job_busy("library scan", True)
        if hasattr(self, "status_var"):
            self.status_var.set("Scanning library…")
        threading.Thread(
            target=self._library_worker,
            args=(regrade, generation, self._scan_q, folder, self._lyrics_format),
            daemon=True,
            name="mlo-library-scan",
        ).start()
        # One persistent drain loop serves every scan and the one-shot
        # background re-grades; start it only once.
        if not self._scan_draining:
            self._scan_draining = True
            self._drain_library()

    def _library_worker(self, regrade, generation, q, folder, lyrics_format):
        # Capture the queue object: if the user starts a new scan, this
        # worker keeps filling the (abandoned) old queue instead of
        # mixing stale results into the new one.
        try:
            from mlo.stats import _find_albums
            from mlo.grader import _grade_album

            albums = _find_albums(folder)
            artists = {}
            root_albums = []

            for album_dir in albums:
                parent = os.path.dirname(album_dir)
                if parent == folder:
                    root_albums.append(album_dir)
                else:
                    artists.setdefault(parent, []).append(album_dir)

            q.put(("data", artists, root_albums))

            todo = [a for albs in artists.values() for a in albs]
            todo.extend(root_albums)
            if not regrade:
                todo = [a for a in todo if a not in self._grade_cache]

            from concurrent.futures import ThreadPoolExecutor, as_completed

            def grade_one(album_dir):
                try:
                    return album_dir, _grade_album(
                        album_dir, lyrics_format, self.config)
                except Exception:
                    return album_dir, None

            workers = max(2, min(8, (os.cpu_count() or 2)))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(grade_one, a) for a in todo]
                # as_completed (not pool.map) so finished albums render
                # immediately instead of waiting on slower predecessors.
                for fut in as_completed(futures):
                    album_dir, result = fut.result()
                    if result is None:
                        result = {"error": True, "path": album_dir}
                    q.put(("grade", album_dir, result))
        except Exception:
            # Never let a scan failure kill the library view silently.
            try:
                traceback.print_exc(file=self.stdout_stream)
            except Exception:
                pass
        q.put(("done", generation))

    def _drain_library(self):
        try:
            while True:
                kind, *payload = self._scan_q.get_nowait()
                if kind == "data":
                    self._artists, self._root_albums = payload
                    self._rebuild_tree()
                elif kind == "grade":
                    album_dir, result = payload
                    # Grade results carry the album's artist tag; enrich
                    # the folder -> artist map used by the filter.
                    artist = (result or {}).get("album_artist")
                    if artist:
                        parent = os.path.dirname(album_dir)
                        if parent and parent not in self._folder_artist:
                            self._folder_artist[parent] = artist
                    self._update_grade(album_dir, result)
                elif kind == "done":
                    generation = payload[0]
                    if generation != self._scan_generation:
                        continue
                    self._library_busy = False
                    self._set_job_busy("library scan", False)
                    if hasattr(self, "status_var"):
                        self.status_var.set("Library scan complete")
                    if self._sort_mode() != "name" or self.bad_only_var.get():
                        self._rebuild_tree()
                    if self._scan_pending:
                        pending = self._scan_pending
                        self._scan_pending = False
                        self.after_idle(lambda p=pending: self._refresh_library(regrade=p))
        except queue.Empty:
            pass
        except Exception:
            # A single malformed message must not kill the drain loop.
            _stream = getattr(self, "stdout_stream", None)
            if _stream is not None:
                traceback.print_exc(file=_stream)
        self.after(120, self._drain_library)

    def _collect_open(self):
        """Return the set of paths of currently expanded tree items."""
        open_paths = set()
        stack = list(self.library_tree.get_children(""))
        while stack:
            item = stack.pop()
            if item in self._item_paths and self.library_tree.item(item, "open"):
                open_paths.add(self._item_paths[item])
            stack.extend(self.library_tree.get_children(item))
        return open_paths

    def _rebuild_tree(self):
        """Build the library tree from cached scan + grade data."""
        tree = self.library_tree
        open_paths = self._collect_open()
        scroll_frac = tree.yview()[0] if tree.get_children("") else 0.0
        for item in tree.get_children():
            tree.delete(item)
        self._item_paths = {}
        self._item_base = {}
        self._path_items = {}
        self._agg = {}
        self._agg_total = {}
        self._root_item = None

        compact = self.compact_var.get()
        tree.configure(show="tree" if compact else "tree headings")

        folder = self._lib_folder or self.folder_var.get().strip()
        if not folder or not os.path.isdir(folder):
            tree.insert("", "end",
                        text="No library folder set — use Browse to pick one")
            return

        filter_text = self.albumartist_var.get().strip().lower()
        artists = getattr(self, "_artists", {})
        root_albums = getattr(self, "_root_albums", [])
        folder_artist = getattr(self, "_folder_artist", {})

        root_text = f"All Folders ({os.path.basename(folder)})"
        self._root_item = tree.insert("", "end", text="", open=True)
        self._item_paths[self._root_item] = folder
        self._item_base[self._root_item] = root_text
        self._agg[self._root_item] = [0, 0, 0, 0, 0, set(), 0,
                                      set(), set(), set(), set(), 0, 0,
                                      set()]
        self._agg_total[self._root_item] = 0

        shown_any = False
        for parent_dir, album_dirs in sorted(
                artists.items(), key=lambda kv: self._artist_sort_key(kv[0])):
            artist_name = os.path.basename(parent_dir) or parent_dir
            tag_artist = folder_artist.get(parent_dir, "")
            if filter_text and filter_text not in artist_name.lower() \
                    and filter_text not in tag_artist.lower():
                continue
            visible = [d for d in album_dirs if self._album_visible(d)]
            if self.bad_only_var.get() and not visible:
                continue
            shown_any = True
            artist_item = tree.insert(self._root_item, "end", text="",
                                      open=False)
            self._item_paths[artist_item] = parent_dir
            self._item_base[artist_item] = artist_name
            self._agg[artist_item] = [0, 0, 0, 0, 0, set(), 0,
                                      set(), set(), set(), set(), 0, 0,
                                      set()]
            count_for_total = len(visible) if self.bad_only_var.get() else len(album_dirs)
            self._agg_total[artist_item] = count_for_total
            self._agg_total[self._root_item] += count_for_total
            for album_dir in sorted(visible, key=self._album_sort_key):
                self._insert_album(tree, artist_item, album_dir)

        root_visible = [d for d in root_albums if self._album_visible(d)]
        for album_dir in sorted(root_visible, key=self._album_sort_key):
            shown_any = True
            self._insert_album(tree, self._root_item, album_dir)
            self._agg_total[self._root_item] += 1

        self._item_base[self._root_item] = (
            root_text + f" — {len(self._grade_cache)} graded")
        self._set_row_text(self._root_item)

        for item_id, path in self._item_paths.items():
            if path in open_paths:
                tree.item(item_id, open=True)

        # Re-accumulate aggregates for albums already in the cache
        for item_id, path in self._item_paths.items():
            res = self._grade_cache.get(path)
            if res is None:
                continue
            parent = tree.parent(item_id)
            if parent:
                self._add_agg(parent, res)
                grand = tree.parent(parent)
                if grand:
                    self._add_agg(grand, res)

        self._apply_agg(self._root_item)
        for child in tree.get_children(self._root_item):
            self._apply_agg(child)
        self._reconcile_all()

        if filter_text and not shown_any:
            tree.insert("", "end", text="No albums match the filter")
        self._update_selection_label()
        if scroll_frac:
            tree.after_idle(lambda f=scroll_frac: tree.yview_moveto(f))

    def _album_visible(self, album_dir):
        """Bad-only filter: hide graded albums that passed."""
        if not self.bad_only_var.get():
            return True
        res = self._grade_cache.get(album_dir)
        if not res or "error" in res:
            return True
        return res["pass_count"] != res["total_checks"]

    def _insert_album(self, tree, parent_item, album_dir):
        base = os.path.basename(album_dir)
        item = tree.insert(parent_item, "end",
                           text="",
                           open=False, tags=("pending",))
        self._item_paths[item] = album_dir
        self._item_base[item] = base
        self._path_items.setdefault(album_dir, set()).add(item)
        self._set_row_text(item)
        res = self._grade_cache.get(album_dir)
        if res is None:
            tree.item(item, values=("…", "…", "", "", "", "", ""))
        else:
            self._apply_album_grade(tree, item, album_dir, res)
        return item

    # ------------------------------------------------------------------
    # Row states: green = graded pass, purple = audited only,
    # blue = graded + audited, yellow = warnings / mixed, red = failing.
    # ------------------------------------------------------------------
    AUDIT_BAD = ("FAKE",)
    AUDIT_WARN = ("MIX", "WARN", "UNKNOWN")

    @classmethod
    def _row_state(cls, grade_ok, audit):
        """Pick the tree row tag from (grade passed?, audit verdict).

        grade_ok: True = all checks pass, False = failing, None = partial
        (aggregates) - full albums/tracks always pass a real boolean.
        audit:   REAL / FAKE / Mix (compared case-insensitively).
        """
        audit = str(audit).upper() if audit else None
        if audit in cls.AUDIT_BAD:
            return "fail"
        if audit == "REAL":
            return "both" if grade_ok else "audited"
        if audit in cls.AUDIT_WARN:
            return "mixed" if grade_ok else "fail"
        if grade_ok is None:
            return "mixed"
        return "pass" if grade_ok else "fail"

    def _fmt_tag_val(self, v, max_len=10):
        s = str(v).strip() if v is not None else ""
        if not s or s == "INCONSISTENT":
            return "—"
        return s[:max_len]

    def _fmt_vals(self, vals, max_n=3, max_len=10):
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
        """TAGS layout: G A I L AA (matches the column-heading key)."""
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
        """TAGS layout: G A I L AA (matches the column-heading key)."""
        av = res.get("album_values") or {}
        tracks = res.get("tracks") or []
        lyr = sum(
            1 for tr in tracks
            if tr.get("lyrics_embedded") or tr.get("lyrics_lrc")
        )
        tot = res.get("track_count") or 0
        return (
            f"G:{self._sum_key(res, 'GENRE')} "
            f"A:{self._sum_key(res, 'ITUNESADVISORY')} "
            f"I:{self._sum_key(res, 'INSTRUMENTAL')} "
            f"L:{lyr}/{tot} "
            f"AA:{self._fmt_tag_val(av.get('ALBUMITUNESADVISORY'), 8)}"
        )

    def _apply_album_grade(self, tree, item, album_dir, res):
        if "error" in res:
            tree.item(item, values=("ERR", "ERR", "", "", "", "", ""),
                      tags=("fail",))
            return
        ok = res["pass_count"] == res["total_checks"]
        audit = res.get("audit_summary")
        aa_value = (res.get("album_values") or {}).get("ALBUMITUNESADVISORY")
        tree.item(item, values=(
            "PASS" if ok else "FAIL",
            audit or "—",
            f"{res['pass_count']}/{res['total_checks']}",
            res["track_count"],
            res["media"],
            res["cover_file"] or "MISSING",
            self._album_tags_txt(res),
        ), tags=(self._row_state(ok, audit),))
        if not self.compact_var.get():
            for child in tree.get_children(item):
                # Drop the row from the path maps so stale item ids (Tk
                # never reuses them) don't accumulate across re-grades.
                p = self._item_paths.pop(child, None)
                if p is not None:
                    s = self._path_items.get(p)
                    if s is not None:
                        s.discard(child)
                        if not s:
                            del self._path_items[p]
                self._item_base.pop(child, None)
                tree.delete(child)
            for tr in res["tracks"]:
                self._insert_track(tree, item, album_dir, tr, aa_value)
            if self.config.get("show_sidecar_files", False):
                for sc in res.get("sidecars") or []:
                    self._insert_sidecar(tree, item, album_dir, sc)
            # Track rows changed -> recompute this album's check state and
            # propagate it up the tree.
            self._recompute_folder_state(item)
            self._set_row_text(item)
            self._refresh_ancestors(item)

    def _insert_sidecar(self, tree, album_item, album_dir, sc):
        """Insert a non-audio file row (.cue/.log/.lrc/image) under an album."""
        path = os.path.join(album_dir, sc["file"])
        item = tree.insert(album_item, "end", text="", open=False,
                           tags=("pass" if sc.get("ok") else "fail",))
        self._item_paths[item] = path
        self._item_base[item] = sc["file"]
        self._path_items.setdefault(path, set()).add(item)
        self._set_row_text(item)
        tree.item(item, values=(
            "OK" if sc.get("ok") else "FAIL",
            "—",
            sc.get("detail", ""),
            "—",
            sc.get("type", ""),
            "—",
            "—",
        ))

    def _insert_track(self, tree, album_item, album_dir, tr, aa_value=None):
        path = os.path.join(album_dir, tr["file"])
        issues = tr.get("issues") or []
        ok = not issues and not tr.get("unreadable")
        audit = tr.get("audit")
        base = tr["file"]
        item = tree.insert(album_item, "end",
                           text="",
                           open=False,
                           tags=(self._row_state(ok, audit),))
        self._item_paths[item] = path
        self._item_base[item] = base
        self._path_items.setdefault(path, set()).add(item)
        self._set_row_text(item)
        tree.item(item, values=(
            "OK" if ok else "FAIL",
            audit or "—",
            str(len(issues)) if issues else "",
            "—",
            tr["values"].get("MEDIA") or "",
            "—",
            self._track_tags_txt(tr, aa_value),
        ))

    def _update_grade(self, album_dir, result):
        was_cached = album_dir in self._grade_cache
        self._grade_cache[album_dir] = result
        tree = self.library_tree
        items = self._path_items.get(album_dir)
        item = next(iter(items), None) if items else None
        if item is None:
            return
        self._apply_album_grade(tree, item, album_dir, result)
        if not was_cached:
            parent = tree.parent(item)
            if parent:
                self._add_agg(parent, result)
                grand = tree.parent(parent)
                if grand:
                    self._add_agg(grand, result)

    def _add_agg(self, item, res):
        agg = self._agg.get(item)
        if agg is None:
            return
        agg[0] += 1
        if "error" not in res:
            agg[1] += 1 if res["pass_count"] == res["total_checks"] else 0
            agg[2] += res["total_checks"]
            agg[3] += res["pass_count"]
            agg[4] += res["track_count"]
            if res.get("media"):
                agg[5].add(str(res["media"]))
            agg[6] += 1 if res.get("cover_file") else 0
            av = res.get("album_values") or {}
            aa = av.get("ALBUMITUNESADVISORY")
            if aa is not None and str(aa).strip():
                agg[7].add(str(aa).strip())
            for tr in res.get("tracks") or []:
                v = tr.get("values") or {}
                for idx, key in ((8, "ITUNESADVISORY"), (9, "GENRE"),
                                 (10, "INSTRUMENTAL")):
                    val = v.get(key)
                    if val is not None and str(val).strip():
                        agg[idx].add(str(val).strip())
                if tr.get("lyrics_embedded") or tr.get("lyrics_lrc"):
                    agg[11] += 1
            agg[12] += res.get("track_count") or 0
            if res.get("audit_summary"):
                agg[13].add(str(res["audit_summary"]))
        self._apply_agg(item)

    def _apply_agg(self, item):
        agg = self._agg.get(item)
        if agg is None:
            return
        (albums, passed, checks, pass_checks, tracks, media_set, covers,
         aa_set, ta_set, genre_set, inst_set, lyrics, track_total,
         audit_set) = agg
        grade_txt = f"{passed}/{albums}" if albums else "—"
        from mlo.grader import summarize_audits
        audit_txt = summarize_audits(audit_set) or "—"
        checks_txt = f"{pass_checks}/{checks}" if checks else "—"
        media_txt = "Mixed" if len(media_set) > 1 \
            else (next(iter(media_set), "") or "—")
        cover_txt = f"{covers}/{albums}" if albums else "—"
        tags_txt = (
            f"G:{self._fmt_vals(genre_set)} "
            f"A:{self._fmt_vals(ta_set)} "
            f"I:{self._fmt_vals(inst_set)} "
            f"L:{lyrics}/{track_total} "
            f"AA:{self._fmt_vals(aa_set)}"
        ) if albums else ""
        self.library_tree.item(item, values=(
            grade_txt, audit_txt, checks_txt, tracks or "—", media_txt,
            cover_txt, tags_txt))
        expected = self._agg_total.get(item, albums)
        if albums and albums >= expected:
            if passed == albums:
                grade_ok = True
            elif passed == 0:
                grade_ok = False
            else:
                grade_ok = None  # partially passing -> mixed at best
            self.library_tree.item(
                item, tags=(self._row_state(grade_ok, audit_txt),))

    def _on_tree_click(self, event):
        item = self.library_tree.identify_row(event.y)
        if not item:
            return
        if self.library_tree.identify_region(event.x, event.y) not in ("tree", "cell"):
            return
        bbox = self.library_tree.bbox(item, column="#0")
        if bbox and event.x < bbox[0] - 8:
            self.library_tree.item(
                item, open=not bool(self.library_tree.item(item, "open"))
            )
            return
        if event.state & 0x0001:  # Shift held -> range select
            self._select_range(item)
        else:
            # Plain click or Ctrl+click toggles the single item and
            # becomes the anchor for a later Shift+click range.
            self._toggle_item(item)
            self._last_anchor = item

    def _on_tree_double(self, event):
        item = self.library_tree.identify_row(event.y)
        if item:
            self.library_tree.item(
                item, open=not bool(self.library_tree.item(item, "open"))
            )

    def _tree_items_in_order(self):
        """Flattened list of tree items in display order."""
        items = []

        def walk(parent):
            for child in self.library_tree.get_children(parent):
                items.append(child)
                walk(child)

        walk("")
        return items

    def _select_range(self, target):
        """Shift+click: check every item between the anchor and target."""
        items = self._tree_items_in_order()
        anchor = getattr(self, "_last_anchor", None) or target
        try:
            lo, hi = sorted((items.index(anchor), items.index(target)))
        except ValueError:
            lo = hi = len(items) - 1
        for iid in items[lo:hi + 1]:
            path = self._item_paths.get(iid)
            if path:
                self._checked[path] = True
        if self._root_item is not None:
            self._reconcile_all()
        self._update_selection_label()
        self._last_anchor = target

    def _toggle_item(self, item):
        """Toggle one row. Folders flip every descendant; leaves toggle
        themselves, and checked state cascades up to parent folders."""
        path = self._item_paths.get(item)
        if not path:
            return
        if self.library_tree.get_children(item):
            # Folder: clicking a partial/checked folder unchecks it and its
            # descendants; clicking an unchecked folder checks them all.
            state = 0 if self._item_state(item) in (1, 2) else 2
            self._set_branch(item, state == 2)
            self._refresh_ancestors(item)
        else:
            self._checked[path] = not self._checked.get(path, False)
            self._set_row_text(item)
            self._refresh_ancestors(item)
        self._update_selection_label()

    def _select_all(self, event=None):
        """Ctrl+A / Select All: check every row (except the root), then
        reconcile folder states so all folder boxes render as checked too."""
        self._checked.clear()
        for item_id, path in self._item_paths.items():
            if path and item_id != self._root_item:
                self._checked[path] = True
        if self._root_item is not None:
            self._reconcile_all()
        self._update_selection_label()
        return "break"

    def _select_all_global(self, event=None):
        """Ctrl+A bound on the app window; ignore when typing in an Entry."""
        w = self.focus_get()
        if w is not None and isinstance(w, (ttk.Entry, tk.Entry)):
            return None
        return self._select_all(event)

    def _update_selection_label(self):
        n = sum(1 for c in self._checked.values() if c)
        self.sel_label_var.set(f"{n} selected")
        if not self.running:
            self.opt_selected_btn.configure(
                state=tk.NORMAL if n else tk.DISABLED
            )

    def _clear_selection(self):
        self._checked.clear()
        if self._root_item is not None:
            self._reconcile_all()
        self._update_selection_label()

    def _clear_filter(self):
        self.albumartist_var.set("")
        self._rebuild_tree()

    def _optimize_selected(self):
        targets = [p for p, c in self._checked.items() if c]
        if not targets:
            return
        order = list(self.config.get("run_all_order", DEFAULT_RUN_ALL_ORDER))
        # Optimize Selected always finishes with an audio audit so the
        # AUDIT tags (and the viewer's audit column) stay current.
        if 6 not in order:
            order.append(6)
        self._run_scripts(
            order, f"OPTIMIZE SELECTED ({len(targets)} items)", targets=targets
        )

    def _on_compact_toggle(self):
        self.config["compact_ui"] = self.compact_var.get()
        save_config(self.config)
        self.library_tree.configure(
            show="tree" if self.compact_var.get() else "tree headings")
        self._refresh_console_compact()
        # Rebuild so existing album rows drop/regain their track children.
        self._rebuild_tree()

    def _on_tab_changed(self, event=None):
        """Switching Library/Console tabs must never resize the window.

        Belt-and-suspenders on top of pack_propagate(False): re-assert the
        current window size in case any geometry propagation tried to grow
        or shrink the window to fit the newly-selected tab's content. Never
        touch geometry while the window is maximized (it would un-maximize).
        """
        try:
            if self.state() == "zoomed":
                return
            geo = self.winfo_geometry()
            size = geo.split("+")[0]
            if size and size.count("x") == 1:
                self.geometry(size)
        except Exception:
            pass

    def _side_on_wheel(self, event):
        """Mouse-wheel scrolling over the sidebar."""
        try:
            self._side_canvas.yview_scroll(int(-event.delta / 120), "units")
        except Exception:
            pass

    def _toggle_sidebar(self, event=None):
        """Show / hide the sidebar; the notebook expands to fill the space."""
        vis = self.sidebar_visible.get()
        self.sidebar_visible.set(not vis)
        self.config["sidebar_visible"] = self.sidebar_visible.get()
        save_config(self.config)
        if self.sidebar_visible.get():
            self._sidebar.grid()
        else:
            self._sidebar.grid_remove()
        self.update_idletasks()
        return "break"

    def _sync_side_scrollbar(self):
        """Show the sidebar scrollbar only when its content overflows."""
        try:
            c = self._side_canvas
            bbox = c.bbox("all")
            if not bbox:
                return
            if c.winfo_height() < bbox[3]:
                self._side_scroll.grid()
            else:
                self._side_scroll.grid_remove()
        except Exception:
            pass

    def _on_force_master(self):
        """Master Force pill: on = every force option on, off = all off."""
        on = self.force_var.get()
        self.force_flac_var.set(on)
        self.force_images_var.set(on)
        self.force_audit_var.set(on)
        self.force_dr_var.set(on)
        self.force_autotag_var.set(on)
        self.force_lyrics_var.set(on)
        self.force_cue_var.set(on)
        self._save_force_config()

    def _on_force_option(self):
        """An individual force option changed: the master pill reflects
        whether all of them are on."""
        self.force_var.set(self.force_flac_var.get()
                           and self.force_images_var.get()
                           and self.force_audit_var.get()
                           and self.force_dr_var.get()
                           and self.force_autotag_var.get()
                           and self.force_lyrics_var.get()
                           and self.force_cue_var.get())
        self._save_force_config()

    def _save_force_config(self):
        self.config["force_ui"] = self.force_var.get()
        self.config["force_flac_ui"] = self.force_flac_var.get()
        self.config["force_images_ui"] = self.force_images_var.get()
        self.config["force_audit_ui"] = self.force_audit_var.get()
        self.config["force_dr_ui"] = self.force_dr_var.get()
        self.config["force_auto_tag_ui"] = self.force_autotag_var.get()
        self.config["force_lyrics_ui"] = self.force_lyrics_var.get()
        self.config["force_cue_ui"] = self.force_cue_var.get()
        save_config(self.config)

    def _show_force_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        menu.add_command(label="Force options", state=tk.DISABLED)
        menu.add_separator()
        for var, label in (
            (self.force_lyrics_var, "Format lyrics"),
            (self.force_cue_var, "Format CUE sheets"),
            (self.force_flac_var, "Re-encode FLACs"),
            (self.force_images_var, "Re-encode images"),
            (self.force_audit_var, "Audit"),
            (self.force_dr_var, "DR & ReplayGain"),
            (self.force_autotag_var, "Auto Tagging"),
        ):
            menu.add_checkbutton(label=label, variable=var, onvalue=True,
                                 offvalue=False,
                                 command=self._on_force_option)
        menu.add_separator()
        menu.add_command(label="All on",
                         command=lambda: (self.force_var.set(True),
                                          self._on_force_master()))
        menu.add_command(label="All off",
                         command=lambda: (self.force_var.set(False),
                                          self._on_force_master()))
        menu.tk_popup(self.winfo_pointerx(), self.winfo_pointery())
        try:
            menu.grab_release()
        except tk.TclError:
            pass

    def _on_albumartist_change(self, event=None):
        """Handle album artist filter text change (debounced: rebuilding
        the whole tree on every keystroke is far too costly)."""
        if self._filter_job is not None:
            try:
                self.after_cancel(self._filter_job)
            except Exception:
                pass
        self._filter_job = self.after(200, self._apply_filter)

    def _apply_filter(self):
        self._filter_job = None
        self._rebuild_tree()

    def _on_filter_change(self):
        """Bad-only toggle changed."""
        self._rebuild_tree()

    def _on_show_files_toggle(self):
        """'Show files' toggle: persist the setting and refresh the tree."""
        self.config["show_sidecar_files"] = self.show_files_var.get()
        save_config(self.config)
        self._rebuild_tree()

    def _on_sort_change(self, event=None):
        """Grade sort combobox changed."""
        key = self._sort_rev.get(self.sort_var.get(), "name")
        self.config["library_sort"] = key
        save_config(self.config)
        self._rebuild_tree()

    def _sort_mode(self):
        key = self._sort_rev.get(self.sort_var.get(), "name")
        return key if key in ("grade_bad", "grade_good") else "name"

    def _album_sort_key(self, d):
        """Sort key for an album dir: graded-first, then pass ratio, then name."""
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
        """Sort key for an artist folder: worst album ratio, then name."""
        albums = (getattr(self, "_artists", {}) or {}).get(parent_dir, [])
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
                frac = res["pass_count"] / max(1, res["total_checks"])
                worst = min(worst, frac)
        if not graded_any:
            return (1, 0.0, name)
        if mode == "grade_good":
            worst = -worst
        return (0, worst, name)

    def _refresh_console_compact(self):
        """Update console fonts when compact mode toggles."""
        compact = self.compact_var.get()
        try:
            self.console.configure(font=(self._monospace, 8 if compact else 10))
            self._console_bold_font.configure(size=8 if compact else 10)
        except tk.TclError:
            pass

    # ------------------------------------------------------------------
    # Grade details
    # ------------------------------------------------------------------
    def _find_album_for_item(self, item):
        """Return (album_dir, cached grade result) for an album or track row."""
        path = self._item_paths.get(item)
        if not path:
            return None, None
        res = self._grade_cache.get(path)
        if res is not None:
            return path, res
        parent = self.library_tree.parent(item)
        while parent:
            p = self._item_paths.get(parent)
            if p and p in self._grade_cache:
                return p, self._grade_cache[p]
            parent = self.library_tree.parent(parent)
        return None, None

    # ------------------------------------------------------------------
    # Column visibility (right-click any column heading)
    # ------------------------------------------------------------------
    def _apply_column_visibility(self):
        # Tk 8.6 has no per-column -display option; the widget-level
        # displaycolumns list is the supported way to hide columns.
        shown = [c for c in TREE_COLUMNS if self._col_visible.get(c, True)]
        try:
            self.library_tree.configure(displaycolumns=shown or ["#all"])
        except tk.TclError:
            self.library_tree.configure(displaycolumns="#all")

    def _toggle_column(self, col):
        self._col_visible[col] = not self._col_visible[col]
        self.config["library_columns"] = dict(self._col_visible)
        save_config(self.config)
        self._apply_column_visibility()

    def _show_column_menu(self, event):
        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        menu.add_command(label="Columns", state=tk.DISABLED)
        menu.add_separator()
        for col, (heading, _w, _d) in TREE_COLUMNS.items():
            var = tk.BooleanVar(value=self._col_visible.get(col, True))
            menu.add_checkbutton(
                label=heading.replace(" · G A I L AA", ""),
                variable=var, onvalue=True, offvalue=False,
                command=lambda c=col: self._toggle_column(c),
            )
        menu.add_separator()
        menu.add_command(label="TAGS key: G Genre · A Advisory · "
                               "I Instrumental · L Lyrics · AA Album Advisory",
                         state=tk.DISABLED)
        menu.tk_popup(event.x_root, event.y_root)
        try:
            menu.grab_release()
        except tk.TclError:
            pass

    def _on_tree_menu(self, event):
        """Right-click context menu on the library tree."""
        region = self.library_tree.identify_region(event.x, event.y)
        if region in ("heading", "separator"):
            self._show_column_menu(event)
            return
        item = self.library_tree.identify_row(event.y)
        if not item:
            return
        path = self._item_paths.get(item)
        album_dir, res = self._find_album_for_item(item)
        is_track = bool(path and os.path.isfile(path))
        edit_dir = album_dir or (path if path and os.path.isdir(path) else None)

        menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=TEXT,
                       activebackground=ACCENT_DARK, activeforeground="#ffffff")
        if res is not None:
            menu.add_command(label="Grade details…",
                             command=lambda: self._show_grade_details(item))
        if edit_dir:
            menu.add_command(
                label="Open selected tracks in Mp3tag",
                command=lambda: self._open_in_external(
                    "mp3tag", [path if is_track else edit_dir]))
        target_dir = path if (path and os.path.isdir(path)) else album_dir
        if target_dir:
            menu.add_separator()
            menu.add_command(
                label="Enqueue in foobar2000",
                command=lambda: self._open_in_external(
                    "foobar2000", [target_dir]))
            menu.add_command(
                label="Open in Picard",
                command=lambda: self._open_in_external("picard", [target_dir]))
            menu.add_command(
                label="Open in Explorer",
                command=lambda: self._open_in_explorer(target_dir))
        # Run any single script on the selected album / track.
        if album_dir:
            run_target = path if is_track else album_dir
            run_menu = tk.Menu(menu, tearoff=0, bg=PANEL, fg=TEXT,
                               activebackground=ACCENT_DARK,
                               activeforeground="#ffffff")
            for sid in sorted(SCRIPT_NAMES):
                run_menu.add_command(
                    label=SCRIPT_NAMES[sid],
                    command=lambda s=sid, t=run_target: self._run_scripts(
                        [s], f"{SCRIPT_NAMES[s]} — {os.path.basename(t)}",
                        targets=[t]))
            menu.add_cascade(label="Run Script…", menu=run_menu)
        if menu.index("end") is not None:
            menu.tk_popup(event.x_root, event.y_root)
        try:
            menu.grab_release()
        except tk.TclError:
            pass

    def _open_in_explorer(self, path):
        """Open the given folder (or a file's folder) in Windows Explorer."""
        try:
            d = path if os.path.isdir(path) else os.path.dirname(path)
            if os.path.isdir(d):
                subprocess.Popen(["explorer", os.path.normpath(d)],
                                 creationflags=0x08000000)
        except Exception as e:
            self.log(f"Could not open in Explorer: {e}", tag="red")

    # ------------------------------------------------------------------
    # External taggers (Mp3tag / MusicBrainz Picard)
    # ------------------------------------------------------------------
    def _selected_album_dirs(self):
        """Unique directories covered by the checked tree items.

        Track rows map to their album folder; artist/root rows count as
        the folder itself.
        """
        dirs = []
        seen = set()
        for path, on in self._checked.items():
            if not on or not path:
                continue
            d = os.path.dirname(path) if os.path.isfile(path) else path
            if d and d not in seen and os.path.isdir(d):
                seen.add(d)
                dirs.append(d)
        return sorted(dirs)

    def _open_in_external(self, key, targets=None):
        """Launch Mp3tag / Picard / foobar2000 with the given targets (files
        or folders), or the folders covered by the checked tree items."""
        spec = EXTERNAL_TOOLS[key]
        label = spec["label"]
        if targets is None:
            targets = self._selected_album_dirs()
        if not targets:
            self.status_var.set(f"No folders selected — check items in the "
                                f"library tree first.")
            self.log(f"{label}: nothing selected. Tick one or more albums "
                     f"(or artists) in the library tree first.", tag="yellow")
            return

        exe = find_external_tool(key, self.config)
        if not exe:
            if not messagebox.askyesno(
                f"{label} not found",
                f"{label} could not be located automatically.\n\n"
                f"Locate the {spec['exe']} executable manually?",
            ):
                return
            exe = filedialog.askopenfilename(
                parent=self, title=f"Locate {spec['exe']}",
                filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
            )
            if not exe:
                return
            self.config[spec["config_key"]] = os.path.normpath(exe)
            save_config(self.config)
            self.log(f"{label} path saved: {exe}", tag="muted")

        try:
            # GUI application: Popen without waiting; CREATE_NO_WINDOW keeps
            # any console-stub launcher from flashing a window.
            subprocess.Popen(
                [exe] + spec.get("args", []) + targets,
                creationflags=0x08000000 if sys.platform == "win32" else 0,
            )
        except Exception as e:
            self.log(f"Could not launch {label}: {e}", tag="red")
            messagebox.showerror(label, f"Could not launch {label}:\n{e}")
            return

        n = len(targets)
        verb = "Enqueued" if spec.get("args") else "Opened"
        n_files = sum(1 for t in targets if os.path.isfile(t))
        n_dirs = n - n_files
        what = []
        if n_files:
            what.append(f"{n_files} file{'s' if n_files != 1 else ''}")
        if n_dirs:
            what.append(f"{n_dirs} folder{'s' if n_dirs != 1 else ''}")
        msg = f"{verb} {' and '.join(what)} in {label}."
        self.log(msg, tag="green")
        self.status_var.set(msg)

    def _show_grade_details(self, item):
        """Dialog listing exactly which grade checks failed."""
        album_dir, res = self._find_album_for_item(item)
        if res is None:
            return
        path = self._item_paths.get(item)
        track_file = path if (album_dir and path != album_dir) else None

        win = tk.Toplevel(self)
        win.title("Grade Details" + (
            f" — {os.path.basename(track_file)}"
            if track_file else f" — {os.path.basename(album_dir)}"
        ))
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.geometry("680x520")
        win.minsize(560, 360)

        box = ttk.Frame(win, padding=14)
        box.pack(fill=tk.BOTH, expand=True)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)

        txt = tk.Text(box, wrap="none", state=tk.DISABLED, background=FIELD,
                      foreground=TEXT, borderwidth=0, insertbackground=TEXT,
                      highlightthickness=0, font=(self._monospace, 9))
        ysb = ttk.Scrollbar(box, orient=tk.VERTICAL, command=txt.yview)
        xsb = ttk.Scrollbar(box, orient=tk.HORIZONTAL, command=txt.xview)
        txt.configure(yscrollcommand=ysb.set, xscrollcommand=xsb.set)
        txt.grid(row=0, column=0, sticky="nswe")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")

        for tag, color in (("red", RED), ("green", GREEN), ("bold", BRIGHT)):
            txt.tag_configure(tag, foreground=color)
        txt.tag_configure("bold", font=_font(9, "bold"))

        def emit(text, style=None):
            txt.configure(state=tk.NORMAL)
            txt.insert(tk.END, text + "\n", style or ())
            txt.configure(state=tk.DISABLED)

        from mlo.grader import format_grade_report
        emit(os.path.basename(album_dir), "bold")
        for text, style in format_grade_report(
                res, self._lyrics_format, track_file=track_file):
            emit(text, style)

        btn = ttk.Frame(box)
        btn.grid(row=2, column=0, sticky="e", pady=(8, 0))
        ttk.Button(btn, text="Close", style="Small.TButton",
                   command=win.destroy).pack()

    def _regrade_album(self, album_dir):
        """Re-grade a single album in the background and refresh its row."""
        def run():
            try:
                from mlo.grader import _grade_album
                result = _grade_album(
                    album_dir, self._lyrics_format, self.config)
            except Exception:
                result = None
            if result is None:
                result = {"error": True, "path": album_dir}
            self._scan_q.put(("grade", album_dir, result))

        threading.Thread(target=run, daemon=True).start()

    def _regrade_targets(self, targets):
        """Queue background re-grades for the albums covered by run
        targets (files resolve to their album folder; artist folders
        expand to their albums; anything unknown falls back to a full
        library refresh)."""
        albums = set()
        full = False
        for t in targets:
            if not t:
                continue
            d = os.path.dirname(t) if os.path.isfile(t) else t
            if d in self._grade_cache:
                albums.add(d)
            elif d in (self._artists or {}):
                albums.update(self._artists[d])
            else:
                full = True
        if full or not albums:
            self._refresh_library(regrade=True)
            return
        for d in sorted(albums):
            self._regrade_album(d)

    def _copy_console(self):
        text = self.console.get("1.0", tk.END).strip()
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            self.status_var.set("Console output copied to clipboard.")

    def _drain_log(self):
        try:
            while True:
                kind, payload = self.log_q.get_nowait()
                if kind == "out":
                    self.console.configure(state=tk.NORMAL)
                    if payload and payload[-1][0].endswith("\n"):
                        stripped = payload[-1][0].rstrip("\n")
                        payload = list(payload)
                        payload[-1] = (stripped, payload[-1][1])
                    for text, tag in payload:
                        if text:
                            self.console.insert(tk.END, text, tag)
                    self.console.insert(tk.END, "\n", "fg")
                    self.console.configure(state=tk.DISABLED)
                    if self.autoscroll_var.get():
                        self.console.see(tk.END)
                elif kind == "nl":
                    self.console.configure(state=tk.NORMAL)
                    self.console.insert(tk.END, "\n", "fg")
                    self.console.configure(state=tk.DISABLED)
                    if self.autoscroll_var.get():
                        self.console.see(tk.END)
                elif kind == "prog":
                    done, total, desc = payload
                    if total:
                        self.progress.configure(maximum=total, value=min(done, total))
                        self.prog_label_var.set(f"{desc}  {done}/{total}")
                    else:
                        self.progress.configure(value=0)
                        self.prog_label_var.set("")
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "done":
                    self._set_running(False)
                    self.status_var.set(f"Ready — completed in {payload:.1f}s")
                    self.progress.configure(value=0)
                    self.prog_label_var.set("")
                    # Runs may have changed tags (audit verdicts, lyrics,
                    # MEDIA/SOURCE): refresh the library view so grades,
                    # the AUDIT column and row colors stay current.
                    pending = getattr(self, "_regrade_after", None)
                    self._regrade_after = None
                    if pending == "all":
                        self._refresh_library(regrade=True)
                    elif pending:
                        self._regrade_targets(pending)
                elif kind == "pause":
                    self.continue_btn.pack(side=tk.LEFT, padx=(0, 10))
                    self.status_var.set(f"Paused — Continue to run {payload}")
                elif kind == "update_auto":
                    # Result tuple is the payload; there is no dialog/button.
                    result = payload[0]
                    self._update_result = result
                    has_update, version, url, notes, error = result
                    if error:
                        self.log(f"Update check failed: {error}", tag="yellow")
                    elif has_update:
                        self.log(f"Update available: v{version}", tag="yellow")
                        self._handle_auto_update(version, url, notes)
                elif kind == "update_check":
                    win, btn, result = payload
                    self._update_result = result
                    has_update, version, url, notes, error = result
                    if btn is not None and btn.winfo_exists():
                        btn.configure(state=tk.NORMAL, text="Check for Updates")
                    if error:
                        self.log(f"Update check failed: {error}", tag="yellow")
                        if win is not None and win.winfo_exists():
                            messagebox.showerror(
                                "Update Check Failed",
                                f"Could not reach GitHub releases:\n{error}",
                                parent=win,
                            )
                    elif has_update:
                        self.log(f"Update available: v{version}", tag="yellow")
                        if win is not None and win.winfo_exists():
                            self._show_update_dialog(version, url, notes)
                    elif win is not None and win.winfo_exists():
                        messagebox.showinfo(
                            "No Updates",
                            "You are already on the latest version.",
                            parent=win,
                        )
                elif kind == "update_download":
                    win, btn, ok, path, error = payload
                    if not ok:
                        if btn is not None and btn.winfo_exists():
                            btn.configure(state=tk.NORMAL, text="Download & Install")
                        if win is not None and win.winfo_exists():
                            messagebox.showerror(
                                "Update failed", error or "Installer download failed.",
                                parent=win,
                            )
                    else:
                        self._start_update_shutdown(path, dialog=win, btn=btn)
        except queue.Empty:
            pass
        except Exception:
            # A single malformed message must not kill the drain loop; the
            # remaining queued messages are processed on the next tick.
            _stream = getattr(self, "stdout_stream", None)
            if _stream is not None:
                traceback.print_exc(file=_stream)
        self.after(80, self._drain_log)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _publish_instance_state(self):
        reason = ", ".join(sorted(self._busy_reasons))
        updater.update_instance(
            self._instance_state_path,
            busy=self._has_active_work(include_processes=False),
            reason=reason,
        )

    def _set_job_busy(self, name, busy):
        if busy:
            self._busy_reasons.add(name)
        else:
            self._busy_reasons.discard(name)
        self._publish_instance_state()

    def _has_active_work(self, include_processes=True):
        """Return true while closing or replacing the app would be unsafe."""
        active = bool(
            self.running
            or getattr(self, "_library_busy", False)
            or self._deps_busy
            or (self._run_thread is not None and self._run_thread.is_alive())
        )
        if include_processes and active_process_count():
            active = True
        return active

    def _pick_folder(self):
        path = filedialog.askdirectory(initialdir=self.folder_var.get() or "/")
        if path:
            self.folder_var.set(path)
            self.config["music_folder"] = path
            save_config(self.config)
            self.log(f"Library folder set to: {path}")
            self._refresh_library(regrade=True)

    def _open_config(self):
        if self.running:
            messagebox.showinfo("Busy", "Wait for the current operation to finish.")
            return
        # The dialog mutates the live config dict; snapshot the values that
        # decide whether a full (expensive) library re-grade is needed.
        self._pre_save_snapshot = (
            self.config.get("music_folder", ""),
            str(self.config.get("lyrics_format", "EMBEDDED")).upper(),
        )
        ConfigDialog(self, self.config, self._config_saved)

    def _config_saved(self, cfg):
        self.config = cfg
        self.folder_var.set(cfg.get("music_folder", ""))
        self.log("Settings saved.", tag="green")
        old_folder, old_fmt = getattr(self, "_pre_save_snapshot", (None, None))
        folder_changed = cfg.get("music_folder", "") != old_folder
        fmt_changed = str(cfg.get("lyrics_format", "EMBEDDED")).upper() != old_fmt
        self._refresh_library(regrade=folder_changed or fmt_changed)

    def _show_about(self):
        """Show About dialog with version info and update check."""
        from mlo import __version__
        win = tk.Toplevel(self)
        win.title("About Music Library Optimizer")
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.geometry("480x360")
        win.resizable(False, False)

        box = ttk.Frame(win, padding=24)
        box.pack(fill=tk.BOTH, expand=True)

        try:
            icon_file = os.path.join(SCRIPT_DIR, "app_icon.ico")
            if os.path.isfile(icon_file):
                win.iconbitmap(default=icon_file)
        except tk.TclError:
            pass

        ttk.Label(box, text="Music Library Optimizer", style="H1.TLabel").pack(anchor="w")
        ttk.Label(box, text=f"Version {__version__}", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))

        ttk.Separator(box).pack(fill=tk.X, pady=(0, 12))

        ttk.Label(box,
                  text="Lossless audio & image processing suite for maintaining "
                       "a tagged, graded, audited music library.",
                  style="Muted.TLabel", wraplength=400).pack(anchor="w", pady=(0, 8))

        ttk.Label(box,
                  text="GitHub: https://github.com/dillydalli3r/MusicLibraryOptimizer",
                  style="Muted.TLabel", wraplength=400).pack(anchor="w", pady=(0, 16))

        update_status = tk.StringVar(value="")
        if self._update_result and self._update_result[4] is None:
            if self._update_result[0]:
                update_status.set(
                    f"Update available: v{self._update_result[1]}"
                )
            else:
                update_status.set("Update status: already current")
        ttk.Label(box, textvariable=update_status, foreground=YELLOW,
                  wraplength=400).pack(anchor="w", pady=(0, 8))

        ttk.Separator(box).pack(fill=tk.X, pady=(0, 12))

        def check_updates():
            btn.configure(state=tk.DISABLED, text="Checking...")
            def cb(has_update, version, url, notes, error):
                self.log_q.put((
                    "update_check", (win, btn,
                                      (has_update, version, url, notes, error))
                ))
            updater.check_for_updates(silent=False, callback=cb)

        def open_github():
            import webbrowser
            webbrowser.open("https://github.com/dillydalli3r/MusicLibraryOptimizer")

        btn_frame = ttk.Frame(box)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        btn = ttk.Button(btn_frame, text="Check for Updates", style="Accent.TButton",
                         command=check_updates)
        btn.pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="View on GitHub", style="Small.TButton",
                   command=open_github).pack(side=tk.LEFT, padx=(8, 0))

        ttk.Button(box, text="Close", style="Small.TButton",
                   command=win.destroy).pack(side=tk.RIGHT, pady=(16, 0))

    def _handle_auto_update(self, version, url, notes):
        """Act on an update found at startup.

        With 'auto_update_on_start' the app downloads the installer and
        runs the update (only when idle); otherwise it just logs that an
        update is available. 'confirm_before_update' still applies.
        """
        if not self.config.get("auto_update_on_start", False):
            self.log("Tip: enable Settings → Interface → Auto-Install "
                     "Updates on Start to install this automatically.",
                     tag="muted")
            return
        if self._has_active_work():
            self.log("Update available (v" + str(version) +
                     ") but work is in progress — install it later from "
                     "ⓘ About → Check for Updates.", tag="yellow")
            return
        if self.config.get("confirm_before_update", True):
            self._show_update_dialog(version, url, notes)
            return
        self.log("Downloading update v" + str(version) + " …", tag="yellow")
        updater.download_and_prepare_installer(
            url,
            lambda ok, path, error: self.log_q.put(
                ("update_download", (None, None, ok, path, error))
            ),
        )

    def _show_update_dialog(self, version, url, notes):
        win = tk.Toplevel(self)
        win.title("Update Available")
        win.configure(background=PANEL)
        win.transient(self)
        win.grab_set()
        win.geometry("520x380")
        win.resizable(False, False)

        box = ttk.Frame(win, padding=24)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text=f"Update Available: v{version}", style="H1.TLabel", foreground=GREEN).pack(anchor="w")
        ttk.Label(box, text="A new version is ready to download.", style="Muted.TLabel").pack(anchor="w", pady=(0, 16))

        if notes:
            txt = tk.Text(box, wrap="word", height=8, background=FIELD, foreground=TEXT,
                          borderwidth=0, font=_font(9))
            txt.pack(fill=tk.BOTH, expand=True, pady=(0, 12))
            txt.insert("1.0", notes)
            txt.configure(state=tk.DISABLED)

        def download_and_install():
            if self._has_active_work():
                messagebox.showinfo(
                    "Update postponed",
                    "Finish the current operation before installing an update.",
                    parent=win,
                )
                return
            if self.config.get("confirm_before_update", True) and not messagebox.askyesno(
                "Install update",
                "The app will close all idle Music Library Optimizer windows "
                "before the installer starts. Continue?",
                parent=win,
            ):
                return
            btn.configure(state=tk.DISABLED, text="Downloading...")
            updater.download_and_prepare_installer(
                url,
                lambda ok, path, error: self.log_q.put(
                    ("update_download", (win, btn, ok, path, error))
                ),
            )
        btn = ttk.Button(box, text="Download & Install", style="Accent.TButton",
                         command=download_and_install)
        btn.pack(side=tk.LEFT, pady=(12, 0))
        ttk.Button(box, text="Later", style="Small.TButton",
                   command=win.destroy).pack(side=tk.RIGHT, pady=(12, 0))

    def _start_update_shutdown(self, installer_path, dialog=None, btn=None):
        """Coordinate every app instance, then let the helper run setup."""
        if self._has_active_work():
            messagebox.showinfo(
                "Update postponed",
                "The update cannot start while the library, a script, or an "
                "external tool is still working.",
                parent=self,
            )
            self._reenable_update_button(btn)
            return

        other_busy = updater.busy_instance_pids(os.getpid())
        if other_busy:
            reasons = ", ".join(
                f"PID {pid}: {reason}" for pid, reason in other_busy.items()
            )
            messagebox.showwarning(
                "Update postponed",
                "Another Music Library Optimizer instance is still working. "
                f"Finish it before updating.\n\n{reasons}",
                parent=self,
            )
            self._reenable_update_button(btn)
            return

        other_pids = updater.app_instance_pids() - {os.getpid()}
        if other_pids and self.config.get("update_close_other_instances", True):
            updater.request_close_instances(other_pids)
            # Wait asynchronously for the other windows to close; if they
            # refuse, ask the user instead of failing silently in the helper.
            self._installer_pending = installer_path
            self._installer_dialog = dialog
            self._installer_btn = btn
            self._installer_deadline = time.monotonic() + 20
            self._poll_instances_closing()
            return
        self._finish_update_shutdown(installer_path, dialog, btn)

    def _poll_instances_closing(self):
        if not (updater.app_instance_pids() - {os.getpid()}):
            self._finish_update_shutdown(self._installer_pending,
                                         self._installer_dialog,
                                         self._installer_btn)
            return
        if time.monotonic() > self._installer_deadline:
            if not messagebox.askyesno(
                "Instances still open",
                "Another Music Library Optimizer window is still open and "
                "did not close. Start the installer anyway?",
                parent=self,
            ):
                self._installer_pending = None
                self._reenable_update_button(self._installer_btn)
                return
            self._finish_update_shutdown(self._installer_pending,
                                         self._installer_dialog,
                                         self._installer_btn)
            return
        self.after(500, self._poll_instances_closing)

    def _finish_update_shutdown(self, installer_path, dialog, btn=None):
        self._installer_pending = None
        try:
            updater.launch_installer_after_shutdown(
                installer_path, updater.app_instance_pids())
        except Exception as e:
            self.log(f"Could not schedule installer: {e}", tag="red")
            messagebox.showerror(
                "Update failed", f"Could not schedule the installer:\n{e}",
                parent=self,
            )
            self._reenable_update_button(btn)
            return

        self._shutdown_for_update = True
        if dialog is not None and dialog.winfo_exists():
            dialog.destroy()
        self.on_destroy()

    def _reenable_update_button(self, btn):
        if btn is not None:
            try:
                if btn.winfo_exists():
                    btn.configure(state=tk.NORMAL, text="Download & Install")
            except Exception:
                pass

    def _discard_installer(self, installer_path):
        try:
            os.remove(installer_path)
        except OSError:
            pass

    def _run_all(self):
        order = self.config.get("run_all_order", DEFAULT_RUN_ALL_ORDER)
        self._run_scripts(order, "RUN ALL SCRIPTS")

    def _run_custom(self):
        if self.running:
            return
        dlg = CustomRunDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._run_scripts(dlg.result, "CUSTOM RUN ORDER")

    def _set_running(self, flag, label=""):
        self.running = flag
        self._set_job_busy("script run", flag)
        state = tk.DISABLED if flag else tk.NORMAL
        for b in self.run_buttons:
            b.configure(state=state)
        if hasattr(self, "opt_selected_btn"):
            if flag:
                self.opt_selected_btn.configure(state=tk.DISABLED)
            else:
                self._update_selection_label()
        self.status_var.set(f"Running: {label}" if flag else "Ready")
        if flag:
            self.progress.configure(maximum=100, value=0)
            self.prog_label_var.set("")

    def _continue(self):
        self.continue_btn.pack_forget()
        self.status_var.set("Running…")
        self._continue_event.set()

    def _open_deps(self):
        if self.running:
            messagebox.showinfo("Busy", "Wait for the current operation to finish.")
            return
        DependenciesDialog(self)

    def _update_dep_label(self):
        if not hasattr(self, "dep_label"):
            return
        n = len(tools_mod.detect_all_tools())
        # simple-dr-meter is a source script (not an exe), detected separately.
        if tools_mod.simple_dr_meter_path():
            n += 1
        total = len(fetchdeps.DISPLAY_NAMES)
        self.dep_label.configure(
            text=f"{n}/{total} tools detected" if n else "No tools detected"
        )

    def _run_scripts(self, script_ids, title, targets=None):
        if self.running:
            messagebox.showinfo("Busy", "An operation is already running.")
            return

        folder = self.folder_var.get().strip()
        if folder and self.config.get("music_folder") != folder:
            self.config["music_folder"] = folder
            save_config(self.config)

        self._set_running(True, title)
        self.log("")
        self.log("─" * 74, tag="muted")
        self.log(f"{title}", tag="bold")
        self.log(f"Scripts: {' → '.join(SCRIPT_NAMES[s] for s in script_ids)}", tag="muted")
        if targets:
            self.log(f"Targets: {len(targets)} selected item(s)", tag="muted")
            self._regrade_after = list(targets)
        else:
            self._regrade_after = "all"
        self.log("─" * 74, tag="muted")

        t = threading.Thread(
            target=self._worker,
            args=(list(script_ids), title, targets,
                  self.force_flac_var.get(),
                  self.force_images_var.get(),
                  self.force_audit_var.get(),
                  self.force_dr_var.get(),
                  self.force_autotag_var.get(),
                  self.force_lyrics_var.get(),
                  self.force_cue_var.get()),
            daemon=True
        )
        self._run_thread = t
        t.start()

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------
    def _worker(self, script_ids, title, targets=None, force_flac=False,
                force_images=False, force_audit=False, force_dr=False,
                force_autotag=False, force_lyrics=False, force_cue=False):
        started = time.monotonic()
        prev_tqdm, prev_hook = stats_mod.tqdm, stats_mod.progress_hook
        stats_mod.tqdm = None
        stats_mod.progress_hook = lambda done, total, desc: self.log_q.put(
            ("prog", (done, total, desc))
        )
        set_file_lines(True)

        # Runners never mutate the config; a copy lets us scope a run to
        # user-selected directories/tracks without affecting the app.
        run_cfg = normalize_config(self.config)
        if targets is not None:
            run_cfg["targets"] = list(targets)
        if force_flac:
            run_cfg["force_reencode_flac"] = True
        if force_images:
            run_cfg["force_reencode_images"] = True
        if force_audit:
            run_cfg["force_audit"] = True
        if force_dr:
            run_cfg["force_dr_replaygain"] = True
        if force_autotag:
            run_cfg["force_auto_tag"] = True
        if force_lyrics:
            run_cfg["force_lyrics"] = True
        if force_cue:
            run_cfg["force_cue"] = True

        per_script = []
        total_bytes_added = total_bytes_removed = total_errors = 0
        all_errors = []

        try:
            for i, script_id in enumerate(script_ids):
                name, runner = RUNNERS[script_id]

                # Honor Auto-Advance: pause between scripts when disabled.
                if i > 0 and not run_cfg.get("auto_advance", True):
                    self._continue_event.clear()
                    self.log_q.put(("pause", name))
                    self.log(f"⏸ Paused before {name} (Auto-Advance is off)",
                             tag="yellow")
                    self._continue_event.wait()

                self.log("")
                self.log(f"▶ Starting {name}", tag="blue")

                try:
                    s = runner(run_cfg)
                except Exception as e:
                    self.log(f"FATAL in {name}: {e}")
                    traceback.print_exc(file=self.stdout_stream)
                    s = new_stats_stub()
                    s["error_count"] = 1
                    s["errors"] = [(name, str(e))]

                per_script.append((name, s))

                if not s.get("is_grader"):
                    total_bytes_added += s.get("total_bytes_added", 0)
                    total_bytes_removed += s.get("total_bytes_removed", 0)
                    total_errors += s.get("error_count", 0)
                    all_errors.extend(s.get("errors", []))

                if s.get("is_grader"):
                    print_grade_results(s, title=f"RESULTS — {name}")
                else:
                    print_results(s, title=f"RESULTS — {name}")

            if len(script_ids) > 1:
                print_combined_results(
                    per_script, title="COMBINED RESULTS — ALL SCRIPTS"
                )

                if all_errors:
                    self.log("Errors:", tag="red")
                    for path, err in all_errors[:50]:
                        self.log(f"  - {path}", tag="red")
                        self.log(f"      {err}", tag="red")
                    if len(all_errors) > 50:
                        self.log(f"  … and {len(all_errors) - 50} more.", tag="red")

            elapsed = time.monotonic() - started
            self.log("")
            self.log(f"✔ {title} completed in {elapsed:.1f}s", tag="green")

        except Exception:
            traceback.print_exc(file=self.stdout_stream)

        finally:
            stats_mod.tqdm, stats_mod.progress_hook = prev_tqdm, prev_hook
            set_file_lines(False)
            # Queue-based completion: never touch Tk from the worker thread.
            self.log_q.put(("done", time.monotonic() - started))

    # ------------------------------------------------------------------
    def on_destroy(self):
        if not self._shutdown_for_update and self._has_active_work():
            if not messagebox.askyesno(
                "Operation in progress",
                "A scan, script, or download is still working. Close anyway? "
                "The work will be abandoned.",
                parent=self,
            ):
                return
        updater.unregister_instance(self._instance_state_path)
        sys.stdout, sys.stderr = self._real_stdout, self._real_stderr
        self.destroy()


def new_stats_stub():
    s = stats_mod.new_stats()
    s["is_grader"] = False
    return s


def main():
    app = App()
    if app.winfo_exists():
        app.protocol("WM_DELETE_WINDOW", app.on_destroy)
        app.mainloop()


if __name__ == "__main__":
    main()
