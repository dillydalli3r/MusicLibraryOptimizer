"""GUI dialog windows: dependencies, settings, run order, first-run wizard."""
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from mlo import fetchdeps
from mlo import tools as tools_mod
from mlo.config import (
    DEFAULT_CONFIG, DEFAULT_RUN_ALL_ORDER, normalize_config,
    load_config, save_config,
)
from mlo.deps import HAS_MUTAGEN, HAS_PIL
from mlo.gui import (
    BG, PANEL, SIDEBAR, CARD, FIELD, BORDER, BORDER_STRONG, TEXT, BRIGHT,
    MUTED, ACCENT, ACCENT_DARK, GREEN, RED, YELLOW, UI_FAMILY, MONO_FAMILY,
    SCRIPT_NAMES, TREE_COLUMNS, CONFIG_FIELDS, FIELD_DESCRIPTIONS,
    ToggleSwitch, ToolTip, WrapFrame, apply_window_chrome, _font, _sfont,
)
from mlo.paths import DEPS_DIR


class DependenciesDialog(tk.Toplevel):
    """Download / update the external toolchain from GitHub."""

    KEYS = ("flac", "libjxl", "libjpeg_turbo", "oxipng", "audioauditor",
            "rsgain", "ffmpeg", "simpledrmeter")

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("Dependencies")
        self.configure(background=PANEL)
        self.transient(app)
        self.grab_set()
        self.minsize(720, 440)
        self.busy = False
        self.q = queue.Queue()
        self.latest = {}

        outer = ttk.Frame(self, padding=18)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Toolchain", style="H2.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Downloads the latest official Windows builds from GitHub "
                 "releases into the .dependencies folder next to the app. "
                 "AudioAuditor provides the Audit Library script.",
            style="Muted.TLabel", wraplength=660, justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 12))

        grid = ttk.Frame(outer)
        grid.pack(fill=tk.X)
        for col, width in ((0, 26), (1, 16), (2, 16), (3, 14), (4, 28)):
            grid.columnconfigure(col, minsize=width)

        headers = ("Tool", "Installed", "Latest", "", "Status")
        for col, text in enumerate(headers):
            ttk.Label(grid, text=text.upper(), style="Section.TLabel").grid(
                row=0, column=col, sticky="w", padx=6, pady=(0, 6)
            )

        self.rows = {}
        installed = fetchdeps.installed_versions()
        for i, key in enumerate(self.KEYS, start=1):
            inst = installed.get(key, "")
            self.rows[key] = {
                "installed": tk.StringVar(value=inst or "—"),
                "latest": tk.StringVar(value="…"),
                "status": tk.StringVar(value=""),
                "button": None,
                "installed_version": inst,
            }
            row = self.rows[key]
            ttk.Label(grid, text=fetchdeps.DISPLAY_NAMES[key]).grid(
                row=i, column=0, sticky="w", padx=6, pady=3
            )
            ttk.Label(grid, textvariable=row["installed"],
                      foreground=GREEN if inst else MUTED).grid(
                row=i, column=1, sticky="w", padx=6, pady=3
            )
            ttk.Label(grid, textvariable=row["latest"]).grid(
                row=i, column=2, sticky="w", padx=6, pady=3
            )
            btn = ttk.Button(grid, text="…", width=10,
                             command=lambda k=key: self._install([k]))
            btn.grid(row=i, column=3, sticky="w", padx=6, pady=3)
            row["button"] = btn
            ttk.Label(grid, textvariable=row["status"],
                      foreground=MUTED).grid(
                row=i, column=4, sticky="w", padx=6, pady=3
            )

        btns = ttk.Frame(outer)
        btns.pack(fill=tk.X, pady=(16, 0))
        ttk.Button(btns, text="Install / Update All",
                   style="Accent.TButton",
                   command=lambda: self._install(list(self.KEYS))).pack(side=tk.RIGHT)
        ttk.Button(btns, text="Refresh",
                   command=self._check_latest).pack(side=tk.RIGHT, padx=(0, 8))
        ttk.Button(btns, text="Open Folder",
                   command=self._open_folder).pack(side=tk.RIGHT, padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(150, lambda: apply_window_chrome(self))
        self.after(120, self._poll)
        self._check_latest()

    # ------------------------------------------------------------------
    def _on_close(self):
        if self.busy:
            if not messagebox.askyesno(
                "Download in progress",
                "A download is still running. Close this window anyway? The "
                "download continues in the background; the app will close "
                "once it finishes.", parent=self,
            ):
                return
        self.destroy()

    def _open_folder(self):
        if os.path.isdir(DEPS_DIR):
            os.startfile(DEPS_DIR)
        else:
            messagebox.showinfo(
                "Not created yet", "The .dependencies folder does not exist yet.",
                parent=self,
            )

    def _set_busy(self, flag):
        self.busy = flag
        self.app._deps_busy = flag
        self.app._set_job_busy("dependency download", flag)
        state = tk.DISABLED if flag else tk.NORMAL
        for row in self.rows.values():
            row["button"].configure(state=state)

    def _check_latest(self):
        def work():
            try:
                self.q.put(("latest", fetchdeps.latest_versions()))
            except Exception as e:
                self.q.put(("neterr", str(e)))
        threading.Thread(target=work, daemon=True).start()

    def _install(self, keys):
        if self.busy:
            return

        def work():
            self.q.put(("busy", True))
            for key in keys:
                name = fetchdeps.DISPLAY_NAMES[key]
                self.q.put(("status", key, "Downloading…", TEXT))
                try:
                    def prog(done, total, _name=name):
                        self.app.log_q.put(
                            ("prog", (done, total, f"Downloading {_name}"))
                        )
                    version = fetchdeps.install_dependency(
                        key,
                        log=lambda m: self.app.log(m, tag="muted"),
                        progress=prog,
                    )
                    self.q.put(("installed", key, version))
                except Exception as e:
                    self.app.log(f"Dependency install failed ({name}): {e}",
                                 tag="red")
                    self.q.put(("fail", key, str(e)))
            fetchdeps.refresh_tool_cache()
            self.q.put(("busy", False))
        self._install_thread = threading.Thread(target=work, daemon=True)
        self._install_thread.start()

    def _row_button_text(self, key):
        row = self.rows[key]
        inst = row["installed_version"]
        latest = self.latest.get(key)
        if not inst:
            return "Download"
        if latest and tools_mod._version_is_older(inst, latest):
            return "Update"
        return "Reinstall"

    def _poll(self):
        try:
            while True:
                kind, *payload = self.q.get_nowait()
                if not self.winfo_exists():
                    # Dialog closed mid-download: only relay the busy flag so
                    # the app never gets stuck thinking work is in progress.
                    if kind == "busy":
                        self.app._deps_busy = bool(payload[0])
                        self.app._set_job_busy("dependency download",
                                               bool(payload[0]))
                    continue
                if kind == "latest":
                    self.latest = payload[0]
                    for key in self.KEYS:
                        self.rows[key]["latest"].set(self.latest.get(key, "?"))
                        self.rows[key]["button"].configure(
                            text=self._row_button_text(key)
                        )
                elif kind == "neterr":
                    for key in self.KEYS:
                        self.rows[key]["latest"].set("unavailable")
                        self.rows[key]["status"].set("")
                    self.app.log(
                        f"Could not query GitHub for latest versions: {payload[0]}",
                        tag="yellow",
                    )
                elif kind == "status":
                    key, text, color = payload
                    self.rows[key]["status"].set(text)
                elif kind == "installed":
                    key, version = payload
                    row = self.rows[key]
                    row["installed_version"] = version
                    row["installed"].set(version)
                    row["status"].set("Installed")
                    row["button"].configure(text=self._row_button_text(key))
                    self.app._update_dep_label()
                elif kind == "fail":
                    key, err = payload
                    self.rows[key]["status"].set(f"Failed: {err[:60]}")
                elif kind == "busy":
                    self._set_busy(payload[0])
        except queue.Empty:
            pass
        except Exception:
            # Never let one bad message kill the poll loop.
            pass
        if self.winfo_exists():
            self.after(120, self._poll)
        elif getattr(self, "_install_thread", None) is not None \
                and self._install_thread.is_alive():
            self.after(120, self._poll)



class ConfigDialog(tk.Toplevel):
    def __init__(self, parent, config, on_saved):
        super().__init__(parent)
        # Work on a validated candidate so Cancel never changes the live
        # configuration in memory.
        self.config = normalize_config(config)
        self.on_saved = on_saved
        self.vars = {}

        self.title("Settings")
        self.configure(background=PANEL)
        self.transient(parent)
        self.grab_set()
        self.minsize(760, 640)

        outer = ttk.Frame(self, padding=16)
        outer.pack(fill=tk.BOTH, expand=True)

        canvas = tk.Canvas(outer, highlightthickness=0, background=PANEL)
        scrollbar = ttk.Scrollbar(outer, orient=tk.VERTICAL, command=canvas.yview)
        inner = ttk.Frame(canvas, style="Panel.TFrame")

        inner.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")
        # Keep the content frame as wide as the canvas so rows stretch
        # when the dialog is resized (otherwise everything stays at the
        # initial requested width).
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfigure(inner_id, width=e.width),
        )
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        canvas.bind(
            "<Enter>",
            lambda e: canvas.bind_all(
                "<MouseWheel>",
                lambda ev: canvas.yview_scroll(int(-ev.delta / 120), "units"),
            ),
        )
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        # --- Library folder -------------------------------------------------
        row = 0
        folder_header = ttk.Label(inner, text="Library Folder", style="H2.Panel.TLabel")
        folder_header.grid(row=row, column=0, sticky="w", padx=5, pady=(0, 4))
        ToolTip(folder_header, FIELD_DESCRIPTIONS["music_folder"])
        row += 1
        folder_frame = ttk.Frame(inner, style="Panel.TFrame")
        folder_frame.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 12))
        folder_frame.columnconfigure(0, weight=1)
        folder_var = tk.StringVar(value=config.get("music_folder", ""))
        self.vars["music_folder"] = folder_var
        ttk.Entry(folder_frame, textvariable=folder_var).grid(
            row=0, column=0, sticky="ew"
        )
        ttk.Button(folder_frame, text="Browse…", command=lambda: self._browse(folder_var)).grid(
            row=0, column=1, padx=(8, 0)
        )
        row += 1

        # --- Option groups ---------------------------------------------------
        groups = [
            ("FLAC", ["flac_level", "add_seektables", "force_reencode_flac"]),
            ("Images", [
                "jpegxl_effort", "reencode_images", "reencode_to_jxl",
                "convert_jxl_back", "rename_to_cover", "remove_alpha",
                "jpeg_progressive", "png_optimization_level",
                "force_reencode_images",
            ]),
            ("Lyrics", [
                "optimize_lrc", "optimize_embedded_lyrics", "lyrics_format",
                "lrc_timestamp_precision", "lrc_strip_metadata",
                "lrc_collapse_blank_lines", "append_final_newline",
            ]),
            ("CUE Sheets", [
                "keep_empty_cue_lines", "keep_other_cue_lines", "cue_file_type",
            ]),
            ("Tags", [
                "normalize_media_source", "digital_media_source_value",
                "fix_instrumental_from_lyrics", "write_audit_tag",
                "write_log_grade", "write_replaygain_tags",
                "write_dynamic_range_tags",
            ]),
            ("Grading", [
                "grade_include_music", "grade_include_cover",
                "grade_include_cue", "grade_include_log", "grade_include_lrc",
                "grade_include_other",
            ]),
            ("Audio Auditor", [
                "audit_thorough", "force_audit", "audit_cutoff_allow",
                "audit_verify_cd_checksums",
                "audit_clipping", "audit_mqa", "audit_ai",
                "audit_fake_stereo", "audit_silence", "audit_dynamic_range",
                "audit_true_peak", "audit_lufs", "audit_bpm",
            ]),
            ("DR / ReplayGain", [
                "dr_replaygain_enabled", "replaygain_skip_existing",
                "force_dr_replaygain",
            ]),
            ("Auto Tagging", [
                "auto_advisory", "auto_instrumental", "force_auto_tag",
            ]),
            ("Interface", [
                "grade_verbose", "auto_advance", "worker_limit", "compact_ui",
                "show_sidecar_files",
                "check_updates_on_start", "auto_update_on_start",
                "update_check_interval_days",
                "update_close_other_instances", "confirm_before_update",
            ]),
        ]
        field_lookup = {f[0]: f for f in CONFIG_FIELDS}

        for group_title, keys in groups:
            ttk.Label(inner, text=group_title, style="H2.Panel.TLabel").grid(
                row=row, column=0, sticky="w", padx=5, pady=(8, 4)
            )
            row += 1
            box = ttk.Frame(inner, style="Card.TFrame")
            box.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 4))
            box.columnconfigure(1, weight=1)

            for i, key in enumerate(keys):
                _, label, kind, extra = field_lookup[key]
                field_label = ttk.Label(box, text=label, style="Card.TLabel")
                field_label.grid(row=i, column=0, sticky="w", padx=(10, 12), pady=4)
                ToolTip(field_label, FIELD_DESCRIPTIONS.get(key, ""))
                if kind == "bool":
                    var = tk.BooleanVar(value=bool(config.get(key, False)))
                    widget = ToggleSwitch(box, var, bg=CARD)
                    widget.grid(row=i, column=1, sticky="e", padx=(0, 10), pady=4)
                elif kind == "int":
                    var = tk.IntVar(value=int(config.get(key, 0)))
                    widget = ttk.Spinbox(
                        box, from_=extra[0], to=extra[1], textvariable=var, width=8
                    )
                    widget.grid(row=i, column=1, sticky="e", padx=(0, 10), pady=4)
                elif kind == "choice":
                    var = tk.StringVar(value=str(config.get(key, extra[0])).upper())
                    if var.get() not in extra:
                        var.set(extra[0])
                    widget = ttk.Combobox(
                        box, textvariable=var, values=list(extra),
                        state="readonly", width=16,
                    )
                    widget.grid(row=i, column=1, sticky="e", padx=(0, 10), pady=4)
                else:
                    var = tk.StringVar(value=str(config.get(key, "")))
                    widget = ttk.Entry(box, textvariable=var)
                    widget.grid(row=i, column=1, sticky="ew", padx=(0, 10), pady=4)
                ToolTip(widget, FIELD_DESCRIPTIONS.get(key, ""))
                self.vars[key] = var
            row += 1

        # --- Run All order ----------------------------------------------------
        order_header = ttk.Label(inner, text="Run All Order", style="H2.Panel.TLabel")
        order_header.grid(row=row, column=0, sticky="w", padx=5, pady=(8, 4))
        ToolTip(order_header, FIELD_DESCRIPTIONS["run_all_order"])
        row += 1
        order_box = ttk.Frame(inner, style="Card.TFrame")
        order_box.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 4))
        current = list(config.get("run_all_order", DEFAULT_RUN_ALL_ORDER))
        for sid in SCRIPT_NAMES:
            if sid not in current:
                current.append(sid)
        self.order_vars = []
        for i, sid in enumerate(current[:len(SCRIPT_NAMES)]):
            ttk.Label(order_box, text=f"{i + 1}.", style="Card.TLabel").grid(
                row=0, column=i, padx=(10, 2) if i == 0 else (0, 2), pady=6
            )
            sv = tk.StringVar(value=SCRIPT_NAMES[sid])
            self.order_vars.append(sv)
            ttk.Combobox(
                order_box, textvariable=sv, width=12, state="readonly",
                values=[SCRIPT_NAMES[n] for n in sorted(SCRIPT_NAMES)],
            ).grid(row=0, column=i, padx=(0, 8), pady=6)
        row += 1

        # --- Encoder Tags ------------------------------------------------------
        tag_header = ttk.Label(inner, text="Encoder Tags", style="H2.Panel.TLabel")
        tag_header.grid(row=row, column=0, sticky="w", padx=5, pady=(8, 4))
        ToolTip(tag_header, "Which ENCODER marker tags each file type gets.\n"
                            "ENCODER_PROGRAM: encoder name\n"
                            "ENCODER_QUALITY: compression level\n"
                            "ENCODER_VERSION: encoder version\n"
                            "FLAC uses Vorbis comments, JPEG/JXL use XMP, "
                            "PNG uses tEXt chunks.\n"
                            "Disabling QUALITY + VERSION makes files "
                            "unidentifiable, so they are always re-encoded.")
        row += 1
        tag_box = ttk.Frame(inner, style="Card.TFrame")
        tag_box.grid(row=row, column=0, sticky="ew", padx=5, pady=(0, 4))
        tag_box.columnconfigure(0, weight=1)
        self.encoder_tag_vars = {}
        tag_types = [
            ("flac", "FLAC (.flac)"),
            ("jpeg", "JPEG (.jpg/.jpeg)"),
            ("png", "PNG (.png)"),
            ("jxl", "JPEG XL (.jxl)"),
        ]
        for c, col in enumerate(("Tag", "Program", "Quality", "Version")):
            ttk.Label(tag_box, text=col, style="Card.TLabel",
                      font=_sfont(9)).grid(
                row=0, column=c, padx=(10 if c == 0 else 4, 8), pady=(8, 2),
                sticky="w" if c == 0 else "e")
        for i, (ftype, label) in enumerate(tag_types, start=1):
            ttk.Label(tag_box, text=label, style="Card.TLabel").grid(
                row=i, column=0, sticky="w", padx=(10, 8), pady=5)
            self.encoder_tag_vars[ftype] = {}
            for j, key in enumerate(("ENCODER_PROGRAM", "ENCODER_QUALITY",
                                     "ENCODER_VERSION"), start=1):
                var = tk.BooleanVar(
                    value=bool((config.get("encoder_tags") or {}).get(ftype, {}).get(key, True))
                )
                self.encoder_tag_vars[ftype][key] = var
                ToggleSwitch(tag_box, var, bg=CARD).grid(
                    row=i, column=j, padx=(0, 8), pady=5, sticky="e")
        row += 1

        # --- Dependency status -------------------------------------------------
        enc_header = ttk.Frame(inner, style="Panel.TFrame")
        enc_header.grid(row=row, column=0, sticky="ew", padx=5, pady=(8, 4))
        enc_header.columnconfigure(0, weight=1)
        enc_label = ttk.Label(enc_header, text="Detected Tools",
                              style="H2.Panel.TLabel")
        enc_label.grid(row=0, column=0, sticky="w")
        ToolTip(enc_label, "Versions auto-detected from the .dependencies "
                           "folder. Use Dependencies to download or update "
                           "them.")
        ttk.Button(enc_header, text="Manage…",
                   command=lambda: DependenciesDialog(self.master)).grid(
            row=0, column=1, sticky="e"
        )
        row += 1
        tools = tools_mod.detect_all_tools()
        from mlo.tools import simple_dr_meter_path
        found = {
            "flac": tools.get("flac", {}).get("version"),
            "libjxl": tools.get("libjxl", {}).get("version"),
            "libjpeg-turbo": tools.get("libjpeg_turbo", {}).get("version"),
            "oxipng": tools.get("oxipng", {}).get("version"),
            "auditor": tools.get("audioauditor", {}).get("version"),
            "rsgain": tools.get("rsgain", {}).get("version"),
            "ffmpeg": tools.get("ffmpeg", {}).get("version"),
            "dr-meter": fetchdeps.PINNED["simpledrmeter"]["version"]
            if simple_dr_meter_path() else None,
        }
        ver_lines = "   ".join(
            f"{name} {'v' + ver if ver else '—'}" for name, ver in found.items()
        )
        ttk.Label(
            inner, text=ver_lines, style="Card.TLabel",
            font=("Consolas", 9),
        ).grid(row=row, column=0, sticky="w", padx=15)
        if not any(found.values()):
            ttk.Label(
                inner, foreground=YELLOW, background=PANEL,
                text="No tools found. Place flac / libjxl / libjpeg-turbo / oxipng /\n"
                     "AudioAuditor folders inside .dependencies next to the app.",
                justify=tk.LEFT,
            ).grid(row=row + 1, column=0, sticky="w", padx=15, pady=4)
        row += 2

        ttk.Label(
            inner, text="Digital SOURCE Value: written to SOURCE when MEDIA is "
                        '"Digital Media" and SOURCE is missing.\nExisting values '
                        "are preserved.", style="Card.TLabel",
        ).grid(row=row, column=0, sticky="w", padx=15, pady=(4, 0))

        # --- Buttons ------------------------------------------------------------
        btns = ttk.Frame(self, padding=(16, 12))
        btns.pack(fill=tk.X)
        ttk.Button(btns, text="Reset to Defaults", command=self._reset_defaults).pack(
            side=tk.LEFT
        )
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(
            side=tk.RIGHT, padx=5
        )
        ttk.Button(btns, text="Save", style="Accent.TButton", command=self._save).pack(
            side=tk.RIGHT, padx=5
        )

        inner.columnconfigure(0, weight=1)
        canvas.configure(width=max(inner.winfo_reqwidth(), 560))
        self.after(150, lambda: apply_window_chrome(self))

    def _reset_defaults(self):
        if not messagebox.askyesno(
            "Reset settings",
            "Restore every setting to its default value?\n"
            "Nothing is written to disk until you press Save.",
            parent=self,
        ):
            return
        defaults = DEFAULT_CONFIG.copy()
        self.vars["music_folder"].set(defaults.get("music_folder", ""))
        for key, _label, kind, extra in CONFIG_FIELDS:
            if key == "run_all_order":
                continue
            var = self.vars[key]
            d = defaults.get(key)
            try:
                if kind == "bool":
                    var.set(bool(d))
                elif kind == "int":
                    var.set(int(d))
                elif kind == "choice":
                    var.set(str(d).upper())
                else:
                    var.set(str(d))
            except (ValueError, tk.TclError):
                pass
        order = defaults.get("run_all_order", DEFAULT_RUN_ALL_ORDER)
        for sv, sid in zip(self.order_vars, order):
            sv.set(SCRIPT_NAMES[sid])
        default_tags = defaults.get("encoder_tags") or {}
        for ftype, fields in self.encoder_tag_vars.items():
            for key, var in fields.items():
                var.set(bool(default_tags.get(ftype, {}).get(key, True)))

    def _browse(self, var):
        path = filedialog.askdirectory(parent=self, initialdir=var.get() or "/")
        if path:
            var.set(path)

    def _save(self):
        for key, label, kind, extra in CONFIG_FIELDS:
            if key == "run_all_order":
                continue
            var = self.vars[key]
            try:
                if kind == "bool":
                    self.config[key] = bool(var.get())
                elif kind == "int":
                    v = int(var.get())
                    if not (extra[0] <= v <= extra[1]):
                        raise ValueError
                    self.config[key] = v
                elif kind == "choice":
                    self.config[key] = var.get().upper()
                else:
                    self.config[key] = var.get().strip()
            except (ValueError, tk.TclError):
                messagebox.showerror(
                    "Invalid value", f"'{label}' has an invalid value.", parent=self
                )
                return

        self.config["music_folder"] = self.vars["music_folder"].get().strip()

        encoder_tags = self.config.get("encoder_tags") or {}
        for ftype, fields in self.encoder_tag_vars.items():
            encoder_tags[ftype] = {
                key: bool(var.get()) for key, var in fields.items()
            }
        self.config["encoder_tags"] = encoder_tags

        name_to_id = {v: k for k, v in SCRIPT_NAMES.items()}
        order = []
        for sv in self.order_vars:
            sid = name_to_id.get(sv.get())
            if sid and sid not in order:
                order.append(sid)
        self.config["run_all_order"] = order or DEFAULT_RUN_ALL_ORDER

        if not str(self.config.get("digital_media_source_value", "")).strip():
            self.config["digital_media_source_value"] = DEFAULT_DIGITAL_SOURCE

        self.config = normalize_config(self.config)
        if not save_config(self.config):
            messagebox.showerror("Save failed", "Could not write config.json.", parent=self)
            return

        self.on_saved(self.config)
        self.destroy()



class CustomRunDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.result = []

        self.title("Custom Run")
        self.configure(background=PANEL)
        self.transient(parent)
        self.grab_set()
        self.resizable(False, False)

        outer = ttk.Frame(self, padding=20)
        outer.pack(fill=tk.BOTH, expand=True)

        ttk.Label(outer, text="Run Order", style="H2.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Script numbers, comma-separated — e.g.  3,1,2,5",
                  style="Muted.TLabel",
                  ).pack(anchor="w", pady=(0, 8))

        self.entry_var = tk.StringVar()
        e = ttk.Entry(outer, textvariable=self.entry_var, width=24)
        e.pack(anchor="w",)
        e.focus_set()

        ttk.Label(outer, text="1 Format Lyrics    2 Format CUEs    3 Optimize FLACs\n"
                              "4 Grade Library    5 Process Images  6 Audit Library",
                  style="Muted.TLabel", justify=tk.LEFT).pack(anchor="w", pady=(10, 0))

        btns = ttk.Frame(outer)
        btns.pack(anchor="e", pady=(14, 0))
        ttk.Button(btns, text="Cancel", command=self.destroy).pack(side=tk.RIGHT, padx=5)
        ttk.Button(btns, text="Run", style="Accent.TButton", command=self._ok).pack(
            side=tk.RIGHT, padx=5
        )

        self.bind("<Return>", lambda e: self._ok())
        self.after(150, lambda: apply_window_chrome(self))

    def _ok(self):
        order = []
        for part in self.entry_var.get().replace(" ", "").split(","):
            if part in tuple(str(n) for n in SCRIPT_NAMES) \
                    and int(part) not in order:
                order.append(int(part))
        if not order:
            messagebox.showinfo(
                "Invalid order",
                f"Enter at least one script number (1-{len(SCRIPT_NAMES)}).",
                parent=self)
            return
        self.result = order
        self.destroy()



