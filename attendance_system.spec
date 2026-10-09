# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Automatic School Bus Attendance System V4.2
# Generated for Python 3.12 on Windows

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

block_cipher = None

# ─────────────────────────────────────────────
# Collect packages that need all data files
# ─────────────────────────────────────────────
customtkinter_datas = collect_data_files('customtkinter', include_py_files=True)
insightface_datas   = collect_data_files('insightface',   include_py_files=True)
onnxruntime_datas   = collect_data_files('onnxruntime')

# Bundle the haarcascade XML and the src package marker
project_datas = [
    ('src/haarcascade_frontalface_default.xml', 'src'),
    ('src/__init__.py',                          'src'),
]

# Bundle the InsightFace buffalo_sc ONNX models so the EXE works offline.
# The runtime hook copies them to ~/.insightface/models on first launch
# (where FaceAnalysis looks by default) if they are not already there.
_model_dir = os.path.join(os.path.expanduser('~'), '.insightface', 'models', 'buffalo_sc')
if not os.path.isdir(_model_dir):
    raise SystemExit(
        'InsightFace model pack not found at ' + _model_dir +
        '. Run the app once from source so buffalo_sc is downloaded, then rebuild.'
    )
model_datas = [(_model_dir, 'insightface_models/buffalo_sc')]

all_datas = (
    customtkinter_datas
    + insightface_datas
    + onnxruntime_datas
    + project_datas
    + model_datas
)

# ─────────────────────────────────────────────
# Hidden imports
# ─────────────────────────────────────────────
hidden_imports = [
    # ── customtkinter internals ──────────────
    'customtkinter',
    'customtkinter.windows',
    'customtkinter.windows.widgets',
    'customtkinter.windows.widgets.core_rendering',
    'customtkinter.windows.widgets.font',
    'customtkinter.windows.widgets.scaling',
    'customtkinter.windows.widgets.theme',
    'customtkinter.windows.widgets.utility',

    # ── InsightFace / ONNX ──────────────────
    'insightface',
    'insightface.app',
    'insightface.app.common',
    'insightface.model_zoo',
    'insightface.model_zoo.model_zoo',
    'insightface.utils',
    'insightface.utils.face_align',
    'insightface.data',
    'onnxruntime',
    'onnxruntime.capi',
    'onnxruntime.capi._pybind_state',
    'onnxruntime.capi.onnxruntime_pybind11_state',

    # ── OpenCV ──────────────────────────────
    'cv2',

    # ── Numpy / Scipy / Sklearn (indirect) ──
    'numpy',
    'numpy.core',
    'numpy.lib',
    'numpy.linalg',

    # ── PIL / Pillow ────────────────────────
    'PIL',
    'PIL.Image',
    'PIL.ImageTk',

    # ── stdlib extras ───────────────────────
    'sqlite3',
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'multiprocessing',
    'multiprocessing.freeze_support',
    'queue',
    'threading',
    'subprocess',
    'datetime',
    'pathlib',
    'logging',
    'json',
    'csv',
    'io',
    're',
    'os',
    'sys',
    'typing',
    'warnings',
    'functools',
    'collections',
    # unittest/doctest are imported at module level by numpy.testing and
    # onnxruntime.backend, which InsightFace pulls in.
    'unittest',
    'unittest.case',
    'unittest.mock',
    'doctest',
    'pydoc',

    # ── project modules ─────────────────────
    'src',
    'src.config',
    'src.database',
    'src.attendance',
    'src.camera',
    'src.face_detector',
    'src.face_recognizer',
]

# Add all insightface and onnxruntime submodules dynamically
hidden_imports += collect_submodules('insightface')
hidden_imports += collect_submodules('onnxruntime')
hidden_imports += collect_submodules('customtkinter')

# ─────────────────────────────────────────────
# Binaries: collect onnxruntime DLLs and also
# place them at the _internal root so the
# Windows DLL loader can always find them
# ─────────────────────────────────────────────
ort_binaries = collect_dynamic_libs('onnxruntime')

# Explicitly copy onnxruntime.dll and onnxruntime_providers_shared.dll
# to the _internal root (.) so they are found without add_dll_directory
import site
for sp in site.getsitepackages():
    ort_capi = os.path.join(sp, 'onnxruntime', 'capi')
    if os.path.isdir(ort_capi):
        for dll in os.listdir(ort_capi):
            if dll.endswith('.dll'):
                ort_binaries.append((os.path.join(ort_capi, dll), '.'))
        break

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=ort_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_onnxruntime.py'],
    excludes=[
        'matplotlib',
        'IPython',
        'notebook',
        'jupyter',
        'tensorflow',
        'torch',
        'torchvision',
        'test',
        'tests',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AttendanceSystem',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,          # No black console window — GUI only
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AttendanceSystem',
)
