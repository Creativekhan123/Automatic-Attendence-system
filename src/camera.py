import cv2
import threading
import time
from typing import Optional, Tuple
import numpy as np


class Camera:
    """Manages webcam capture, frame retrieval, and device cleanup.
    
    Includes a background daemon capture thread to eliminate buffer lag,
    providing non-blocking, zero-latency access to the latest video frame.
    """

    def __init__(self, camera_index: int = 0) -> None:
        """Initialize camera settings.

        Args:
            camera_index: Device index of the camera (default: 0).
        """
        self.camera_index: int = camera_index
        self._cap: Optional[cv2.VideoCapture] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running: bool = False
        self._latest_frame: Optional[np.ndarray] = None
        self._has_frame: bool = False

    def start(self) -> bool:
        """Open the camera device and start background capture thread.

        Returns:
            True if camera opened successfully, False otherwise.
        """
        # On Windows, cv2.CAP_DSHOW can provide faster init, but default fallback is safe
        self._cap = cv2.VideoCapture(self.camera_index)
        if not self.is_opened():
            return False

        # Set optimal hardware capture properties for speed & low bus bandwidth
        try:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            self._cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
            self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Warm-up grab
        ret, frame = self._cap.read()
        if ret and frame is not None:
            self._latest_frame = frame
            self._has_frame = True

        # Start background capture thread
        self._running = True
        self._thread = threading.Thread(target=self._capture_worker, daemon=True)
        self._thread.start()
        return True

    def _capture_worker(self) -> None:
        """Continuously pulls frames into the atomic buffer to eliminate backlog lag."""
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                time.sleep(0.02)
                continue

            ret, frame = self._cap.read()
            if ret and frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._has_frame = True
            else:
                time.sleep(0.01)

    def is_opened(self) -> bool:
        """Check if camera is currently opened."""
        return self._cap is not None and self._cap.isOpened()

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read the freshest frame from the camera stream with zero buffer delay.

        Returns:
            A tuple of (success_flag, frame_image).
        """
        if not self.is_opened():
            return False, None

        with self._lock:
            if self._has_frame and self._latest_frame is not None:
                # Return a copy to prevent race conditions during frame drawing
                return True, self._latest_frame.copy()

        # Fallback to direct read if worker hasn't grabbed first frame yet
        if self._cap is not None:
            ret, frame = self._cap.read()
            return ret, frame

        return False, None

    def release(self) -> None:
        """Release the camera hardware resources cleanly."""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            try:
                self._thread.join(timeout=0.5)
            except Exception:
                pass
            self._thread = None

        if self._cap is not None:
            self._cap.release()
            self._cap = None

        with self._lock:
            self._latest_frame = None
            self._has_frame = False

    def __enter__(self) -> "Camera":
        """Support context manager protocol."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensure camera release on context manager exit."""
        self.release()
