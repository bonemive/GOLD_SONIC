"""5-Channel Vertical Studio Mixer, Preset Selector, and Master Console Controls."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from core.musical_engine import LAYER_NAMES
from core.system_manager import SystemManager, SystemTelemetry
from dashboard.widgets import ChannelStripWidget

SHORT_LABELS: dict[str, str] = {
    "harmony": "HARM",
    "melody": "MEL",
    "bass": "BASS",
    "drums": "DRUM",
    "atmosphere": "ATMO",
}


class ControlsPanel(QFrame):
    """Vertical 5-channel studio mixer console, master fader, style, and symbol controls."""

    status_message = Signal(str)

    def __init__(self, manager: SystemManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self.setObjectName("ConsoleSection")
        self._known_symbols: list[str] = []
        self._strips: dict[str, ChannelStripWidget] = {}
        self._build_ui()
        self._sync_initial_controls()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        section_lbl = QLabel("03 / MIXER & PATCH")
        section_lbl.setObjectName("SectionTag")
        self.btn_reset = QPushButton("RESET BAR")
        self.btn_reset.setObjectName("GhostBtn")
        self.btn_reset.setFixedHeight(24)
        self.btn_reset.clicked.connect(self._on_reset)
        head.addWidget(section_lbl)
        head.addStretch(1)
        head.addWidget(self.btn_reset)
        root.addLayout(head)

        # Style preset & MT5 Symbol clean stacked controls
        sym_lbl = QLabel("MT5 INSTRUMENT")
        sym_lbl.setObjectName("TechLabel")
        root.addWidget(sym_lbl)

        sym_row = QHBoxLayout()
        sym_row.setSpacing(6)
        self.symbol_combo = QComboBox()
        self.symbol_combo.setEditable(True)
        self.btn_apply_symbol = QPushButton("SET")
        self.btn_apply_symbol.setFixedWidth(48)
        self.btn_refresh_symbols = QPushButton("SCAN")
        self.btn_refresh_symbols.setFixedWidth(56)
        sym_row.addWidget(self.symbol_combo, 1)
        sym_row.addWidget(self.btn_apply_symbol)
        sym_row.addWidget(self.btn_refresh_symbols)
        root.addLayout(sym_row)

        self.btn_apply_symbol.clicked.connect(self._on_apply_symbol)
        self.btn_refresh_symbols.clicked.connect(self._on_refresh_symbols)

        style_lbl = QLabel("STYLE PRESET")
        style_lbl.setObjectName("TechLabel")
        root.addWidget(style_lbl)

        self.style_combo = QComboBox()
        self.style_desc = QLabel("")
        self.style_desc.setWordWrap(True)
        self.style_desc.setObjectName("SubMeta")
        root.addWidget(self.style_combo)
        root.addWidget(self.style_desc)
        self.style_combo.currentIndexChanged.connect(self._on_style_changed)

        root.addWidget(self._hairline())

        # Master Output Fader + Mute
        mv_row = QHBoxLayout()
        mv_lbl = QLabel("MASTER OUTPUT")
        mv_lbl.setObjectName("TechLabel")
        self.master_vol_val = QLabel("80%")
        self.master_vol_val.setObjectName("TechMono")
        self.btn_mute = QPushButton("MUTE")
        self.btn_mute.setObjectName("MuteBtn")
        self.btn_mute.setCheckable(True)
        self.btn_mute.setFixedSize(56, 24)
        self.btn_mute.toggled.connect(self._on_mute)
        mv_row.addWidget(mv_lbl)
        mv_row.addStretch(1)
        mv_row.addWidget(self.master_vol_val)
        mv_row.addSpacing(8)
        mv_row.addWidget(self.btn_mute)
        root.addLayout(mv_row)

        self.master_slider = QSlider(Qt.Orientation.Horizontal)
        self.master_slider.setObjectName("MasterFader")
        self.master_slider.setRange(0, 100)
        self.master_slider.setValue(80)
        self.master_slider.valueChanged.connect(self._on_master_volume)
        root.addWidget(self.master_slider)

        root.addWidget(self._hairline())

        # 5-Channel Vertical Studio Mixer Rack
        mix_lbl = QLabel("5-LAYER CONSOLE MIXER")
        mix_lbl.setObjectName("TechLabel")
        root.addWidget(mix_lbl)

        mixer_well = QFrame()
        mixer_well.setObjectName("OledWell")
        mw = QHBoxLayout(mixer_well)
        mw.setContentsMargins(6, 6, 6, 6)
        mw.setSpacing(4)

        for idx, layer in enumerate(LAYER_NAMES):
            strip = ChannelStripWidget(layer, SHORT_LABELS[layer])
            strip.toggled.connect(self._manager.set_layer_enabled)
            strip.volume_changed.connect(self._manager.set_layer_volume)
            mw.addWidget(strip, 1)
            self._strips[layer] = strip
            if idx < len(LAYER_NAMES) - 1:
                sep = QFrame()
                sep.setObjectName("VertHairline")
                sep.setFixedWidth(1)
                mw.addWidget(sep)

        root.addWidget(mixer_well, 1)

    @staticmethod
    def _hairline() -> QFrame:
        line = QFrame()
        line.setObjectName("Hairline")
        line.setFixedHeight(1)
        return line

    def _sync_initial_controls(self) -> None:
        default_style = self._manager.config["musical_engine"].get("default_style", "rainy_night")
        self.style_combo.blockSignals(True)
        selected_idx = 0
        for idx, (pid, preset) in enumerate(self._manager.presets.items()):
            self.style_combo.addItem(str(preset.get("name", pid)), pid)
            if pid == default_style:
                selected_idx = idx
        self.style_combo.setCurrentIndex(selected_idx)
        self.style_combo.blockSignals(False)
        self._update_style_desc()

        tel = self._manager.get_telemetry()
        self._populate_symbols(tel.discovered_symbols, tel.snapshot.symbol)

        mv = int(round(tel.music.master_volume * 100))
        self.master_slider.blockSignals(True)
        self.master_slider.setValue(mv)
        self.master_slider.blockSignals(False)
        self.master_vol_val.setText(f"{mv}%")
        self._sync_layer_strips()

    def _sync_layer_strips(self) -> None:
        settings = self._manager.get_layer_settings()
        for layer, ls in settings.items():
            if layer in self._strips:
                self._strips[layer].set_state(ls.enabled, ls.volume)

    def _populate_symbols(self, symbols: list[str], active: str) -> None:
        clean = list(symbols)
        if active and active not in clean:
            clean.insert(0, active)
        if clean == self._known_symbols:
            return
        self._known_symbols = clean
        current_text = self.symbol_combo.currentText() or active
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        for s in clean:
            self.symbol_combo.addItem(s)
        idx = self.symbol_combo.findText(active or current_text)
        if idx >= 0:
            self.symbol_combo.setCurrentIndex(idx)
        elif active:
            self.symbol_combo.setEditText(active)
        self.symbol_combo.blockSignals(False)

    def update_telemetry(self, tel: SystemTelemetry) -> None:
        if tel.discovered_symbols:
            self._populate_symbols(tel.discovered_symbols, tel.snapshot.symbol)

        m = tel.music
        self._strips["harmony"].set_synth_tag(str(m.synths.get("harmony", "rhodey"))[:7])
        self._strips["melody"].set_synth_tag(str(m.synths.get("melody", "bell"))[:7])
        self._strips["bass"].set_synth_tag(str(m.synths.get("bass", "sine"))[:7])
        self._strips["drums"].set_synth_tag(str(m.drum_kit.get("snare", "sn_dub"))[:7])
        self._strips["atmosphere"].set_synth_tag(str(m.atmosphere_mode.split("_")[0])[:7])

    def set_layer_checked(self, layer: str, checked: bool) -> None:
        if layer in self._strips:
            self._strips[layer].btn_on.setChecked(checked)

    def _on_mute(self, checked: bool) -> None:
        self._manager.set_muted(checked)
        self.btn_mute.setText("MUTED" if checked else "MUTE")
        self.status_message.emit("Audio muted." if checked else "Audio unmuted.")

    def _on_reset(self) -> None:
        self._manager.reset_arrangement()
        self.status_message.emit("Arrangement reset to Bar 01.")

    def _on_master_volume(self, value: int) -> None:
        self.master_vol_val.setText(f"{value}%")
        self._manager.set_master_volume(value / 100.0)

    def _on_style_changed(self) -> None:
        style_id = self.style_combo.currentData()
        if style_id and self._manager.set_style(str(style_id)):
            self._update_style_desc()
            self._sync_layer_strips()
            self.status_message.emit(f"Style preset: {self.style_combo.currentText()}")

    def _update_style_desc(self) -> None:
        style_id = self.style_combo.currentData()
        preset = self._manager.presets.get(str(style_id), {})
        self.style_desc.setText(str(preset.get("description", "")))

    def _on_apply_symbol(self) -> None:
        sym = self.symbol_combo.currentText().strip()
        ok, msg = self._manager.set_symbol(sym)
        if ok:
            self.status_message.emit(f"Instrument switched to {msg}")
        else:
            self.status_message.emit(f"Symbol notice: {msg}")

    def _on_refresh_symbols(self) -> None:
        syms = self._manager.refresh_symbols()
        tel = self._manager.get_telemetry()
        self._populate_symbols(syms, tel.snapshot.symbol)
        self.status_message.emit(f"Scanned MT5: {len(syms)} gold symbols found")
