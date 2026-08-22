"""Console page widget: fast colored ANSI log output."""
from PySide6.QtGui import QColor, QFont, QFontDatabase, QTextCharFormat
from PySide6.QtWidgets import (QPlainTextEdit, QVBoxLayout, QHBoxLayout,
                               QLabel, QWidget, QPushButton)

from .theme import THEME
from .widgets import ToggleSwitch, section_label

# ANSI SGR tag -> palette key
TAG_KEYS = {
    "fg": "text",
    "bold": "bright",
    "grey": "muted",
    "red": "danger",
    "green": "success",
    "yellow": "warning",
    "blue": "info",
    "magenta": "text",
    "cyan": "muted",
    "muted": "muted",
}


def pick_monospace():
    fams = set(QFontDatabase.families())
    for name in ("Cascadia Code", "Cascadia Mono", "Consolas",
                 "JetBrains Mono", "Courier New"):
        if name in fams:
            return name
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


class ConsoleEdit(QPlainTextEdit):
    """Append-only log view fed with parsed ANSI segments."""

    MAX_BLOCKS = 20000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setMaximumBlockCount(self.MAX_BLOCKS)
        self._mono = pick_monospace()
        f = QFont(self._mono)
        f.setPointSize(9)
        self.setFont(f)
        self.set_theme(THEME.palette())
        THEME.changed.connect(lambda: self.set_theme(THEME.palette()))

    def set_theme(self, p):
        self.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {p['console_bg']};"
            f" color: {p['text']}; border: none; border-radius: 0;"
            f" padding: 10px 12px; }}"
        )
        self._rebuild_formats(p)
        # History keeps the colors it was written with; new lines use
        # the fresh palette.

    def _rebuild_formats(self, p):
        self._formats = {}
        for tag, key in TAG_KEYS.items():
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(p[key]))
            if tag == "bold":
                f = QFont(self._mono)
                f.setPointSize(9)
                f.setBold(True)
                fmt.setFont(f)
            self._formats[tag] = fmt

    def append_segments(self, segments, newline=True):
        """segments: list[(text, tag)] - one visual line."""
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.beginEditBlock()
        at_end = self.verticalScrollBar().value() >= \
            self.verticalScrollBar().maximum() - 4
        for text, tag in segments:
            if not text:
                continue
            cursor.insertText(text, self._formats.get(tag) or
                              self._formats["fg"])
        if newline:
            cursor.insertBlock()
        cursor.endEditBlock()
        if at_end:
            self.scrollToBottom()

    def scrollToBottom(self):
        sb = self.verticalScrollBar()
        sb.setValue(sb.maximum())

    def copy_all(self):
        self.selectAll()
        self.copy()
        cursor = self.textCursor()
        cursor.clearSelection()
        self.setTextCursor(cursor)


class ConsolePage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(8)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        bar.addWidget(section_label("Console"))

        self.auto_switch = ToggleSwitch(True)
        self.auto_label = QLabel("Auto-scroll")
        self.auto_label.setProperty("role", "muted")

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setProperty("variant", "small")
        self.copy_btn = QPushButton("Copy All")
        self.copy_btn.setProperty("variant", "small")

        bar.addStretch(1)
        bar.addWidget(self.auto_switch)
        bar.addWidget(self.auto_label)
        bar.addSpacing(10)
        bar.addWidget(self.clear_btn)
        bar.addWidget(self.copy_btn)
        layout.addLayout(bar)

        # Card wrapper for the console surface
        from PySide6.QtWidgets import QFrame
        card = QFrame()
        card.setObjectName("Card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(1, 1, 1, 1)
        self.console = ConsoleEdit()
        cl.addWidget(self.console)
        layout.addWidget(card, 1)

        self.clear_btn.clicked.connect(self.console.clear)
        self.copy_btn.clicked.connect(self.console.copy_all)

    def append_segments(self, segments, newline=True):
        self.console.append_segments(segments, newline)
        if self.auto_switch.isChecked():
            self.console.scrollToBottom()

    def append_line(self, text, tag=None):
        self.append_segments([(text, tag or "fg")], newline=True)
