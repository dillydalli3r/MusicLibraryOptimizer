"""Theme engine: palettes, full-application QSS, custom accents and
Windows DWM title-bar coloring (light/dark caption + accent border).

One Theme instance (THEME) is shared app-wide. Widgets recolor by
connecting to THEME.changed; top-level windows get their native chrome
re-applied automatically via register_window().
"""
import ctypes
import os
import sys
import weakref

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

IS_WINDOWS = sys.platform == "win32"

# --------------------------------------------------------------------------
# Palettes
# --------------------------------------------------------------------------
DARK = {
    "window": "#0e0f14",
    "sidebar": "#0a0b0f",
    "panel": "#14161d",
    "card": "#171a22",
    "console_bg": "#0b0c11",
    "field": "#1e222d",
    "border": "#262b38",
    "border_strong": "#3a4152",
    "text": "#e7eaf2",
    "bright": "#ffffff",
    "muted": "#8d95a8",
    "faint": "#5f6678",
    "hover": "#222734",
    "pressed": "#2b3140",
    "row_hover": "#1b1f2a",
    "row_sel": "#242b3d",
    "danger": "#e06c75",
    "success": "#8ccf6a",
    "warning": "#d8b25e",
    "info": "#7aa7f5",
    # Library row states (grade x audit): (background, foreground)
    "row_pass": ("#15251c", "#96d98a"),
    "row_audited": ("#231a38", "#c4a6f7"),
    "row_both": ("#12233d", "#8fb8f0"),
    "row_mixed": ("#2a2415", "#e0c584"),
    "row_fail": ("#2d171b", "#ef8f9a"),
}

LIGHT = {
    "window": "#f3f4f8",
    "sidebar": "#ffffff",
    "panel": "#ffffff",
    "card": "#ffffff",
    "console_bg": "#ffffff",
    "field": "#ffffff",
    "border": "#d9dde6",
    "border_strong": "#bfc6d4",
    "text": "#1c2130",
    "bright": "#000000",
    "muted": "#667085",
    "faint": "#98a0b0",
    "hover": "#edeff5",
    "pressed": "#e2e6ef",
    "row_hover": "#eff1f6",
    "row_sel": "#e3e8fb",
    "danger": "#c2344a",
    "success": "#237a33",
    "warning": "#9a6c0a",
    "info": "#2563c9",
    "row_pass": ("#e4f3e1", "#1e6b2e"),
    "row_audited": ("#efe7fb", "#6b3fd4"),
    "row_both": ("#e3edfb", "#2456a8"),
    "row_mixed": ("#fbf2dc", "#8a6410"),
    "row_fail": ("#fbe5e7", "#b32435"),
}

PALETTES = {"dark": DARK, "light": LIGHT}

DEFAULT_ACCENT = {"dark": "#8b5cf6", "light": "#6d28d9"}

ACCENT_PRESETS = [
    ("Violet", "#8b5cf6"),
    ("Indigo", "#6366f1"),
    ("Blue", "#3b82f6"),
    ("Teal", "#14b8a6"),
    ("Green", "#22a55c"),
    ("Amber", "#f59e0b"),
    ("Rose", "#f43f5e"),
    ("Pink", "#ec4899"),
]


# --------------------------------------------------------------------------
# Color helpers
# --------------------------------------------------------------------------
def _rgb(hexstr):
    h = hexstr.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex(r, g, b):
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, round(r))),
        max(0, min(255, round(g))),
        max(0, min(255, round(b))),
    )


def blend(c1, c2, t):
    """Blend two #rrggbb colors; t=0 -> c1, t=1 -> c2."""
    r1, g1, b1 = _rgb(c1)
    r2, g2, b2 = _rgb(c2)
    return _hex(r1 + (r2 - r1) * t, g1 + (g2 - g1) * t, b1 + (b2 - b1) * t)


def lighten(c, t):
    r, g, b = _rgb(c)
    return _hex(r + (255 - r) * t, g + (255 - g) * t, b + (255 - b) * t)


def darken(c, t):
    r, g, b = _rgb(c)
    return _hex(r * (1 - t), g * (1 - t), b * (1 - t))


def luminance(c):
    r, g, b = _rgb(c)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255.0


def on_color(c):
    """Readable text color on top of the given background."""
    return "#ffffff" if luminance(c) < 0.55 else "#101014"


def colorref(hexstr):
    """Windows COLORREF is 0x00BBGGRR."""
    r, g, b = _rgb(hexstr)
    return r | (g << 8) | (b << 16)


# --------------------------------------------------------------------------
# System theme detection (Windows personalization)
# --------------------------------------------------------------------------
def system_prefers_dark():
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return value == 0
    except OSError:
        return True


