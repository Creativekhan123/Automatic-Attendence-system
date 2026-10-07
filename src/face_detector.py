import cv2
import os
from typing import List, Tuple
import numpy as np


class FaceDetector:
    """Detects human faces in images using OpenCV Haar Cascade Classifier."""

    def __init__(self, cascade_path: str = None) -> None:
        """Initialize the Haar Cascade detector.

        Args:
            cascade_path: Optional custom path to cascade XML file.
                          If None, uses cv2.data.haarcascades default.
        """
        if cascade_path is None:
            # First check local src directory
            local_path = os.path.join(os.path.dirname(__file__), "haarcascade_frontalface_default.xml")
            if os.path.exists(local_path):
                cascade_path = local_path
            elif hasattr(cv2, "data") and hasattr(cv2.data, "haarcascades"):
                cascade_path = os.path.join(
                    cv2.data.haarcascades, "haarcascade_frontalface_default.xml"
                )

        if not cascade_path or not os.path.exists(cascade_path):
            raise FileNotFoundError(
                f"Cascade classifier file not found. Checked: {cascade_path}"
            )

        self.face_cascade = cv2.CascadeClassifier(cascade_path)
        if self.face_cascade.empty():
            raise RuntimeError(f"Failed to load Haar Cascade classifier from {cascade_path}")

    def detect_faces(
        self,
        frame: np.ndarray,
        scale_factor: float = 1.1,
        min_neighbors: int = 5,
        min_size: Tuple[int, int] = (40, 40)
    ) -> List[Tuple[int, int, int, int]]:
        """Detect faces in a given frame.

        Args:
            frame: Color or grayscale BGR image as a numpy array.
            scale_factor: Parameter specifying how much the image size is reduced at each image scale.
            min_neighbors: How many neighbors each candidate rectangle should have to retain it.
            min_size: Minimum possible object size. Objects smaller than this are ignored.

        Returns:
            List of detected face bounding boxes formatted as (x, y, w, h).
        """
        if frame is None or frame.size == 0:
            return []

        # Convert to grayscale for Haar Cascade detection
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Detect faces
        faces = self.face_cascade.detectMultiScale(
            gray,
            scaleFactor=scale_factor,
            minNeighbors=min_neighbors,
            minSize=min_size
        )

        # Return as list of (x, y, w, h) tuples
        if len(faces) == 0:
            return []

        return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]
