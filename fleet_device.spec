# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Fleet Attendance Device (Bus / Edge Computer Application)

import os
import sys
import site
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_dynamic_libs

block_cipher = None

# Collect packages that need all data files
insightface_datas   = collect_data_files('insightface', include_py_files=True)
onnxruntime_datas   = collect_data_files('onnxruntime')

project_datas = [
    ('src/haarcascade_frontalface_default.xml', 'src'),
    ('src/__init__.py', 'src'),
    ('fleet_system', 'fleet_system'),
]

_model_dir = os.path.join(os.path.expanduser('~'), '.insightface', 'models', 'buffalo_sc')
model_datas = []
if os.path.isdir(_model_dir):
    model_datas.append((_model_dir, 'insightface_models/buffalo_sc'))

all_datas = (
    insightface_datas
    + onnxruntime_datas
    + project_datas
    + model_datas
)

hidden_imports = [
    'insightface',
    'onnxruntime',
    'cv2',
    'numpy',
    'sqlite3',
    'requests',
    'dotenv',
    'fleet_system',
    'fleet_system.shared',
    'fleet_system.shared.cloud_client',
    'fleet_system.device_app',
    'fleet_system.device_app.local_db',
    'fleet_system.device_app.sync_worker',
    'src.camera',
    'src.face_recognizer',
]

hidden_imports += collect_submodules('insightface')
hidden_imports += collect_submodules('onnxruntime')

ort_binaries = collect_dynamic_libs('onnxruntime')
for sp in site.getsitepackages():
    ort_capi = os.path.join(sp, 'onnxruntime', 'capi')
    if os.path.isdir(ort_capi):
        for dll in os.listdir(ort_capi):
            if dll.endswith('.dll'):
                ort_binaries.append((os.path.join(ort_capi, dll), '.'))
        break

a = Analysis(
    ['fleet_system/device_app/main.py'],
    pathex=['.'],
    binaries=ort_binaries,
    datas=all_datas,
    hiddenimports=hidden_imports,
    hookspath=['hooks'],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_onnxruntime.py'] if os.path.exists('hooks/rthook_onnxruntime.py') else [],
    excludes=['customtkinter', 'matplotlib', 'IPython', 'notebook', 'jupyter', 'torch', 'torchvision', 'tests'],
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
    name='FleetAttendanceDevice',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,       # Console enabled so bus admin can see camera logs & pass flags like --bus-id
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
    name='FleetAttendanceDevice',
)
