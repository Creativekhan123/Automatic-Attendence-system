import os
import warnings
from typing import List, Dict, Optional, Tuple, Any
import numpy as np

# Suppress scikit-image FutureWarning from InsightFace face_align
warnings.filterwarnings("ignore", category=FutureWarning)

_insightface_import_error = None
try:
    import insightface
    from insightface.app import FaceAnalysis
except Exception as _e:
    insightface = None
    FaceAnalysis = None
    _insightface_import_error = _e


class FaceRecognizer:
    """Performs face detection, ArcFace embedding extraction, and student matching.

    Uses InsightFace FaceAnalysis (with buffalo_sc ONNX models) loaded once on startup.
    """

    def __init__(
        self,
        model_name: str = "buffalo_sc",
        det_size: Tuple[int, int] = (640, 640),
        similarity_threshold: float = 0.50
    ) -> None:
        """Initialize the FaceRecognizer and load models into memory.

        Args:
            model_name: InsightFace model pack name ('buffalo_sc' is fast & lightweight).
            det_size: Image detection resolution (width, height).
            similarity_threshold: Cosine similarity cutoff for identity verification (0.0 to 1.0).
        """
        if FaceAnalysis is None:
            cause = f" Cause: {_insightface_import_error}" if _insightface_import_error else ""
            raise ImportError(
                f"InsightFace failed to load.{cause}\n"
                "If running from source: pip install insightface onnxruntime"
            )

        self.model_name = model_name
        self.det_size = det_size
        self.similarity_threshold = similarity_threshold

        try:
            # Initialize FaceAnalysis with CPUExecutionProvider for standard CPU inference
            self.app = FaceAnalysis(name=self.model_name, providers=["CPUExecutionProvider"])
            self.app.prepare(ctx_id=0, det_size=self.det_size)
        except Exception as e:
            raise RuntimeError(f"Failed to load InsightFace model '{self.model_name}': {e}") from e

    def extract_faces(self, frame: np.ndarray) -> List[Any]:
        """Detect faces and extract embeddings, landmarks, and bounding boxes.

        Args:
            frame: OpenCV BGR image frame.

        Returns:
            List of InsightFace Face objects (each containing .bbox, .embedding, .kps).
        """
        if frame is None or frame.size == 0:
            return []

        faces = self.app.get(frame)
        return faces

    @staticmethod
    def normalize_embedding(embedding: np.ndarray) -> np.ndarray:
        """L2-normalize a 512-D embedding vector."""
        norm = np.linalg.norm(embedding)
        if norm == 0:
            return embedding
        return embedding / norm

    @classmethod
    def compute_similarity(cls, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """Calculate cosine similarity between two face embeddings.

        Returns:
            Cosine similarity value between -1.0 and 1.0 (typically 0.0 to 1.0).
        """
        norm_emb1 = cls.normalize_embedding(emb1)
        norm_emb2 = cls.normalize_embedding(emb2)
        return float(np.dot(norm_emb1, norm_emb2))

    def identify_face(
        self,
        query_embedding: np.ndarray,
        registered_students: List[Dict[str, Any]]
    ) -> Tuple[str, Optional[Dict[str, Any]], float]:
        """Match a query face embedding against registered students.

        Args:
            query_embedding: 512-D float32 numpy vector for the query face.
            registered_students: List of student records containing 'face_embedding'.

        Returns:
            A tuple of:
            (display_label, matched_student_dict_or_None, similarity_score)
            If matched: ("Student Name (ID)", student_dict, score)
            If unmatched: ("UNKNOWN", None, best_score)
        """
        if not registered_students:
            return "UNKNOWN", None, 0.0

        best_score = -1.0
        best_student = None

        norm_query = self.normalize_embedding(query_embedding)

        for student in registered_students:
            ref_emb = student.get("face_embedding")
            if ref_emb is None:
                continue

            norm_ref = self.normalize_embedding(ref_emb)
            score = float(np.dot(norm_query, norm_ref))

            if score > best_score:
                best_score = score
                best_student = student

        if best_student is not None and best_score >= self.similarity_threshold:
            display_label = f"{best_student['name']} ({best_student['student_id']})"
            return display_label, best_student, best_score
        else:
            return "UNKNOWN", None, max(best_score, 0.0)
