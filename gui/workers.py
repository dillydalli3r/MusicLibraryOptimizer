"""Background workers: ANSI stdout capture and the script-run thread."""
import io
import re
import sys
import threading
import time
import traceback

from PySide6.QtCore import QObject, Signal

from mlo import stats as stats_mod
from mlo.ui import set_file_lines

ANSI_TAG = {
    "0": "fg", "1": "bold", "90": "grey", "91": "red", "92": "green",
    "93": "yellow", "94": "blue", "95": "magenta", "96": "cyan",
}
ANSI_RE = re.compile(r"\x1b\[([0-9;]*)m")
ANSI_PARTIAL_RE = re.compile(r"\x1b\[([0-9;]*)$")


class AnsiStream(io.TextIOBase):
    """sys.stdout replacement: parses ANSI colors, emits Qt signals.

    Emits ("out", [(text, tag), ...]) and ("nl", None) events through
    `sig_output`; thread-safe (signals are queued to the receiver).
    """

    def __init__(self, sig_output):
        super().__init__()
        self.sig_output = sig_output
        self.buf = ""
        self.tag = "fg"
        self._line_pending = False
        self._lock = threading.Lock()

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        with self._lock:
            return self._write_locked(s)

    def _write_locked(self, s):
        if not s:
            self.sig_output.emit(("nl", None))
            return 0
        if s == "\n":
            if self._line_pending:
                self._line_pending = False
                return len(s)
            self.sig_output.emit(("nl", None))
            return len(s)

        self.buf += s.replace("\r\n", "\n").replace("\r", "")

        # Hold back a trailing incomplete escape sequence.
        hold = ""
        m = ANSI_PARTIAL_RE.search(self.buf)
        if m:
            hold = m.group(0)
            self.buf = self.buf[:m.start()]

        segments = []
        pos = 0
        for m2 in ANSI_RE.finditer(self.buf):
            if m2.start() > pos:
                segments.append((self.buf[pos: m2.start()], self.tag))
            codes = [c for c in m2.group(1).split(";") if c]
            new_tag = "fg"
            for code in codes:
                if code in ANSI_TAG:
                    new_tag = ANSI_TAG[code]
            self.tag = new_tag
            pos = m2.end()

        if pos < len(self.buf):
            segments.append((self.buf[pos:], self.tag))

        self.buf = hold
        if segments:
            self._line_pending = True
            self.sig_output.emit(("out", segments))
        return len(s)

    def flush(self):
        pass

    def writable(self):
        return True


SCRIPT_NAMES = {
    1: "Format Lyrics",
    2: "Format CUEs",
    3: "Optimize FLACs",
    4: "Grade Library",
    5: "Process Images",
    6: "Audit Library",
    7: "DR & ReplayGain",
    8: "Auto Tagging",
}


class ScriptRunner(QObject):
    """Runs the selected scripts off the UI thread.

    All UI feedback flows through signals; nothing here touches widgets.
    """

    sig_output = Signal(tuple)        # ("out", segments) | ("nl", None)
    sig_progress = Signal(int, int, str)
    sig_status = Signal(str)
    sig_pause = Signal(str)
    sig_done = Signal(float)

    def __init__(self, runners, config, script_ids, title, targets,
                 force_flac=False, force_images=False, force_audit=False):
        super().__init__()
        self.runners = runners
        self.config = config
        self.script_ids = list(script_ids)
        self.title = title
        self.targets = targets
        self.force_flac = force_flac
        self.force_images = force_images
        self.force_audit = force_audit
        self.continue_event = threading.Event()
        self.continue_event.set()
        self.abort_flag = False

    def proceed(self):
        self.continue_event.set()

    def abort(self):
        """Stop after the current script (also releases any pause)."""
        self.abort_flag = True
        self.continue_event.set()

    def run(self):
        from mlo.report import (print_results, print_grade_results,
                                print_combined_results)

        started = time.monotonic()
        prev_tqdm, prev_hook = stats_mod.tqdm, stats_mod.progress_hook
        stats_mod.tqdm = None
        stats_mod.progress_hook = lambda done, total, desc: \
            self.sig_progress.emit(done, total, desc)
        set_file_lines(True)

        stream = AnsiStream(self.sig_output)
        real_out, real_err = sys.stdout, sys.stderr
        sys.stdout = stream
        sys.stderr = stream

        run_cfg = self.config
        if self.targets or self.force_flac or self.force_images \
                or self.force_audit:
            run_cfg = self.config.copy()
            if self.targets:
                run_cfg["targets"] = list(self.targets)
            if self.force_flac:
                run_cfg["force_reencode_flac"] = True
            if self.force_images:
                run_cfg["force_reencode_images"] = True
            if self.force_audit:
                run_cfg["force_audit"] = True

        def emit_log(msg, tag=None):
            self.sig_output.emit(("out", [(msg, tag or "fg")]))

        per_script = []
        all_errors = []

        try:
            emit_log("")
            emit_log("─" * 74, "muted")
            emit_log(self.title, "bold")
            emit_log("Scripts: " + " → ".join(
                SCRIPT_NAMES[s] for s in self.script_ids), "muted")
            if self.targets:
                emit_log(f"Targets: {len(self.targets)} selected item(s)",
                         "muted")
            emit_log("─" * 74, "muted")

            for i, script_id in enumerate(self.script_ids):
                if self.abort_flag:
                    emit_log("Run aborted by user.", "yellow")
                    break

                name, runner = self.runners[script_id]

                if i > 0 and not run_cfg.get("auto_advance", True):
                    self.continue_event.clear()
                    self.sig_pause.emit(name)
                    emit_log(f"⏸ Paused before {name} (Auto-Advance is off)",
                             "yellow")
                    self.continue_event.wait()

                emit_log("")
                emit_log(f"▶ Starting {name}", "blue")

                try:
                    s = runner(run_cfg)
                except Exception as e:
                    emit_log(f"FATAL in {name}: {e}", "red")
                    traceback.print_exc(file=stream)
                    s = {
                        "total_scanned": 0, "modified_count": 0,
                        "unchanged_count": 0, "skipped_count": 0,
                        "error_count": 1, "total_bytes_added": 0,
                        "total_bytes_removed": 0,
                        "errors": [(name, str(e))],
                    }

                per_script.append((name, s))

                if not s.get("is_grader"):
                    all_errors.extend(s.get("errors", []))

                if s.get("is_grader"):
                    print_grade_results(s, title=f"RESULTS — {name}")
                else:
                    print_results(s, title=f"RESULTS — {name}")

            if len(self.script_ids) > 1:
                print_combined_results(
                    per_script, title="COMBINED RESULTS — ALL SCRIPTS")
                if all_errors:
                    emit_log("Errors:", "red")
                    for path, err in all_errors[:50]:
                        emit_log(f"  - {path}", "red")
                        emit_log(f"      {err}", "red")
                    if len(all_errors) > 50:
                        emit_log(
                            f"  … and {len(all_errors) - 50} more.", "red")

            elapsed = time.monotonic() - started
            emit_log("")
            emit_log(f"✔ {self.title} completed in {elapsed:.1f}s", "green")

        except Exception:
            traceback.print_exc(file=stream)
        finally:
            sys.stdout, sys.stderr = real_out, real_err
            stats_mod.tqdm, stats_mod.progress_hook = prev_tqdm, prev_hook
            set_file_lines(False)
            self.sig_done.emit(time.monotonic() - started)
