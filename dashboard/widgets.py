"""Custom QPainter hardware-inspired studio widgets for GOLD SONIC.

Designed with Dieter Rams / Elektron / Ableton industrial restraint:
matte graphite plates, crisp 1px hairlines, warm burnished brass indicators,
live sparkline OLED well, 16-step bar sequencer, and vertical channel strips.
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

C_INK = QColor("#0E0E0D")
C_BORDER = QColor("#2A2925")
C_GRID = QColor("#1D1C19")
C_BRASS = QColor("#D4A853")
C_BRASS_DIM = QColor("#6E582C")
C_BRASS_GLOW = QColor(212, 168, 83, 42)
C_BONE = QColor("#ECE8DF")
C_MUTED = QColor("#6C685F")
C_SAGE = QColor("#6EBF8B")
C_AMBER = QColor("#D99B43")
C_RED = QColor("#C95B5B")


class LedIndicator(QWidget):
    """Minimal physical 7px studio LED indicator with crisp label."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#45433E")
        self._label_text = label
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._dot = _LedDot(self)
        self._lbl = QLabel(label)
        self._lbl.setObjectName("LedLabel")
        layout.addWidget(self._dot)
        layout.addWidget(self._lbl)

    def set_state(self, state: str, text: str | None = None) -> None:
        """state: 'ok' | 'warn' | 'err' | 'off' | 'brass'"""
        palette = {
            "ok": C_SAGE,
            "warn": C_AMBER,
            "err": C_RED,
            "brass": C_BRASS,
            "off": QColor("#3E3D39"),
        }
        self._dot.set_color(palette.get(state, palette["off"]))
        if text is not None:
            self._lbl.setText(text)


class _LedDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor("#3E3D39")
        self.setFixedSize(10, 10)

    def set_color(self, color: QColor) -> None:
        if color != self._color:
            self._color = color
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QColor(self._color)
        glow.setAlpha(60)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(0.5, 0.5, 9.0, 9.0))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(2.0, 2.0, 6.0, 6.0))