class FirstRunWizard(tk.Toplevel):
    """Wizard shown on first launch to configure library folder and settings."""

    def __init__(self, parent, config, on_complete, reopen=False):
        super().__init__(parent)
        self.config = config
        self.on_complete = on_complete
        self.reopen = reopen
        self.vars = {}

        self.title("Setup Guide" if reopen else "Welcome to Music Library Optimizer")
        self.configure(background=PANEL)
        self.transient(parent)
        # Setup must finish before a script can be started; this also prevents
        # a half-configured first launch from racing the library scanner.
        self.grab_set()
        self.resizable(False, False)
        self.geometry("720x580")
        self.lift()
        self.focus_force()
        self.protocol("WM_DELETE_WINDOW", self._skip)

        outer = ttk.Frame(self, padding=24)
        outer.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(outer)
        header.pack(fill=tk.X, pady=(0, 16))
        ttk.Label(header, text="Music Library Optimizer", style="H1.TLabel").pack(anchor="w")
        ttk.Label(header,
                  text="Let's get you set up. Choose your music library folder and review the default settings.",
                  style="Muted.TLabel", wraplength=640).pack(anchor="w", pady=(4, 0))

        # Step indicator
        self.step = 0
        self.steps = ["Welcome", "Settings Preset", "Dependencies", "Ready"]
        self.step_frame = ttk.Frame(outer)
        self.step_frame.pack(fill=tk.X, pady=(0, 16))
        self.step_labels = []
        for i, name in enumerate(self.steps):
            lbl = ttk.Label(self.step_frame, text=f"  {i+1}. {name}  ",
                            style="Muted.TLabel", borderwidth=1, relief="solid")
            lbl.pack(side=tk.LEFT, padx=2)
            self.step_labels.append(lbl)
        self._update_step_indicator()

        # Content area (swapped per step)
        self.content = ttk.Frame(outer)
        self.content.pack(fill=tk.BOTH, expand=True)

        # Navigation buttons
        nav = ttk.Frame(outer)
        nav.pack(fill=tk.X, pady=(16, 0))
        self.back_btn = ttk.Button(nav, text="← Back", command=self._go_back, state=tk.DISABLED)
        self.back_btn.pack(side=tk.LEFT)
        self.next_btn = ttk.Button(nav, text="Next →", style="Accent.TButton", command=self._go_next)
        self.next_btn.pack(side=tk.RIGHT)
        self.finish_btn = ttk.Button(nav, text="Finish", style="Accent.TButton", command=self._finish, state=tk.HIDDEN)
        self.finish_btn.pack(side=tk.RIGHT, padx=(0, 8))

        self._show_step(0)
        self.after(150, lambda: apply_window_chrome(self))

    def _update_step_indicator(self):
        for i, lbl in enumerate(self.step_labels):
            if i == self.step:
                lbl.configure(style="Section.TLabel", foreground=ACCENT)
            elif i < self.step:
                lbl.configure(style="Muted.TLabel", foreground=GREEN)
            else:
                lbl.configure(style="Muted.TLabel", foreground=MUTED)

    def _show_step(self, n):
        self.step = n
        for w in self.content.winfo_children():
            w.destroy()
        self._update_step_indicator()
        self.back_btn.configure(state=tk.NORMAL if n > 0 else tk.DISABLED)
        self.next_btn.configure(state=tk.NORMAL if n < len(self.steps) - 1 else tk.HIDDEN)
        self.finish_btn.configure(state=tk.HIDDEN)
        if n == 0:
            self._build_step_library()
        elif n == 1:
            self._build_step_preset()
        elif n == 2:
            self._build_step_deps()
        elif n == 3:
            self._build_step_ready()

    def _go_back(self):
        if self.step > 0:
            self._show_step(self.step - 1)

    def _go_next(self):
        if self.step == 0:
            folder = self.vars.get("music_folder", "").get().strip()
            if not folder:
                messagebox.showwarning(
                    "Required", "Please select a music library folder.", parent=self
                )
                return
            if not os.path.isdir(folder):
                messagebox.showwarning(
                    "Folder not found",
                    "Choose an existing music library folder before continuing.",
                    parent=self,
                )
                return
        elif self.step == 1:
            pass  # preset step has no validation
        elif self.step == 2:
            pass
        if self.step < len(self.steps) - 1:
            self._show_step(self.step + 1)

    def _finish(self):
        # Save the music folder chosen in the welcome step.
        folder = self.vars.get("music_folder", "").get().strip()
        if not os.path.isdir(folder):
            messagebox.showwarning(
                "Folder not found",
                "Choose an existing music library folder before finishing.",
                parent=self,
            )
            self._show_step(0)
            return
        self.config["music_folder"] = folder
        # Apply preset if selected
        if self.vars.get("use_preset", tk.BooleanVar(value=True)).get():
            self._apply_preset()
        # Mark first run complete
        self.config["first_run_done"] = True
        self.config = normalize_config(self.config)
        if not save_config(self.config):
            messagebox.showerror(
                "Save failed", "Could not save setup settings to config.json.",
                parent=self,
            )
            return
        self.on_complete()
        self.destroy()

    def _skip(self):
        """Close the wizard without completing setup; the app keeps working."""
        if self.reopen:
            self.destroy()
            return
        self.config["first_run_done"] = True
        if not save_config(self.config):
            messagebox.showerror(
                "Save failed", "Could not save setup settings to config.json.",
                parent=self,
            )
            return
        self.on_complete()
        self.destroy()

    def _build_step_library(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)
        box.columnconfigure(1, weight=1)

        ttk.Label(box, text="Welcome to your library workspace", style="Card.TLabel",
                  font=_sfont(11)).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 12))

        ttk.Label(
            box,
            text="Music Library Optimizer only changes files when you run a script. "
                 "The default preset is conservative about metadata, keeps "
                 "processing repeatable, and can be changed later in Settings.",
            style="Muted.Card.TLabel", wraplength=560, justify=tk.LEFT,
        ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(0, 14))

        ttk.Label(box, text="Music Folder:", style="Card.TLabel").grid(
            row=2, column=0, sticky="w", padx=(0, 8), pady=8)
        folder_var = tk.StringVar(value=self.config.get("music_folder", ""))
        self.vars["music_folder"] = folder_var
        ttk.Entry(box, textvariable=folder_var, width=50).grid(
            row=2, column=1, sticky="ew", pady=8)
        ttk.Button(box, text="Browse…", command=lambda: self._browse(folder_var)).grid(
            row=2, column=2, padx=(8, 0), pady=8)

        ttk.Label(box,
                  text="This should be the root folder containing your artist folders "
                       "(e.g., F:\\Music\\Artists). The app scans recursively.",
                  style="Muted.Card.TLabel", wraplength=500).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))

    def _browse(self, var):
        path = filedialog.askdirectory(parent=self, initialdir=var.get() or "/")
        if path:
            var.set(path)

    def _build_step_preset(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text="Settings Preset", style="Card.TLabel",
                  font=_sfont(11)).pack(anchor="w", pady=(0, 8))

        ttk.Label(box,
                  text="The app comes with a recommended preset (enabled below). "
                       "You can customize any setting later in ⚙ Settings.",
                  style="Muted.Card.TLabel", wraplength=560).pack(anchor="w", pady=(0, 12))

        preset_var = tk.BooleanVar(value=not self.reopen)
        self.vars["use_preset"] = preset_var
        ttk.Checkbutton(box, text="Use recommended preset",
                        variable=preset_var, style="TCheckbutton").pack(anchor="w")

        # Show preset summary
        preset_frame = ttk.Frame(box, style="Card.TFrame", padding=12)
        preset_frame.pack(fill=tk.X, pady=(12, 0))
        ttk.Label(preset_frame, text="Preset includes:", style="Card.TLabel",
                  font=_sfont(9)).pack(anchor="w")
        for line in [
            "• FLAC: Level 8, no seektables, ENCODER tags on",
            "• Images: JPEG XL effort 10, convert to JXL, rename to cover",
            "• Lyrics: Embedded format, clean LRC & embedded",
            "• CUE: Normalize, drop empty/non-standard lines",
            "• MEDIA/SOURCE: Normalize (Digital Media → SOURCE=Digital)",
            "• Audio Audit: Fast scan, all detectors on, cutoff 19600 Hz",
            "• DR & ReplayGain: rsgain + simple-dr-meter loudness tags",
            "• Auto Tagging: ALBUMITUNESADVISORY + INSTRUMENTAL",
            "• Run All: every script (1-8), order configurable later",
            "• Auto-advance: On, Compact UI: Off",
        ]:
            ttk.Label(preset_frame, text=line, style="Muted.Card.TLabel",
                      font=_font(8)).pack(anchor="w")

    def _build_step_deps(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text="External Tools", style="Card.TLabel",
                  font=_sfont(11)).pack(anchor="w", pady=(0, 8))

        ttk.Label(box,
                  text="The app downloads required tools automatically on first use "
                       "(all pinned to exact versions). Manage them anytime from the "
                       "sidebar → MANAGE → Dependencies.",
                  style="Muted.Card.TLabel", wraplength=560).pack(anchor="w", pady=(0, 12))

        tools = [
            ("FLAC", "flac.exe / metaflac.exe — FLAC encoding & tag editing"),
            ("libjxl", "cjxl.exe / djxl.exe — JPEG XL conversion"),
            ("libjpeg-turbo", "jpegtran.exe — JPEG lossless optimization"),
            ("oxipng", "oxipng.exe — PNG lossless optimization"),
            ("AudioAuditor", "AudioAuditorCLI.exe — Audio integrity audit"),
            ("rsgain", "rsgain.exe — ReplayGain calculation"),
            ("ffmpeg", "ffmpeg.exe / ffprobe.exe — audio decode for DR"),
            ("simple-dr-meter", "Python DR meter (needs numpy + chardet)"),
        ]
        for name, desc in tools:
            row = ttk.Frame(box, style="Card.TFrame")
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=name, style="Card.TLabel", font=_sfont(9), width=18).pack(side=tk.LEFT)
            ttk.Label(row, text=desc, style="Muted.Card.TLabel", font=_font(8)).pack(side=tk.LEFT)

    def _build_step_ready(self):
        box = ttk.Frame(self.content, style="Card.TFrame", padding=16)
        box.pack(fill=tk.BOTH, expand=True)

        ttk.Label(box, text="You're all set!", style="Card.TLabel",
                  font=_sfont(14), foreground=GREEN).pack(anchor="w", pady=(0, 16))

        ttk.Label(box,
                  text="Click Finish to save your settings and open the main window. "
                       "You can change anything later via ⚙ Settings or the sidebar.",
                  style="Muted.Card.TLabel", wraplength=560).pack(anchor="w")

        self.next_btn.configure(state=tk.HIDDEN)
        self.finish_btn.configure(state=tk.NORMAL)

    def _apply_preset(self):
        """Apply the recommended preset (excluding user-specific paths)."""
        # User-specific keys to NOT overwrite
        user_keys = {
            "music_folder", "mp3tag_path", "picard_path", "foobar2000_path",
            "last_update_check", "first_run_done",
        }
        for key, value in DEFAULT_CONFIG.items():
            if key not in user_keys:
                self.config[key] = value
        # Ensure encoder_tags preset is applied
        self.config["encoder_tags"] = normalize_config({
            "encoder_tags": DEFAULT_CONFIG["encoder_tags"]
        })["encoder_tags"]
        # Run all order preset
        self.config["run_all_order"] = DEFAULT_CONFIG["run_all_order"].copy()