# --------------------------------------------------------------------------
# QSS checkmark asset (generated once next to the exe / source tree)
# --------------------------------------------------------------------------
def _ensure_assets():
    """Tiny PNGs used by the stylesheet (checkbox check mark)."""
    from PySide6.QtCore import Qt, QRect
    from PySide6.QtGui import QImage, QPainter, QColor, QPen, QBrush

    cache = os.path.join(
        os.environ.get("TEMP") or os.getcwd(), "mlo_qss_assets")
    os.makedirs(cache, exist_ok=True)
    check = os.path.join(cache, "check.png")

    if not os.path.isfile(check):
        img = QImage(32, 32, QImage.Format.Format_ARGB32)
        img.fill(Qt.transparent)
        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.setPen(QPen(QColor("#ffffff"), 5.5, Qt.PenStyle.SolidLine,
                      Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.drawLine(8, 17, 14, 23)
        p.drawLine(14, 23, 25, 9)
        p.end()
        img.save(check)

    return cache


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------
class Theme(QObject):
    """Live theme state: mode (dark/light/system), custom accent color."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mode = "dark"
        self._accent = ""
        self._palette = {}
        self._windows = []          # weakrefs of chrome-managed widgets
        self.apply_settings("dark", "")

    # -- setup ------------------------------------------------------------
    def apply_settings(self, mode, accent):
        self._mode = mode if mode in ("dark", "light", "system") else "dark"
        self._accent = accent or ""

        base = PALETTES[self.effective]
        p = dict(base)
        accent = self._accent or DEFAULT_ACCENT[self.effective]

        p["accent"] = accent
        p["accent_hover"] = lighten(accent, 0.12) if self.is_dark() \
            else darken(accent, 0.10)
        p["accent_pressed"] = darken(accent, 0.12) if self.is_dark() \
            else darken(accent, 0.2)
        p["accent_text"] = on_color(accent)
        p["accent_dim"] = blend(p["window"], accent, 0.16)
        p["accent_tint"] = blend(p["window"], accent, 0.30)
        p["accent_row"] = blend(p["window"], accent, 0.22)

        # Buttons sit slightly above cards.
        p["button"] = blend(p["card"], p["bright"], 0.045) if self.is_dark() \
            else "#ffffff"
        self._palette = p

    @property
    def effective(self):
        if self._mode == "system":
            return "dark" if system_prefers_dark() else "light"
        return self._mode

    def is_dark(self):
        return self.effective == "dark"

    def c(self, key):
        return self._palette[key]

    def palette(self):
        return self._palette

    # -- application --------------------------------------------------------
    def apply(self, app):
        self.apply_settings(self._mode, self._accent)
        app.setStyleSheet(self.qss(app))
        app.setPalette(self.qpalette())
        self.refresh_chrome()
        self.changed.emit()

    def qpalette(self):
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window, QColor(self.c("window")))
        p.setColor(QPalette.ColorRole.Base, QColor(self.c("card")))
        p.setColor(QPalette.ColorRole.AlternateBase, QColor(self.c("console_bg")))
        p.setColor(QPalette.ColorRole.Text, QColor(self.c("text")))
        p.setColor(QPalette.ColorRole.WindowText, QColor(self.c("text")))
        p.setColor(QPalette.ColorRole.ButtonText, QColor(self.c("text")))
        p.setColor(QPalette.ColorRole.Highlight, QColor(self.c("accent")))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(self.c("accent_text")))
        p.setColor(QPalette.ColorRole.ToolTipBase, QColor(self.c("panel")))
        p.setColor(QPalette.ColorRole.ToolTipText, QColor(self.c("text")))
        p.setColor(QPalette.ColorRole.PlaceholderText, QColor(self.c("faint")))
        return p

    # -- native chrome -------------------------------------------------------
    def register_window(self, widget):
        self._windows.append(weakref.ref(widget))
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() == QEvent.Type.Show:
            apply_win_chrome(obj, self)
        return False

    def refresh_chrome(self):
        for ref in list(self._windows):
            w = ref()
            if w is None:
                self._windows.remove(ref)
            else:
                apply_win_chrome(w, self)

    # -- stylesheet ------------------------------------------------------------
    def qss(self, app):
        p = self._palette
        assets = _ensure_assets()
        check_url = os.path.join(assets, "check.png").replace("\\", "/")

        # Font stacks via app font; QSS only adjusts weight/size hints.
        return f"""
* {{
    outline: none;
}}
QWidget {{
    background-color: {p['window']};
    color: {p['text']};
    selection-background-color: {p['accent']};
    selection-color: {p['accent_text']};
}}
QToolTip {{
    background-color: {p['panel']};
    color: {p['text']};
    border: 1px solid {p['border_strong']};
    padding: 6px 10px;
}}

/* ---------- structural frames ---------- */
#Sidebar {{
    background-color: {p['sidebar']};
    border-right: 1px solid {p['border']};
}}
#TopBar {{
    background-color: {p['window']};
    border-bottom: 1px solid {p['border']};
}}
#StatusBar {{
    background-color: {p['panel']};
    border-top: 1px solid {p['border']};
}}
#Card {{
    background-color: {p['card']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
#FilterCard {{
    background-color: {p['card']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QFrame[role="divider"] {{
    background-color: {p['border']};
    max-height: 1px;
    border: none;
}}
QLabel[role="h1"] {{
    color: {p['bright']};
    font-size: 15pt;
    font-weight: 700;
}}
QLabel[role="h2"] {{
    color: {p['text']};
    font-weight: 600;
}}
QLabel[role="section"] {{
    color: {p['faint']};
    font-size: 8pt;
    font-weight: 700;
    letter-spacing: 1px;
}}
QLabel[role="muted"] {{ color: {p['muted']}; }}
QLabel[role="accent"] {{ color: {p['accent']}; }}
QLabel[role="version"] {{
    color: {p['faint']};
    font-size: 8pt;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background-color: {p['button']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: {p['hover']};
    border-color: {p['border_strong']};
}}
QPushButton:pressed {{ background-color: {p['pressed']}; }}
QPushButton:disabled {{
    color: {p['faint']};
    background-color: {p['card']};
    border-color: {p['border']};
}}
QPushButton[variant="accent"] {{
    background-color: {p['accent']};
    color: {p['accent_text']};
    border: 1px solid transparent;
    font-weight: 600;
}}
QPushButton[variant="accent"]:hover {{
    background-color: {p['accent_hover']};
}}
QPushButton[variant="accent"]:pressed {{
    background-color: {p['accent_pressed']};
}}
QPushButton[variant="accent"]:disabled {{
    background-color: {blend(p['accent'], p['window'], 0.55)};
    color: {blend(p['accent_text'], p['window'], 0.5)};
}}
QPushButton[variant="ghost"] {{
    background-color: transparent;
    border: 1px solid transparent;
    color: {p['muted']};
}}
QPushButton[variant="ghost"]:hover {{
    background-color: {p['hover']};
    color: {p['text']};
}}
QPushButton[variant="danger"] {{
    color: {p['danger']};
}}

/* sidebar navigation + script buttons */
QPushButton[role="nav"] {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 9px 12px;
    text-align: left;
    color: {p['muted']};
    font-weight: 600;
}}
QPushButton[role="nav"]:hover {{
    background-color: {p['hover']};
    color: {p['text']};
}}
QPushButton[role="nav"]:checked {{
    background-color: {p['accent_dim']};
    color: {p['bright']};
}}
QPushButton[role="side"] {{
    background-color: transparent;
    border: none;
    border-radius: 8px;
    padding: 8px 12px;
    text-align: left;
    color: {p['text']};
}}
QPushButton[role="side"]:hover {{ background-color: {p['hover']}; }}
QPushButton[role="side"]:pressed {{ background-color: {p['pressed']}; }}
QPushButton[role="side"]:disabled {{ color: {p['faint']}; }}

/* small dense buttons */
QPushButton[variant="small"] {{
    padding: 4px 12px;
    font-size: 9pt;
    border-radius: 6px;
}}
QToolButton {{
    background-color: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 5px 9px;
    color: {p['text']};
}}
QToolButton:hover {{
    background-color: {p['hover']};
    border-color: {p['border']};
}}
QToolButton:pressed {{ background-color: {p['pressed']}; }}

/* ---------- inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background-color: {p['field']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 10px;
}}
QLineEdit:focus {{
    border-color: {p['accent']};
}}
QLineEdit[role="path"] {{
    font-family: "Consolas", "Cascadia Mono", monospace;
}}
QSpinBox, QComboBox {{
    background-color: {p['field']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 5px 10px;
    min-height: 20px;
}}
QSpinBox:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: transparent;
    border: none;
    width: 18px;
}}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox QAbstractItemView {{
    background-color: {p['panel']};
    color: {p['text']};
    border: 1px solid {p['border_strong']};
    border-radius: 8px;
    selection-background-color: {p['accent_dim']};
    selection-color: {p['bright']};
    padding: 4px;
    outline: 0;
}}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid {p['border_strong']};
    background-color: {p['field']};
}}
QCheckBox::indicator:hover {{ border-color: {p['accent']}; }}
QCheckBox::indicator:checked {{
    background-color: {p['accent']};
    border-color: {p['accent']};
    image: url({check_url});
}}
QCheckBox::indicator:disabled {{ border-color: {p['border']}; }}

/* ---------- menus ---------- */
QMenu {{
    background-color: {p['panel']};
    color: {p['text']};
    border: 1px solid {p['border_strong']};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 26px 7px 14px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {p['accent_dim']};
    color: {p['bright']};
}}
QMenu::item:disabled {{ color: {p['faint']}; }}
QMenu::separator {{
    height: 1px;
    background-color: {p['border']};
    margin: 5px 6px;
}}
QMenu::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 5px;
    border: 1px solid {p['border_strong']};
    background-color: {p['field']};
    margin-left: 6px;
}}
QMenu::indicator:checked {{
    background-color: {p['accent']};
    border-color: {p['accent']};
    image: url({check_url});
}}

