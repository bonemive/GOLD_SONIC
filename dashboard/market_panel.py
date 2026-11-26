"""Market Telemetry Panel — Matte Hardware Instrument Aesthetic for GOLD SONIC."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.market_data import DataQuality
from core.regime_detector import MarketRegime
from core.system_manager import SystemTelemetry
from dashboard.widgets import HairlineMeter, LedIndicator, PriceSparklineWidget

REGIME_ACCENT: dict[MarketRegime, str] = {
    MarketRegime.BULLISH: "#6EBF8B",
    MarketRegime.BEARISH: "#C95B5B",
    MarketRegime.SIDEWAYS: "#D4A853",
    MarketRegime.HIGH_VOLATILITY: "#DF8B4C",
    MarketRegime.COMPRESSION: "#A89F91",
    MarketRegime.MARKET_SHOCK: "#E5B95C",
}


class MarketPanel(QFrame):
    """Recessed OLED price curve, regime telemetry, and hairline quant table."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConsoleSection")
        self._last_symbol: str = ""
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        # Minimal top strip
        head = QHBoxLayout()
        section_lbl = QLabel("01 / MARKET FEED")
        section_lbl.setObjectName("SectionTag")
        self.quality_led = LedIndicator("FEED IDLE")
        head.addWidget(section_lbl)
        head.addStretch(1)
        head.addWidget(self.quality_led)
        root.addLayout(head)

        # Symbol + Live Hero Price
        price_top = QHBoxLayout()
        self.symbol_label = QLabel("GOLD#")
        self.symbol_label.setObjectName("SymbolTitle")
        self.trend_label = QLabel("Awaiting live data")
        self.trend_label.setObjectName("SubMeta")
        price_top.addWidget(self.symbol_label)
        price_top.addStretch(1)
        price_top.addWidget(self.trend_label)
        root.addLayout(price_top)

        self.price_label = QLabel("----.--")
        self.price_label.setObjectName("HeroPrice")
        root.addWidget(self.price_label)

        quote_row = QHBoxLayout()
        quote_row.setSpacing(16)
        self.bid_label = QLabel("BID  --")
        self.bid_label.setObjectName("TechMono")
        self.ask_label = QLabel("ASK  --")
        self.ask_label.setObjectName("TechMono")
        self.spread_label = QLabel("SPD  --")
        self.spread_label.setObjectName("TechMono")
        quote_row.addWidget(self.bid_label)
        quote_row.addWidget(self.ask_label)
        quote_row.addStretch(1)
        quote_row.addWidget(self.spread_label)
        root.addLayout(quote_row)

        # Recessed OLED Sparkline
        self.sparkline = PriceSparklineWidget(maxlen=100)
        root.addWidget(self.sparkline)

        root.addWidget(self._hairline())

        # Market Regime block
        reg_row = QHBoxLayout()
        reg_key = QLabel("REGIME")
        reg_key.setObjectName("TechLabel")
        self.regime_label = QLabel("SIDEWAYS")
        self.regime_label.setObjectName("RegimeReadout")
        self.shock_label = QLabel("SHOCK ARMED")
        self.shock_label.setObjectName("SubMeta")
        reg_row.addWidget(reg_key)
        reg_row.addSpacing(10)
        reg_row.addWidget(self.regime_label)
        reg_row.addStretch(1)
        reg_row.addWidget(self.shock_label)
        root.addLayout(reg_row)

        self.conf_meter = HairlineMeter("CONFIDENCE")
        root.addWidget(self.conf_meter)

        root.addWidget(self._hairline())

        # Flat 2-column architectural indicator table (zero boxed card clutter)
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(8)

        self.atr_val = self._add_row(grid, 0, 0, "ATR 14")
        self.atr_ratio_val = self._add_row(grid, 0, 1, "ATR RATIO")
        self.rsi_val = self._add_row(grid, 1, 0, "RSI 14")
        self.adx_val = self._add_row(grid, 1, 1, "ADX 14")
        self.mom_val = self._add_row(grid, 2, 0, "MOMENTUM")
        self.vol_val = self._add_row(grid, 2, 1, "TICK VOL")
        self.ema20_val = self._add_row(grid, 3, 0, "EMA 20")
        self.ema50_val = self._add_row(grid, 3, 1, "EMA 50")
        self.ema200_val = self._add_row(grid, 4, 0, "EMA 200")
        self.range_val = self._add_row(grid, 4, 1, "COIL RATIO")

        root.addLayout(grid)
        root.addStretch(1)

    @staticmethod
    def _hairline() -> QFrame:
        line = QFrame()
        line.setObjectName("Hairline")
        line.setFixedHeight(1)
        return line

    def _add_row(self, grid: QGridLayout, row: int, col: int, key_text: str) -> QLabel:
        row_box = QHBoxLayout()
        row_box.setContentsMargins(0, 1, 0, 1)
        k = QLabel(key_text)
        k.setObjectName("TechLabel")
        v = QLabel("--")
        v.setObjectName("TableMono")
        v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row_box.addWidget(k)
        row_box.addStretch(1)
        row_box.addWidget(v)
        wrap = QWidget()
        wrap.setLayout(row_box)
        grid.addWidget(wrap, row, col)
        return v

    def update_telemetry(self, tel: SystemTelemetry) -> None:
        snap = tel.snapshot
        feat = tel.features
        reg = tel.regime
        digits = max(2, snap.digits)

        if snap.symbol and snap.symbol != self._last_symbol:
            self._last_symbol = snap.symbol
            self.sparkline.clear()

        self.symbol_label.setText(snap.symbol or "--")
        self.trend_label.setText(reg.trend_label)

        if snap.price > 0.0:
            self.price_label.setText(f"{snap.price:,.{digits}f}")
            self.bid_label.setText(f"BID  {snap.bid:,.{digits}f}")
            self.ask_label.setText(f"ASK  {snap.ask:,.{digits}f}")
            self.spread_label.setText(f"SPD  {snap.spread_points} pt")
            self.sparkline.push_price(snap.price)
        else:
            self.price_label.setText("----.--")
            self.bid_label.setText("BID  --")
            self.ask_label.setText("ASK  --")
            self.spread_label.setText("SPD  --")

        # Honest feed LED
        if snap.quality == DataQuality.OK:
            self.quality_led.set_state("ok", "LIVE FEED")
        elif snap.quality == DataQuality.EXCESSIVE_SPREAD:
            self.quality_led.set_state("warn", "WIDE SPREAD")
        elif not tel.running:
            self.quality_led.set_state("off", "STANDBY")
        else:
            self.quality_led.set_state("err", snap.quality.value.replace("_", " "))

        # Regime text accent
        accent = REGIME_ACCENT.get(reg.regime, "#ECE8DF")
        self.regime_label.setText(reg.regime.value.replace("_", " "))
        self.regime_label.setStyleSheet(f"color: {accent}; font-weight: 700; font-size: 14px;")

        self.conf_meter.set_value(reg.confidence, f"{int(round(reg.confidence * 100))}% · {reg.regime_age_seconds:.0f}s")
        if reg.shock_cooldown_remaining > 0.5:
            self.shock_label.setText(f"COOLDOWN {reg.shock_cooldown_remaining:.0f}s")
        else:
            self.shock_label.setText("SHOCK ARMED")

        if feat.valid:
            self.atr_val.setText(f"{feat.atr_m1:.3f}")
            self.atr_ratio_val.setText(f"{reg.atr_ratio_smooth:.2f}x")
            self.rsi_val.setText(f"{feat.rsi14:.1f}")
            self.adx_val.setText(f"{feat.adx14:.1f}")
            self.mom_val.setText(f"{reg.momentum_smooth:+.2f}")
            self.vol_val.setText(f"{feat.tick_volume:,.0f}")
            self.ema20_val.setText(f"{feat.ema20:,.{digits}f}")
            self.ema50_val.setText(f"{feat.ema50:,.{digits}f}")
            self.ema200_val.setText(f"{feat.ema200:,.{digits}f}")
            self.range_val.setText(f"{feat.range_compression:.2f}x")
        else:
            for lbl in (
                self.atr_val, self.atr_ratio_val, self.rsi_val, self.adx_val,
                self.mom_val, self.vol_val, self.ema20_val, self.ema50_val,
                self.ema200_val, self.range_val,
            ):
                lbl.setText("--")
