import cv2
from typing import Optional, Tuple
import numpy as np


class Camera:
    """Manages webcam capture, frame retrieval, and device cleanup."""

    def __init__(self, camera_index: int = 0) -> None:
        """Initialize camera settings.

        Args:
            camera_index: Device index of the camera (default: 0).
        """
        self.camera_index: int = camera_index
        self._cap: Optional[cv2.VideoCapture] = None

    def start(self) -> bool:
        """Open the camera device.

        Returns:
            True if camera opened successfully, False otherwise.
        """
        # On Windows, cv2.CAP_DSHOW can provide faster init, but default fallback is safe
        self._cap = cv2.VideoCapture(self.camera_index)
        return self.is_opened()

    def is_opened(self) -> bool:
        """Check if camera is currently opened."""
        return self._cap is not None and self._cap.isOpened()

    def read_frame(self) -> Tuple[bool, Optional[np.ndarray]]:
        """Read a single frame from the camera stream.

        Returns:
            A tuple of (success_flag, frame_image).
        """
        if not self.is_opened():
            return False, None

        ret, frame = self._cap.read()
        if not ret or frame is None:
            return False, None

        return True, frame

    def release(self) -> None:
        """Release the camera hardware resources cleanly."""
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def __enter__(self) -> "Camera":
        """Support context manager protocol."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Ensure camera release on context manager exit."""
        self.release()
