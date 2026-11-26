"""Composition, 16-Step Sequencer & Sound Design Panel — Studio Console Aesthetic."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from core.system_manager import SystemTelemetry
from dashboard.widgets import BarSequencerWidget, HairlineMeter


class MusicPanel(QFrame):
    """Displays recessed OLED Chord/BPM deck, 16-step sequencer, and hairline DSP rack."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConsoleSection")
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        head = QHBoxLayout()
        section_lbl = QLabel("02 / COMPOSITION & DSP")
        section_lbl.setObjectName("SectionTag")
        self.mood_label = QLabel("Dreamy Jazz Chords")
        self.mood_label.setObjectName("SubMeta")
        head.addWidget(section_lbl)
        head.addStretch(1)
        head.addWidget(self.mood_label)
        root.addLayout(head)

        # Dual Recessed OLED Well (Active Chord | Smooth BPM)
        oled = QFrame()
        oled.setObjectName("OledWell")
        ol = QHBoxLayout(oled)
        ol.setContentsMargins(16, 14, 16, 14)
        ol.setSpacing(18)

        chord_col = QVBoxLayout()
        chord_col.setSpacing(4)
        c_tag = QLabel("HARMONY")
        c_tag.setObjectName("TechLabel")
        self.chord_label = QLabel("Dm9")
        self.chord_label.setObjectName("HeroBrass")
        self.key_label = QLabel("D Minor  ·  [60, 62, 64, 65, 69]")
        self.key_label.setObjectName("TechMono")
        chord_col.addWidget(c_tag)
        chord_col.addWidget(self.chord_label)
        chord_col.addWidget(self.key_label)
        ol.addLayout(chord_col, 55)

        vsep = QFrame()
        vsep.setObjectName("VertHairline")
        vsep.setFixedWidth(1)
        ol.addWidget(vsep)

        bpm_col = QVBoxLayout()
        bpm_col.setSpacing(4)
        b_tag = QLabel("TEMPO")
        b_tag.setObjectName("TechLabel")
        self.bpm_label = QLabel("74.0")
        self.bpm_label.setObjectName("HeroBone")
        self.vol_lvl_label = QLabel("BPM  ·  VOL LOW  ·  TGT 74.0")
        self.vol_lvl_label.setObjectName("TechMono")
        bpm_col.addWidget(b_tag)
        bpm_col.addWidget(self.bpm_label)
        bpm_col.addWidget(self.vol_lvl_label)
        ol.addLayout(bpm_col, 45)
        root.addWidget(oled)

        # 16-Step Hardware Arrangement Sequencer
        seq_head = QHBoxLayout()
        self.section_label = QLabel("INTRO")
        self.section_label.setObjectName("SectionReadout")
        self.bar_label = QLabel("BAR 01 / 16   ·   PHRASE 1/4")
        self.bar_label.setObjectName("TechMono")
        seq_head.addWidget(self.section_label)
        seq_head.addStretch(1)
        seq_head.addWidget(self.bar_label)
        root.addLayout(seq_head)

        self.sequencer = BarSequencerWidget()
        root.addWidget(self.sequencer)

        mel_row = QHBoxLayout()
        self.mel_meta = QLabel("CONTOUR: BALANCED   ·   DENSITY: 40%   ·   ARP: 15%")
        self.mel_meta.setObjectName("SubMeta")
        mel_row.addWidget(self.mel_meta)
        mel_row.addStretch(1)
        root.addLayout(mel_row)

        root.addWidget(self._hairline())

        # Monochrome Hairline DSP Rack
        dsp_tag = QLabel("SOUND DESIGN MODULATION")
        dsp_tag.setObjectName("TechLabel")
        root.addWidget(dsp_tag)

        self.cutoff_meter = HairlineMeter("LPF CUTOFF")
        self.reverb_meter = HairlineMeter("REVERB MIX")
        self.delay_meter = HairlineMeter("DELAY FBK")
        self.drum_meter = HairlineMeter("DRUM DRIVE")
        self.bass_meter = HairlineMeter("BASS DEPTH")
        for m in (
            self.cutoff_meter,
            self.reverb_meter,
            self.delay_meter,
            self.drum_meter,
            self.bass_meter,
        ):
            root.addWidget(m)

        root.addWidget(self._hairline())

        # Clean Synth / Kit Patch Summary
        patch_tag = QLabel("ACTIVE PATCH")
        patch_tag.setObjectName("TechLabel")
        self.patch_line_1 = QLabel("HARM :rhodey   ·   MEL :pretty_bell   ·   BASS :sine")
        self.patch_line_1.setObjectName("TechMono")
        self.patch_line_2 = QLabel("KIT  :bd_tek / :sn_dub / :drum_cymbal_closed   ·   ATMO rain_vinyl")
        self.patch_line_2.setObjectName("TechMono")
        root.addWidget(patch_tag)
        root.addWidget(self.patch_line_1)
        root.addWidget(self.patch_line_2)
        root.addStretch(1)

    @staticmethod
    def _hairline() -> QFrame:
        line = QFrame()
        line.setObjectName("Hairline")
        line.setFixedHeight(1)
        return line

    def update_telemetry(self, tel: SystemTelemetry) -> None:
        m = tel.music
        self.mood_label.setText(m.mood)
        self.chord_label.setText(m.chord_name or "--")
        self.key_label.setText(f"{m.musical_key}  ·  {m.chord_notes}")
        self.bpm_label.setText(f"{m.bpm:.1f}")
        self.vol_lvl_label.setText(
            f"BPM  ·  {m.volatility_level.upper()} ({int(m.volatility_norm * 100)}%)  ·  TGT {m.target_bpm:.1f}"
        )

        self.section_label.setText(m.section.value.upper())
        self.bar_label.setText(f"BAR {m.bar_in_cycle:02d} / 16   ·   PHRASE {m.bar_in_phrase}/4")
        self.sequencer.set_bar(m.bar_in_cycle, active=tel.running and not m.paused)

        dir_map = {1: "ASCENDING", -1: "DESCENDING", 0: "ARCH"}
        self.mel_meta.setText(
            f"CONTOUR: {dir_map.get(m.melody_direction, 'ARCH')}   ·   "
            f"DENSITY: {int(m.note_density * 100)}%   ·   "
            f"ARP: {int(m.arpeggio_intensity * 100)}%"
        )

        cutoff_ratio = max(0.0, min(1.0, (m.filter_cutoff - 55.0) / 65.0))
        self.cutoff_meter.set_value(cutoff_ratio, f"{m.filter_cutoff:.0f} MIDI")
        self.reverb_meter.set_value(m.reverb_amount, f"{int(round(m.reverb_amount * 100))}%")
        self.delay_meter.set_value(m.delay_feedback, f"{int(round(m.delay_feedback * 100))}%")
        self.drum_meter.set_value(m.drum_intensity, f"{int(round(m.drum_intensity * 100))}%")
        self.bass_meter.set_value(m.bass_energy, f"{int(round(m.bass_energy * 100))}%")

        self.patch_line_1.setText(
            f"HARM :{m.synths.get('harmony', 'rhodey')}   ·   "
            f"MEL :{m.synths.get('melody', 'pretty_bell')}   ·   "
            f"BASS :{m.synths.get('bass', 'sine')}"
        )
        self.patch_line_2.setText(
            f"KIT  :{m.drum_kit.get('kick', 'bd_tek')} / "
            f":{m.drum_kit.get('snare', 'sn_dub')} / "
            f":{m.drum_kit.get('hat', 'drum_cymbal_closed')}   ·   "
            f"ATMO {m.atmosphere_mode}"
        )
