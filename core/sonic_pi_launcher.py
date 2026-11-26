"""Managed background launcher for Sonic Pi 5.0.0 SuperSonic audio engine.

Allows one-click launch from the Windows Desktop without requiring the user
to manually open Sonic Pi or juggle multiple terminal windows. If Sonic Pi is
already listening on port 4560, it leaves the existing instance untouched.
"""

from __future__ import annotations

import logging
import socket
import subprocess
import sys
import threading
from pathlib import Path

from core.config_loader import PROJECT_ROOT

logger = logging.getLogger("gold_sonic.sp_launcher")

SONIC_PI_RUBY = Path(r"C:\Program Files\Sonic Pi\app\server\native\ruby\bin\ruby.exe")
SONIC_PI_RUNNER = PROJECT_ROOT / "sonic_pi" / "run_sonic_pi_engine.rb"


def is_udp_port_in_use(host: str, port: int) -> bool:
    """Return True if another process (e.g., Sonic Pi GUI) already owns the UDP port."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind((host, port))
        return False
    except OSError:
        return True
    finally:
        sock.close()


class SonicPiProcessManager:
    """Starts and cleanly terminates Sonic Pi 5.0.0 headless audio engine when managed."""

    def __init__(self, host: str = "127.0.0.1", port: int = 4560) -> None:
        self._host = host
        self._port = port
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._managed_by_us: bool = False

    @property
    def is_managed_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def ensure_running(self) -> tuple[bool, str]:
        """Ensure Sonic Pi audio engine is active on the configured OSC port."""
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return True, "Managed Sonic Pi engine already running"

            if is_udp_port_in_use(self._host, self._port):
                self._managed_by_us = False
                msg = f"Existing Sonic Pi detected on {self._host}:{self._port}"
                logger.info(msg)
                return True, msg

            if not SONIC_PI_RUBY.exists():
                msg = f"Sonic Pi 5 Ruby runtime not found at {SONIC_PI_RUBY}"
                logger.warning(msg)
                return False, msg

            if not SONIC_PI_RUNNER.exists():
                msg = f"Sonic Pi runner script not found at {SONIC_PI_RUNNER}"
                logger.warning(msg)
                return False, msg

            log_dir = PROJECT_ROOT / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            sp_log_path = log_dir / "sonic_pi_engine.log"

            creationflags = 0
            if sys.platform == "win32":
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)

            try:
                log_fh = sp_log_path.open("wb")
                self._proc = subprocess.Popen(
                    [str(SONIC_PI_RUBY), str(SONIC_PI_RUNNER)],
                    cwd=str(PROJECT_ROOT),
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                log_fh.close()
                self._managed_by_us = True
                msg = f"Booting Sonic Pi 5.0.0 audio engine (PID {self._proc.pid})..."
                logger.info(msg)
                return True, msg
            except OSError as exc:
                self._proc = None
                self._managed_by_us = False
                msg = f"Failed to launch Sonic Pi engine: {exc}"
                logger.error(msg)
                return False, msg

    def stop(self) -> None:
        """Cleanly shut down Sonic Pi engine (and child SuperSonic/daemon) if we launched it."""
        with self._lock:
            if not self._managed_by_us or self._proc is None:
                return
            pid = self._proc.pid
            try:
                if self._proc.poll() is None:
                    if sys.platform == "win32":
                        # Terminate full process tree (ruby -> daemon -> SuperSonic) cleanly
                        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
                        subprocess.run(
                            ["taskkill", "/PID", str(pid), "/T", "/F"],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=creationflags,
                            timeout=5,
                            check=False,
                        )
                    else:
                        self._proc.terminate()
                        self._proc.wait(timeout=4)
                logger.info("Managed Sonic Pi 5.0.0 audio engine stopped cleanly.")
            except Exception as exc:  # pragma: no cover - defensive cleanup
                logger.debug("Error stopping managed Sonic Pi process: %s", exc)
            finally:
                self._proc = None
                self._managed_by_us = False
