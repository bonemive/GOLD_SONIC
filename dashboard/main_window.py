"""Main PySide6 Studio Console Window for GOLD SONIC.

Matte graphite & burnished brass hardware aesthetic — flat architectural
1px hairline layout, top tactile transport deck, custom OLED/sequencer/mixer
instruments, real physical LED status rail, and collapsible log drawer.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config_loader import PROJECT_ROOT
from core.system_manager import SystemManager, SystemTelemetry
from dashboard.controls import ControlsPanel
from dashboard.market_panel import MarketPanel
from dashboard.music_panel import MusicPanel
from dashboard.widgets import LedIndicator

HARDWARE_CONSOLE_QSS = """
QMainWindow {
    background-color: #141413;
}
QWidget {
    background-color: transparent;
    color: #ECE8DF;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}
#TopRail {
    background-color: #1A1A18;
    border-bottom: 1px solid #2A2925;
}
#BottomRail {
    background-color: #181816;
    border-top: 1px solid #2A2925;
}
#ConsoleSection {
    background-color: #191917;
    border: none;
}
#OledWell {
    background-color: #0E0E0D;
    border: 1px solid #2A2925;
    border-radius: 3px;
}
#Hairline {
    background-color: #2A2925;
    border: none;
}
#VertHairline {
    background-color: #2A2925;
    border: none;
}
#Wordmark {
    color: #ECE8DF;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 3px;
}
#WordmarkSub {
    color: #7B776D;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
}
#SectionTag {
    color: #8E8A80;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
}
#TechLabel {
    color: #6C685F;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}
