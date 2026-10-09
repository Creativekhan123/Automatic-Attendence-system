"""Runtime hook for onnxruntime / InsightFace in PyInstaller frozen executables.

1. When frozen, onnxruntime's native .dll files are placed inside _internal/onnxruntime/capi/
   but Windows DLL loader won't find them unless we explicitly add that directory to the
   DLL search path before any imports happen.
2. InsightFace's FaceAnalysis looks for models in ~/.insightface/models/<name>. The EXE
   bundles the buffalo_sc model pack; copy it there on first launch (offline-safe).
"""
import os
import shutil
import sys

if getattr(sys, "frozen", False):
    # sys._MEIPASS points to the _internal/ extraction directory
    _base = sys._MEIPASS

    # Add onnxruntime/capi to DLL search path so onnxruntime.dll is found
    _ort_capi = os.path.join(_base, "onnxruntime", "capi")
    if os.path.isdir(_ort_capi):
        # os.add_dll_directory is available on Python 3.8+ Windows
        if hasattr(os, "add_dll_directory"):
            os.add_dll_directory(_ort_capi)
        # Also prepend to PATH as a fallback
        os.environ["PATH"] = _ort_capi + os.pathsep + os.environ.get("PATH", "")

    # Also add the _MEIPASS root itself (for any DLLs placed there by PyInstaller)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(_base)

    # Seed bundled InsightFace models into the default model directory if missing
    try:
        _bundled = os.path.join(_base, "insightface_models", "buffalo_sc")
        _target = os.path.join(os.path.expanduser("~"), ".insightface", "models", "buffalo_sc")
        if os.path.isdir(_bundled):
            os.makedirs(_target, exist_ok=True)
            for _name in os.listdir(_bundled):
                _dst = os.path.join(_target, _name)
                if not os.path.exists(_dst):
                    shutil.copy2(os.path.join(_bundled, _name), _dst)
    except Exception:
        pass