class PriceSparklineWidget(QWidget):
    """Recessed OLED live price curve for MT5 GOLD#."""

    def __init__(self, maxlen: int = 90, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: deque[float] = deque(maxlen=maxlen)
        self.setMinimumHeight(74)
        self.setMaximumHeight(86)

    def push_price(self, price: float) -> None:
        if price > 0.0:
            self._values.append(price)
            self.update()

    def clear(self) -> None:
        self._values.clear()
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)

        # Recessed OLED well
        p.setPen(QPen(C_BORDER, 1.0))
        p.setBrush(C_INK)
        p.drawRoundedRect(rect, 3.0, 3.0)

        # Subtle horizontal grid hairlines
        p.setPen(QPen(C_GRID, 1.0))
        for frac in (0.25, 0.5, 0.75):
            y = rect.top() + rect.height() * frac
            p.drawLine(QPointF(rect.left() + 1, y), QPointF(rect.right() - 1, y))

        if len(self._values) < 2:
            p.setPen(C_MUTED)
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, "AWAITING LIVE TICKS")
            return

        vals = list(self._values)
        lo = min(vals)
        hi = max(vals)
        span = hi - lo
        if span < 1e-6:
            lo -= 0.5
            hi += 0.5
            span = 1.0

        pad_x = 8.0
        pad_y = 10.0
        w = max(1.0, rect.width() - pad_x * 2)
        h = max(1.0, rect.height() - pad_y * 2)

        pts: list[QPointF] = []
        n = len(vals)
        for i, v in enumerate(vals):
            x = rect.left() + pad_x + (i / (n - 1)) * w
            y = rect.bottom() - pad_y - ((v - lo) / span) * h
            pts.append(QPointF(x, y))

        # Soft brass area fill
        fill_path = QPainterPath()
        fill_path.moveTo(pts[0].x(), rect.bottom() - 2)
        for pt in pts:
            fill_path.lineTo(pt)
        fill_path.lineTo(pts[-1].x(), rect.bottom() - 2)
        fill_path.closeSubpath()

        grad = QLinearGradient(0, rect.top(), 0, rect.bottom())
        grad.setColorAt(0.0, QColor(212, 168, 83, 55))
        grad.setColorAt(1.0, QColor(212, 168, 83, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(grad)
        p.drawPath(fill_path)

        # Crisp brass curve
        line_path = QPainterPath(pts[0])
        for pt in pts[1:]:
            line_path.lineTo(pt)
        p.setPen(QPen(C_BRASS, 1.7))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(line_path)

        # Live head dot
        head = pts[-1]
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(C_BONE)
        p.drawEllipse(head, 2.8, 2.8)


class BarSequencerWidget(QWidget):
    """16-step hardware drum-machine style bar position indicator (4x4 phrase groups)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bar: int = 1
        self._active: bool = False
        self.setFixedHeight(22)

    def set_bar(self, bar_1_to_16: int, active: bool = True) -> None:
        b = max(1, min(16, int(bar_1_to_16)))
        if b != self._bar or active != self._active:
            self._bar = b
            self._active = active
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        group_gap = 8.0
        step_gap = 3.0
        total_gaps = 3 * group_gap + 12 * step_gap
        cell_w = max(4.0, (w - total_gaps) / 16.0)
        cell_h = 10.0
        y = (h - cell_h) * 0.5

        x = 0.0
        for idx in range(16):
            step_num = idx + 1
            rect = QRectF(x, y, cell_w, cell_h)
            if self._active and step_num == self._bar:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(C_BRASS)
            elif self._active and step_num < self._bar:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#5C4A26"))
            else:
                p.setPen(QPen(C_BORDER, 1.0))
                p.setBrush(C_INK)
            p.drawRoundedRect(rect, 1.5, 1.5)

            x += cell_w + (group_gap if (step_num % 4 == 0 and step_num < 16) else step_gap)


class HairlineMeter(QWidget):
    """Ultra-clean 1-line technical parameter bar (replaces chunky QProgressBar)."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ratio: float = 0.0
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 2, 0, 2)
        layout.setSpacing(10)

        self._lbl = QLabel(label)
        self._lbl.setFixedWidth(92)
        self._lbl.setObjectName("TechLabel")

        self._bar = _ThinBar(self)

        self._val = QLabel("--")
        self._val.setFixedWidth(72)
        self._val.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._val.setObjectName("TechMono")

        layout.addWidget(self._lbl)
        layout.addWidget(self._bar, 1)
        layout.addWidget(self._val)

    def set_value(self, ratio: float, text: str) -> None:
        self._bar.set_ratio(ratio)
        self._val.setText(text)


class _ThinBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ratio = 0.0
        self.setFixedHeight(10)

    def set_ratio(self, ratio: float) -> None:
        r = max(0.0, min(1.0, float(ratio)))
        if abs(r - self._ratio) > 0.005:
            self._ratio = r
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        y = (self.height() - 3.0) * 0.5
        w = self.width()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#242320"))
        p.drawRect(QRectF(0, y, w, 3.0))
        if self._ratio > 0.0:
            p.setBrush(C_BRASS)
            p.drawRect(QRectF(0, y, w * self._ratio, 3.0))


class ChannelStripWidget(QWidget):
    """Vertical studio console mixer channel strip for one Sonic Pi audio layer."""

    toggled = Signal(str, bool)
    volume_changed = Signal(str, float)

    def __init__(self, layer_id: str, short_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layer_id = layer_id
        self.setObjectName("ChannelStrip")
        self.setMinimumWidth(68)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 8, 6, 8)
        root.setSpacing(6)
        root.setAlignment(Qt.AlignmentFlag.AlignHCenter)

        self.btn_on = QPushButton(short_name)
        self.btn_on.setObjectName("ChannelToggle")
        self.btn_on.setCheckable(True)
        self.btn_on.setChecked(True)
        self.btn_on.setFixedHeight(24)
        self.btn_on.toggled.connect(self._on_toggled)

        self.val_lbl = QLabel("75")
        self.val_lbl.setObjectName("TechMono")
        self.val_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setObjectName("ConsoleFader")
        self.slider.setRange(0, 100)
        self.slider.setValue(75)
        self.slider.setMinimumHeight(124)
        self.slider.valueChanged.connect(self._on_vol)

        self.synth_lbl = QLabel("--")
        self.synth_lbl.setObjectName("ChannelSynth")
        self.synth_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        root.addWidget(self.btn_on)
        root.addWidget(self.val_lbl)
        root.addWidget(self.slider, 1, Qt.AlignmentFlag.AlignHCenter)
        root.addSpacing(4)
        root.addWidget(self.synth_lbl)

    def set_state(self, enabled: bool, volume: float) -> None:
        self.btn_on.blockSignals(True)
        self.btn_on.setChecked(enabled)
        self.btn_on.blockSignals(False)

        v = int(round(max(0.0, min(1.0, volume)) * 100))
        self.slider.blockSignals(True)
        self.slider.setValue(v)
        self.slider.blockSignals(False)
        self.val_lbl.setText(f"{v}")

    def set_synth_tag(self, tag: str) -> None:
        self.synth_lbl.setText(tag)

    def _on_toggled(self, checked: bool) -> None:
        self.toggled.emit(self._layer_id, checked)

    def _on_vol(self, value: int) -> None:
        self.val_lbl.setText(f"{value}")
        self.volume_changed.emit(self._layer_id, value / 100.0)
