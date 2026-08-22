"""Custom widgets shared across the GUI: animated toggle switch, small
building blocks."""
from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt, QSize
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QAbstractButton, QWidget, QLabel, QHBoxLayout

from .theme import THEME, blend


class ToggleSwitch(QAbstractButton):
    """Pill-style boolean toggle with a sliding, animated knob."""

    def __init__(self, checked=False, parent=None, scale=1.0):
        super().__init__(parent)
        self._pos = 1.0 if checked else 0.0
        self._scale = scale
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._anim = QPropertyAnimation(self, b"knobPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(int(44 * self._scale), int(24 * self._scale))

    def _animate(self, checked):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def get_knobPos(self):
        return self._pos

    def set_knobPos(self, v):
        self._pos = v
        self.update()

    knobPos = Property(float, get_knobPos, set_knobPos)

    def paintEvent(self, _):
        p = THEME.palette()
        w, h = self.width(), self.height()
        margin = 3
        track_h = h - margin * 2
        radius = track_h / 2

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_off = p["border_strong"]
        track = blend(track_off, p["accent"], self._pos)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(margin, margin, w - margin * 2, track_h,
                                radius, radius)

        knob_d = track_h - 4
        travel = (w - margin * 2) - knob_d - 2
        kx = margin + 1 + travel * self._pos
        painter.setBrush(QColor(p["bright"] if THEME.is_dark() else "#ffffff"))
        painter.drawEllipse(int(kx), margin + 2, int(knob_d), int(knob_d))
        painter.end()

    def hitButton(self, pos):
        return self.rect().contains(pos)


class SwitchRow(QWidget):
    """A labeled toggle: [Switch] Label  (or Label [Switch] if trailing)."""

    def __init__(self, text, checked=False, parent=None, trailing=True,
                 on_change=None):
        super().__init__(parent)
        self.switch = ToggleSwitch(checked)
        self.label = QLabel(text)
        self.label.setProperty("role", "muted")
        if on_change:
            self.switch.toggled.connect(on_change)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        if trailing:
            lay.addWidget(self.switch)
            lay.addWidget(self.label)
            lay.addStretch(1)
        else:
            lay.addWidget(self.label)
            lay.addStretch(1)
            lay.addWidget(self.switch)


def section_label(text, parent=None):
    lbl = QLabel(text.upper(), parent)
    lbl.setProperty("role", "section")
    return lbl


def make_h1(text, parent=None):
    lbl = QLabel(text, parent)
    lbl.setProperty("role", "h1")
    return lbl