#SubMeta {
    color: #8E8A80;
    font-size: 11px;
}
#LedLabel {
    color: #C8C3B8;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
    font-weight: 600;
}
#SymbolTitle {
    color: #ECE8DF;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 1px;
}
#HeroPrice {
    color: #ECE8DF;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 34px;
    font-weight: 700;
    letter-spacing: -0.5px;
}
#HeroBrass {
    color: #D4A853;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 32px;
    font-weight: 700;
}
#HeroBone {
    color: #ECE8DF;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 32px;
    font-weight: 700;
}
#SectionReadout {
    color: #D4A853;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: 1.2px;
}
#TechMono {
    color: #B9B4A8;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
}
#TableMono {
    color: #ECE8DF;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 12px;
    font-weight: 600;
}
#ChannelSynth {
    color: #6C685F;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 10px;
}
QPushButton {
    background-color: #232320;
    color: #DCD7CC;
    border: 1px solid #35342F;
    border-radius: 3px;
    padding: 5px 12px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.6px;
}
QPushButton:hover {
    background-color: #2C2C28;
    border-color: #4A4841;
}
QPushButton:disabled {
    background-color: #181816;
    color: #484640;
    border-color: #242320;
}
#StartBtn {
    background-color: #D4A853;
    color: #141413;
    border: 1px solid #D4A853;
}
#StartBtn:hover {
    background-color: #E0B765;
}
#StartBtn:disabled {
    background-color: #29251D;
    color: #6E5D3B;
    border-color: #3A3224;
}
#StopBtn:hover {
    border-color: #C95B5B;
    color: #E89A9A;
}
#MuteBtn:checked {
    background-color: #3D1F1F;
    color: #E69595;
    border-color: #C95B5B;
}
#GhostBtn {
    background-color: transparent;
    color: #8E8A80;
    border: 1px solid #2A2925;
    padding: 2px 9px;
    font-size: 10px;
}
#GhostBtn:hover {
    color: #ECE8DF;
    border-color: #4A4841;
}
#ChannelToggle {
    background-color: #1A1A18;
    color: #6C685F;
    border: 1px solid #2A2925;
    padding: 2px 4px;
    font-size: 10px;
}
#ChannelToggle:checked {
    background-color: #262219;
    color: #D4A853;
    border: 1px solid #8A6E35;
}
QComboBox {
    background-color: #0E0E0D;
    color: #ECE8DF;
    border: 1px solid #2E2D28;
    border-radius: 3px;
    padding: 5px 8px;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
}
QComboBox::drop-down {
    border: none;
    width: 20px;
}
QComboBox QAbstractItemView {
    background-color: #191917;
    color: #ECE8DF;
    border: 1px solid #35342F;
    selection-background-color: #2F291E;
    selection-color: #D4A853;
}
#MasterFader::groove:horizontal {
    height: 3px;
    background: #2A2925;
}
#MasterFader::sub-page:horizontal {
    background: #D4A853;
}
#MasterFader::handle:horizontal {
    background: #ECE8DF;
    border: 1px solid #141413;
    width: 10px;
    height: 16px;
    margin: -7px 0;
    border-radius: 2px;
}
#ConsoleFader::groove:vertical {
    width: 3px;
    background: #2A2925;
}
#ConsoleFader::add-page:vertical {
    background: #D4A853;
}
#ConsoleFader::sub-page:vertical {
    background: #242320;
}
#ConsoleFader::handle:vertical {
    background: #DCD7CC;
    border: 1px solid #0E0E0D;
    height: 10px;
    width: 22px;
    margin: 0 -10px;
    border-radius: 2px;
}
QPlainTextEdit {
    background-color: #0D0D0C;
    color: #8E8A80;
    border: none;
    border-top: 1px solid #262522;
    font-family: "Consolas", "Cascadia Mono", monospace;
    font-size: 11px;
    padding: 6px 14px;
}
"""


class MainWindow(QMainWindow):
    """Matte Graphite & Burnished Brass Hardware Console GUI for GOLD SONIC."""

    def __init__(self, manager: SystemManager) -> None:
        super().__init__()
        self._manager = manager
        self.setWindowTitle("GOLD SONIC")
        self.resize(1240, 680)
        self.setMinimumSize(1080, 610)
        self.setStyleSheet(HARDWARE_CONSOLE_QSS)

        ico_path = PROJECT_ROOT / "assets" / "gold_sonic.ico"
        if ico_path.exists():
            self.setWindowIcon(QIcon(str(ico_path)))

        self._last_log_count: int = 0
        self._build_ui()

        refresh_ms = int(self._manager.config.get("dashboard", {}).get("refresh_interval_ms", 250))
        self._timer = QTimer(self)
        self._timer.setInterval(max(100, refresh_ms))
        self._timer.timeout.connect(self._refresh_ui)
        self._timer.start()

        self._refresh_ui()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_l = QVBoxLayout(central)
        main_l.setContentsMargins(0, 0, 0, 0)
        main_l.setSpacing(0)

        # 1. Top Hardware Console Rail (Brand + Master Transport)
        top_rail = QFrame()
        top_rail.setObjectName("TopRail")
        top_rail.setFixedHeight(54)
        tl = QHBoxLayout(top_rail)
        tl.setContentsMargins(20, 0, 20, 0)
        tl.setSpacing(12)

        brand = QLabel("GOLD SONIC")
        brand.setObjectName("Wordmark")
        sub = QLabel("// MT5 XAU  ->  SONIC PI 5")
        sub.setObjectName("WordmarkSub")
        tl.addWidget(brand)
        tl.addWidget(sub)
        tl.addStretch(1)

        self.engine_led = LedIndicator("STANDBY")
        tl.addWidget(self.engine_led)
        tl.addSpacing(12)

        self.btn_start = QPushButton("START")
        self.btn_start.setObjectName("StartBtn")
        self.btn_start.setFixedHeight(30)
        self.btn_pause = QPushButton("PAUSE")
        self.btn_pause.setFixedHeight(30)
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setObjectName("StopBtn")
        self.btn_stop.setFixedHeight(30)

        self.btn_start.clicked.connect(self._on_start)
        self.btn_pause.clicked.connect(self._on_toggle_pause)
        self.btn_stop.clicked.connect(self._on_stop)

        tl.addWidget(self.btn_start)
        tl.addWidget(self.btn_pause)
        tl.addWidget(self.btn_stop)
        main_l.addWidget(top_rail)

        # 2. Architectural 3-Column Console Body with 1px Vertical Hairlines
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.market_panel = MarketPanel()
        self.music_panel = MusicPanel()
        self.controls_panel = ControlsPanel(self._manager)
        self.controls_panel.status_message.connect(self._on_status_message)

        sep1 = QFrame()
        sep1.setObjectName("VertHairline")
        sep1.setFixedWidth(1)
        sep2 = QFrame()
        sep2.setObjectName("VertHairline")
        sep2.setFixedWidth(1)

        body.addWidget(self.market_panel, 33)
        body.addWidget(sep1)
        body.addWidget(self.music_panel, 36)
        body.addWidget(sep2)
        body.addWidget(self.controls_panel, 31)
        main_l.addLayout(body, 1)

        # 3. Collapsible Monospace Log Drawer (collapsed by default for clean studio look)
        self.log_console = QPlainTextEdit()
        self.log_console.setReadOnly(True)
        self.log_console.setFixedHeight(110)
        self.log_console.setVisible(False)
        main_l.addWidget(self.log_console)

        # 4. Bottom Hardware LED Status Rail
        bot_rail = QFrame()
        bot_rail.setObjectName("BottomRail")
        bot_rail.setFixedHeight(38)
        bl = QHBoxLayout(bot_rail)
        bl.setContentsMargins(20, 0, 20, 0)
        bl.setSpacing(16)

        self.mt5_led = LedIndicator("MT5 OFF")
        self.sp_led = LedIndicator("SONIC PI OFF")
        self.hb_led = LedIndicator("HB --")
        self.audio_led = LedIndicator("AUDIO INACTIVE")

        self.osc_meta_lbl = QLabel("OSC :4560  ·  0 TX  ·  0.0 Hz")
        self.osc_meta_lbl.setObjectName("TechMono")
        self.sys_meta_lbl = QLabel("CPU 0.0%  ·  0 MB")
        self.sys_meta_lbl.setObjectName("TechMono")

        self.btn_logs = QPushButton("LOGS")
        self.btn_logs.setObjectName("GhostBtn")
        self.btn_logs.setCheckable(True)
        self.btn_logs.setFixedHeight(22)
        self.btn_logs.toggled.connect(self._on_toggle_logs)

        bl.addWidget(self.mt5_led)
        bl.addWidget(self.sp_led)
        bl.addWidget(self.hb_led)
        bl.addWidget(self.audio_led)
        bl.addStretch(1)
        bl.addWidget(self.osc_meta_lbl)
        bl.addWidget(self.sys_meta_lbl)
        bl.addWidget(self.btn_logs)
        main_l.addWidget(bot_rail)

    def _refresh_ui(self) -> None:
        tel: SystemTelemetry = self._manager.get_telemetry()

        # Top transport & engine state LED
        self.btn_start.setEnabled(not tel.running)
        self.btn_stop.setEnabled(tel.running)
        self.btn_pause.setEnabled(tel.running)
        self.btn_pause.setText("RESUME" if tel.music.paused else "PAUSE")

        if not tel.running:
            self.engine_led.set_state("off", "STANDBY")
        elif tel.regime.safe_mode:
            self.engine_led.set_state("warn", "SAFE MODE")
        elif tel.music.paused:
            self.engine_led.set_state("warn", "PAUSED")
        else:
            self.engine_led.set_state("ok", "RUNNING")

        self.market_panel.update_telemetry(tel)
        self.music_panel.update_telemetry(tel)
        self.controls_panel.update_telemetry(tel)

        # Honest Bottom LEDs
        if tel.mt5_status.connected:
            srv = tel.mt5_status.server or "MT5"
            self.mt5_led.set_state("ok", f"MT5 {srv}")
        else:
            self.mt5_led.set_state("err" if tel.running else "off", "MT5 OFF")

        osc = tel.osc_status
        if osc.sonic_pi_connected:
            ver = osc.sonic_pi_version or "SonicPi"
            self.sp_led.set_state("ok", ver.upper())
            self.hb_led.set_state("ok", f"HB #{osc.pongs_received} ({osc.heartbeat_rtt_ms:.0f}ms)")
        else:
            self.sp_led.set_state("warn" if tel.running else "off", "SONIC PI WAIT" if tel.running else "SONIC PI OFF")
            self.hb_led.set_state("off", "HB NO PONG")

        if osc.audio_engine_active:
            self.audio_led.set_state("brass", f"AUDIO ACTIVE · {osc.sonic_pi_active_layers}L · B{osc.sonic_pi_bars_played}")
        else:
            self.audio_led.set_state("off", "AUDIO INACTIVE")

        self.osc_meta_lbl.setText(
            f"OSC :{osc.port}  ·  TX {osc.messages_sent}  ·  LOSS {osc.packet_loss_pct:.0f}%  ·  {tel.snapshot.update_rate_hz:.1f} Hz"
        )
        self.sys_meta_lbl.setText(f"CPU {tel.cpu_percent:.1f}%  ·  {tel.memory_mb:.0f} MB")

        lines = self._manager.get_log_lines()
        if len(lines) != self._last_log_count:
            self._last_log_count = len(lines)
            self.log_console.setPlainText("\n".join(lines[-120:]))
            sb = self.log_console.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _on_start(self) -> None:
        self._manager.start()

    def _on_stop(self) -> None:
        self._manager.stop()

    def _on_toggle_pause(self) -> None:
        if self._manager.get_telemetry().music.paused:
            self._manager.resume_music()
        else:
            self._manager.pause_music()

    def _on_toggle_logs(self, checked: bool) -> None:
        self.log_console.setVisible(checked)

    def _on_status_message(self, msg: str) -> None:
        self.osc_meta_lbl.setText(msg)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._timer.stop()
        self._manager.shutdown()
        event.accept()
