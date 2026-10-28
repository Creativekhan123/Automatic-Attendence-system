"""Ultra-Fast SFace Face Recognizer for Raspberry Pi 4.

Leverages OpenCV's native cv2.FaceRecognizerSF implementation:
- Model size: 38 MB (ONNX)
- Feature size: 128-D normalized embedding vector
- Latency: ~30-35ms on Raspberry Pi 4 CPU
- Built-in alignment and cropping using 5 facial landmarks
"""

import os
from typing import List, Dict, Tuple, Optional, Any
import numpy as np
import cv2
from .downloader import get_model_path


class SFaceRecognizer:
    """Face feature extractor and identifier powered by OpenCV SFace."""

    # Default cosine similarity threshold recommended by OpenCV Zoo
    COSINE_THRESHOLD = 0.363
    L2_THRESHOLD = 1.128

    def __init__(
        self,
        model_path: Optional[str] = None,
        cosine_threshold: float = 0.363
    ) -> None:
        """Initialize SFace recognizer.

        Args:
            model_path: Path to face_recognition_sface_2021dec.onnx. If None, auto-downloads.
            cosine_threshold: Minimum cosine similarity score for verification match.
        """
        if model_path is None or not os.path.isfile(model_path):
            model_path = get_model_path("sface", auto_download=True)

        self.model_path = model_path
        self.cosine_threshold = cosine_threshold

        if not hasattr(cv2, "FaceRecognizerSF"):
            raise RuntimeError(
                "OpenCV FaceRecognizerSF is not available in your OpenCV installation. "
                "Please install opencv-python >= 4.5.4."
            )

        self.recognizer = cv2.FaceRecognizerSF.create(
            model=self.model_path,
            config=""
        )

    def extract_feature(self, frame: np.ndarray, raw_face: np.ndarray) -> np.ndarray:
        """Align, crop face from frame and extract 128-D feature embedding.

        Args:
            frame: Input BGR image frame.
            raw_face: 15-element face detection array from YuNet.

        Returns:
            128-D normalized numpy float32 embedding vector.
        """
        aligned_face = self.recognizer.alignCrop(frame, raw_face)
        feature = self.recognizer.feature(aligned_face)
        # SFace features are 2D (1, 128); flatten to 1D
        emb = feature.flatten().astype(np.float32)
        norm = np.linalg.norm(emb)
        if norm > 0:
            emb = emb / norm
        return emb

    def match(self, feature1: np.ndarray, feature2: np.ndarray) -> float:
        """Compute cosine similarity score between two 128-D embeddings.

        Returns:
            Cosine similarity score (higher = closer match).
        """
        f1 = feature1.reshape(1, -1)
        f2 = feature2.reshape(1, -1)
        return float(self.recognizer.match(f1, f2, cv2.FaceRecognizerSF_FR_COSINE))

    def identify_vectorized(
        self,
        query_emb: np.ndarray,
        roster_matrix: Optional[np.ndarray],
        student_records: List[Dict[str, Any]],
        threshold: Optional[float] = None
    ) -> Tuple[str, Optional[Dict[str, Any]], float]:
        """Vectorized cosine similarity comparison against enrolled students.

        Args:
            query_emb: 128-D query embedding.
            roster_matrix: (N, 128) pre-stacked matrix of enrolled student embeddings.
            student_records: List of student dicts corresponding to matrix rows.
            threshold: Cosine similarity cutoff. If None, uses self.cosine_threshold.

        Returns:
            Tuple of (label_text, matched_student_dict_or_None, score).
        """
        cutoff = threshold if threshold is not None else self.cosine_threshold

        if roster_matrix is None or len(student_records) == 0 or roster_matrix.shape[0] == 0:
            return "Unknown", None, 0.0

        q = query_emb.flatten()
        norm = np.linalg.norm(q)
        if norm > 0:
            q = q / norm

        # BLAS matrix-vector dot product (takes <0.02ms on Pi 4 for hundreds of students)
        similarities = np.dot(roster_matrix, q)
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])

        if best_score >= cutoff:
            student = student_records[best_idx]
            label = student.get("name", f"Student {student.get('student_id')}")
            return label, student, best_score

        return "Unknown", None, best_score
