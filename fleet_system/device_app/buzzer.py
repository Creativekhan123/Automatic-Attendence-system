"""Hardware Buzzer Controller for Attendance Device (Raspberry Pi GPIO).

Supports:
- Raspberry Pi GPIO 23 (Active/Passive buzzer)
- Multiple backends: gpiozero (modern Pi OS), RPi.GPIO (legacy), and winsound/mock fallback for PC
- Asynchronous, non-blocking beeps in background daemon threads so video/AI never stutters
"""

import sys
import time
import logging
import threading
from typing import Optional

logger = logging.getLogger("Buzzer")


class BuzzerController:
    """Non-blocking hardware buzzer controller."""

    def __init__(self, pin: int = 23, enabled: bool = True) -> None:
        """Initialize buzzer on the specified BCM GPIO pin.

        Args:
            pin: BCM GPIO pin number (default: 23, Physical Pin 16 on Pi 40-pin header).
            enabled: Master switch to enable/disable buzzer audio.
        """
        self.pin = pin
        self.enabled = enabled
        self._backend = "mock"
        self._device = None
        self._rpi_gpio = None
        self._lock = threading.Lock()

        if not self.enabled:
            logger.info("Buzzer disabled by configuration.")
            return

        # 1. Try modern gpiozero (preferred on Raspberry Pi OS Bookworm/Bullseye)
        try:
            from gpiozero import OutputDevice  # type: ignore
            self._device = OutputDevice(self.pin, active_high=True, initial_value=False)
            self._backend = "gpiozero"
            logger.info(f"Hardware Buzzer initialized via gpiozero on BCM GPIO {self.pin}.")
            return
        except Exception as e_gpiozero:
            logger.debug(f"gpiozero not available for buzzer: {e_gpiozero}")

        # 2. Try legacy RPi.GPIO
        try:
            import RPi.GPIO as GPIO  # type: ignore
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)
            self._rpi_gpio = GPIO
            self._backend = "rpigpio"
            logger.info(f"Hardware Buzzer initialized via RPi.GPIO on BCM GPIO {self.pin}.")
            return
        except Exception as e_rpigpio:
            logger.debug(f"RPi.GPIO not available for buzzer: {e_rpigpio}")

        # 3. Fallback for Windows or non-RPi desktop environments
        if sys.platform == "win32":
            self._backend = "winsound"
            logger.info("Hardware Buzzer initialized in Windows winsound dev-mode.")
        else:
            self._backend = "mock"
            logger.info(f"Hardware Buzzer running in simulation/mock mode (BCM GPIO {self.pin}).")

    def beep(self, duration: float = 0.18, count: int = 1) -> None:
        """Emit non-blocking audible beep(s) without freezing video or AI frames.

        Args:
            duration: Duration of each beep tone in seconds (default: 0.18s).
            count: Number of beeps (default: 1).
        """
        if not self.enabled:
            return

        threading.Thread(
            target=self._beep_worker,
            args=(duration, count),
            name="BuzzerWorker",
            daemon=True
        ).start()

    def _beep_worker(self, duration: float, count: int) -> None:
        """Background worker executing the physical beep pulse."""
        with self._lock:
            try:
                for i in range(count):
                    if self._backend == "gpiozero" and self._device:
                        self._device.on()
                        time.sleep(duration)
                        self._device.off()
                    elif self._backend == "rpigpio" and self._rpi_gpio:
                        self._rpi_gpio.output(self.pin, self._rpi_gpio.HIGH)
                        time.sleep(duration)
                        self._rpi_gpio.output(self.pin, self._rpi_gpio.LOW)
                    elif self._backend == "winsound":
                        try:
                            import winsound
                            winsound.Beep(2400, int(duration * 1000))
                        except Exception:
                            pass
                    else:
                        logger.info(f"[BUZZER BEEP] Pin {self.pin} triggered ({duration:.2f}s)")

                    if i < count - 1:
                        time.sleep(0.08)  # Pause between multi-beeps
            except Exception as e:
                logger.error(f"Error executing buzzer beep: {e}")

    def cleanup(self) -> None:
        """Safely release GPIO hardware pin on shutdown."""
        with self._lock:
            try:
                if self._backend == "gpiozero" and self._device:
                    self._device.off()
                    self._device.close()
                    self._device = None
                elif self._backend == "rpigpio" and self._rpi_gpio:
                    self._rpi_gpio.output(self.pin, self._rpi_gpio.LOW)
                    self._rpi_gpio.cleanup(self.pin)
                    self._rpi_gpio = None
            except Exception as e:
                logger.debug(f"Error cleaning up buzzer: {e}")
            logger.info("Buzzer resources released cleanly.")
