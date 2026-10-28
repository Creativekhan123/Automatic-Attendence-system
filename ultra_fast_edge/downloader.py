"""Automatic Model Downloader for Ultra-Fast Edge (YuNet & SFace).

Fetches official OpenCV Zoo ONNX models directly from GitHub:
- YuNet: Ultra-lightweight face detector (232 KB, ~25-30ms on Raspberry Pi 4 CPU)
- SFace: High-speed mobile face recognition model (38 MB, 128-D embeddings)
"""

import os
import sys
import time
import urllib.request
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("model_downloader")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

MODELS = {
    "yunet": {
        "filename": "face_detection_yunet_2023mar.onnx",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "expected_size": 232589,
        "description": "OpenCV YuNet Face Detector (232 KB) - 35+ FPS on RPi 4"
    },
    "sface": {
        "filename": "face_recognition_sface_2021dec.onnx",
        "url": "https://github.com/opencv/opencv_zoo/raw/main/models/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        "expected_size": 38696353,
        "description": "OpenCV SFace Face Recognizer (38 MB) - 128-D embeddings"
    }
}


def ensure_models_dir() -> str:
    """Ensure the models directory exists."""
    os.makedirs(MODELS_DIR, exist_ok=True)
    return MODELS_DIR


def download_file(url: str, dest_path: str, description: str, expected_size: int = 0) -> bool:
    """Download a file with console progress indicator."""
    logger.info(f"Downloading {description}...")
    logger.info(f"Target: {dest_path}")

    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    req = urllib.request.Request(url, headers=headers)

    tmp_path = dest_path + ".tmp"
    start_time = time.time()
    try:
        with urllib.request.urlopen(req, timeout=30) as response, open(tmp_path, "wb") as out_file:
            total_size = int(response.headers.get("Content-Length", expected_size))
            downloaded = 0
            chunk_size = 64 * 1024  # 64 KB

            while True:
                chunk = response.read(chunk_size)
                if not chunk:
                    break
                out_file.write(chunk)
                downloaded += len(chunk)

                if total_size > 0:
                    percent = min(100.0, (downloaded / total_size) * 100.0)
                    mb_down = downloaded / (1024 * 1024)
                    mb_tot = total_size / (1024 * 1024)
                    sys.stdout.write(f"\r  Progress: {percent:5.1f}% [{mb_down:.2f} MB / {mb_tot:.2f} MB]")
                else:
                    sys.stdout.write(f"\r  Downloaded: {downloaded / (1024 * 1024):.2f} MB")
                sys.stdout.flush()

        sys.stdout.write("\n")
        # Rename tmp to final
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(tmp_path, dest_path)

        elapsed = time.time() - start_time
        file_size_kb = os.path.getsize(dest_path) / 1024
        logger.info(f"[OK] Downloaded successfully: {file_size_kb:.1f} KB in {elapsed:.2f}s")
        return True

    except Exception as e:
        sys.stdout.write("\n")
        logger.error(f"Download failed for {url}: {e}")
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False


def get_model_path(model_key: str, auto_download: bool = True) -> str:
    """Return local path to model; automatically downloads if missing."""
    if model_key not in MODELS:
        raise ValueError(f"Unknown model key '{model_key}'. Available: {list(MODELS.keys())}")

    info = MODELS[model_key]
    dest = os.path.join(ensure_models_dir(), info["filename"])

    if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
        return dest

    if not auto_download:
        raise FileNotFoundError(f"Model file not found at {dest}")

    success = download_file(info["url"], dest, info["description"], info["expected_size"])
    if not success or not os.path.isfile(dest):
        raise RuntimeError(f"Failed to acquire model '{model_key}' at {dest}")

    return dest


def download_all_models() -> bool:
    """Download all required models into the models directory."""
    print("=" * 65)
    print("  ULTRA-FAST EDGE - OPENCV MODEL DOWNLOADER")
    print("=" * 65)
    ensure_models_dir()
    all_ok = True
    for key, info in MODELS.items():
        dest = os.path.join(MODELS_DIR, info["filename"])
        if os.path.isfile(dest) and os.path.getsize(dest) > 1000:
            print(f"[FOUND] {info['description']} already present ({os.path.getsize(dest)/1024:.1f} KB).")
        else:
            ok = download_file(info["url"], dest, info["description"], info["expected_size"])
            if not ok:
                all_ok = False
    return all_ok


if __name__ == "__main__":
    download_all_models()