/* ---------- tree / table ---------- */
QTreeWidget, QTreeView {{
    background-color: {p['console_bg']};
    alternate-background-color: {blend(p['console_bg'], p['bright'], 0.02)};
    border: none;
    border-radius: 0;
}}
QTreeWidget::item {{
    height: 30px;
    border: none;
}}
QTreeWidget::item:hover {{ background-color: {p['row_hover']}; }}
QTreeWidget::item:selected {{ background-color: {p['row_sel']}; }}
QHeaderView::section {{
    background-color: {p['card']};
    color: {p['muted']};
    border: none;
    border-bottom: 1px solid {p['border']};
    border-right: 1px solid {p['border']};
    padding: 8px 10px;
    font-size: 8pt;
    font-weight: 700;
}}
QHeaderView::section:hover {{ color: {p['text']}; }}
QTreeWidget::branch {{
    background-color: transparent;
}}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent;
    width: 11px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background-color: {p['border_strong']};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{ background-color: {p['accent']}; }}
QScrollBar:horizontal {{
    background: transparent;
    height: 11px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background-color: {p['border_strong']};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::handle:horizontal:hover {{ background-color: {p['accent']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0; width: 0; border: none; background: none;
}}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}

/* ---------- progress ---------- */
QProgressBar {{
    background-color: {p['field']};
    border: none;
    border-radius: 4px;
    height: 7px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background-color: {p['accent']};
    border-radius: 4px;
}}

/* ---------- tabs (console dialogs) ---------- */
QTabWidget::pane {{
    border: 1px solid {p['border']};
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {p['muted']};
    padding: 7px 18px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {p['bright']};
    border-bottom: 2px solid {p['accent']};
}}
QTabBar::tab:hover:!selected {{ color: {p['text']}; }}

/* ---------- dialogs ---------- */
QDialog {{
    background-color: {p['window']};
}}
QScrollArea {{
    border: none;
    background-color: transparent;
}}
"""


# --------------------------------------------------------------------------
# Windows DWM title bar
# --------------------------------------------------------------------------
def apply_win_chrome(widget, theme):
    """Color the native title bar to match the theme: immersive dark mode,
    exact caption/background color, title text color and an accent-tinted
    window border. No-ops on non-Windows or old Windows builds."""
    if not IS_WINDOWS:
        return
    try:
        hwnd = int(widget.winId())
    except (TypeError, RuntimeError):
        return

    try:
        dwm = ctypes.windll.dwmapi
        dark = 1 if theme.is_dark() else 0

        # DWMWA_USE_IMMERSIVE_DARK_MODE (20, fallback 19)
        value = ctypes.c_int(dark)
        for attr in (20, 19):
            if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(value), 4) == 0:
                break

        p = theme.palette()
        # DWMWA_CAPTION_COLOR = 35, DWMWA_TEXT_COLOR = 36,
        # DWMWA_BORDER_COLOR = 34 (Windows 11)
        caption = ctypes.c_int(colorref(p["window"]))
        text = ctypes.c_int(colorref(p["text"] if dark else "#1c2130"))
        border = ctypes.c_int(colorref(p["accent_dim"]))
        dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(caption), 4)
        dwm.DwmSetWindowAttribute(hwnd, 36, ctypes.byref(text), 4)
        dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border), 4)
    except Exception:
        pass


# Shared singleton
THEME = Theme()


def apply_app_theme(config):
    """Load theme settings from config and apply to the running app."""
    THEME.apply_settings(config.get("theme", "dark"),
                         config.get("accent_color", ""))
    app = QApplication.instance()
    if app is not None:
        THEME.apply(app)


def set_window_icon(widget):
    from PySide6.QtGui import QIcon
    from mlo.paths import SCRIPT_DIR
    ico = os.path.join(SCRIPT_DIR, "app_icon.ico")
    if os.path.isfile(ico):
        widget.setWindowIcon(QIcon(ico))


def set_appusermodelid():
    """Keep the taskbar entry grouped under our app id with our icon."""
    if IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "MusicLibraryOptimizer.App")
        except Exception:
            pass
