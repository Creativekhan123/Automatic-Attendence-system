"""Ultra-Fast YuNet Face Detector for Raspberry Pi 4.

Leverages OpenCV's native cv2.FaceDetectorYN implementation:
- Model size: 232 KB (ONNX)
- Latency: ~25-30ms on Raspberry Pi 4 CPU (~35+ FPS)
- Utilizes ARM NEON SIMD instructions in OpenCV DNN
"""

import os
from typing import List, Dict, Tuple, Optional, Any
import numpy as np
import cv2
from .downloader import get_model_path


class YuNetDetector:
    """High-speed face detector powered by OpenCV YuNet."""

    def __init__(
        self,
        model_path: Optional[str] = None,
        input_size: Tuple[int, int] = (320, 320),
        score_threshold: float = 0.6,
        nms_threshold: float = 0.3,
        top_k: int = 5000
    ) -> None:
        """Initialize YuNet face detector.

        Args:
            model_path: Path to face_detection_yunet_2023mar.onnx. If None, auto-downloads.
            input_size: Initial (width, height) for detector. Defaults to (320, 320).
            score_threshold: Confidence threshold for face detection (0.0 to 1.0).
            nms_threshold: Non-Maximum Suppression threshold (0.0 to 1.0).
            top_k: Maximum number of detections to keep before NMS.
        """
        if model_path is None or not os.path.isfile(model_path):
            model_path = get_model_path("yunet", auto_download=True)

        self.model_path = model_path
        self.input_size = input_size
        self.score_threshold = score_threshold
        self.nms_threshold = nms_threshold
        self.top_k = top_k

        if not hasattr(cv2, "FaceDetectorYN"):
            raise RuntimeError(
                "OpenCV FaceDetectorYN is not available in your OpenCV installation. "
                "Please install opencv-python >= 4.5.4."
            )

        self.detector = cv2.FaceDetectorYN.create(
            model=self.model_path,
            config="",
            input_size=self.input_size,
            score_threshold=self.score_threshold,
            nms_threshold=self.nms_threshold,
            top_k=self.top_k
        )

    def set_input_size(self, size: Tuple[int, int]) -> None:
        """Update detector input size when camera frame resolution changes.

        Args:
            size: (width, height) tuple.
        """
        if size != self.input_size:
            self.input_size = size
            self.detector.setInputSize(self.input_size)

    def detect(self, frame: np.ndarray, min_size: int = 30) -> List[Dict[str, Any]]:
        """Detect faces in a BGR frame.

        Args:
            frame: BGR numpy image frame.
            min_size: Minimum face bounding box width/height in pixels.

        Returns:
            List of detected face dictionaries containing:
                - 'bbox': (x1, y1, x2, y2)
                - 'x': int
                - 'y': int
                - 'w': int
                - 'h': int
                - 'landmarks': 5 landmark coordinates [(x, y), ...]
                - 'score': float confidence
                - 'raw': raw 15-element array needed by cv2.FaceRecognizerSF
        """
        if frame is None or frame.size == 0:
            return []

        h, w = frame.shape[:2]
        if (w, h) != self.input_size:
            self.set_input_size((w, h))

        _, faces = self.detector.detect(frame)
        if faces is None or len(faces) == 0:
            return []

        results: List[Dict[str, Any]] = []
        for face in faces:
            score = float(face[-1])
            if score < self.score_threshold:
                continue

            x = int(face[0])
            y = int(face[1])
            box_w = int(face[2])
            box_h = int(face[3])

            if box_w < min_size or box_h < min_size:
                continue

            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(w, x + box_w)
            y2 = min(h, y + box_h)

            # Extract 5 landmarks: right eye, left eye, nose tip, right mouth, left mouth
            landmarks = [
                (int(face[4]), int(face[5])),
                (int(face[6]), int(face[7])),
                (int(face[8]), int(face[9])),
                (int(face[10]), int(face[11])),
                (int(face[12]), int(face[13]))
            ]

            results.append({
                "bbox": (x1, y1, x2, y2),
                "x": x1,
                "y": y1,
                "w": box_w,
                "h": box_h,
                "landmarks": landmarks,
                "score": score,
                "raw": face
            })

        return results
