"""Console output helpers shared by every module."""
import os
from datetime import datetime

# Per-file console lines are used by front-ends that suppress the tqdm
# progress bars (the GUI). The CLI keeps the bars and skips these lines.
_file_lines = False


def set_file_lines(enabled):
    global _file_lines
    _file_lines = bool(enabled)

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"
    CYAN = "\033[96m"
    GREY = "\033[90m"


def c(text, color_code):
    return f"{color_code}{text}{Color.RESET}"


def clear_screen():
    os.system("cls" if os.name == "nt" else "clear")


def log(msg, color=None):
    timestamp = datetime.now().strftime("%H:%M:%S")
    colored_msg = c(msg, color) if color else msg
    print(f"[{c(timestamp, Color.GREY)}] {colored_msg}", flush=True)


def fmt_size(b):
    try:
        b = int(b)
    except Exception:
        b = 0
    return f"{b:,} bytes ({b / 1024.0:,.2f} KB / {b / (1024.0 * 1024.0):,.2f} MB)"


def fmt_short_bytes(b):
    """Compact byte size: '1,234 B' / '12.4 KB' / '3.45 MB'."""
    try:
        b = int(b)
    except Exception:
        b = 0
    if abs(b) >= 1024 * 1024:
        return f"{b / (1024 * 1024):,.2f} MB"
    if abs(b) >= 1024:
        return f"{b / 1024:,.2f} KB"
    return f"{b:,} B"


def log_file_result(name, status, b_rem=0, b_add=0, info=None):
    """One compact line per processed file. status: ok | skip | fail.

    Byte deltas are rendered prominently (bold, colored) so savings and
    removals stand out at a glance. No-op unless set_file_lines(True).
    """
    if not _file_lines:
        return
    base = os.path.basename(str(name))
    if status == "ok":
        net = int(b_rem) - int(b_add)
        if net > 0:
            delta = f"  {c('▼ ' + fmt_short_bytes(net) + ' saved', Color.GREEN)}"
        elif net < 0:
            delta = f"  {c('▲ ' + fmt_short_bytes(-net) + ' added', Color.RED)}"
        else:
            delta = f"  {c('0 B', Color.GREY)}"
        log(f"{c('✓ ', Color.GREEN)}{base}{delta}")
    elif status == "skip":
        note = f" ({info})" if info else ""
        log(f"{c('– ', Color.GREY)}{base}{c(note, Color.GREY)}")
    else:
        log(f"{c('✕ ', Color.RED)}{base}  {c(str(info or 'failed'), Color.RED)}")


def print_separator():
    print(c("-" * 60, Color.GREY), flush=True)


def print_header(title):
    print(c(f"── {title} ", Color.CYAN) + c("─" * max(2, 58 - len(title)), Color.GREY),
          flush=True)


def pause_for_input():
    try:
        input(c("\nPress Enter to continue...", Color.GREY))
    except (EOFError, KeyboardInterrupt):
        pass


def _short_val(v, n=28):
    if v is None:
        return "MISS"
    s = str(v).replace("\n", " ").replace("\r", " ").strip()
    if not s:
        return "MISS"
    return s if len(s) <= n else s[: n - 1] + "…"

