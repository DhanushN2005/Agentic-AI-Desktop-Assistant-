# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all

block_cipher = None
ROOT_DIR = os.path.abspath(SPECPATH)

# Packages to collect
packages = [
    'PyQt6', 'pygame', 'edge_tts', 'speech_recognition', 
    'psutil', 'dotenv', 'requests'
]

datas = [
    (os.path.join(ROOT_DIR, 'interface'), 'interface'),
    (os.path.join(ROOT_DIR, 'core'), 'core'),
    (os.path.join(ROOT_DIR, 'engines'), 'engines'),
    (os.path.join(ROOT_DIR, 'utils'), 'utils'),
    (os.path.join(ROOT_DIR, 'adapters'), 'adapters'),
    (os.path.join(ROOT_DIR, 'agents'), 'agents'),
    (os.path.join(ROOT_DIR, 'context'), 'context'),
    (os.path.join(ROOT_DIR, 'data'), 'data'),
    (os.path.join(ROOT_DIR, 'recovery'), 'recovery'),
    (os.path.join(ROOT_DIR, 'sandbox'), 'sandbox'),
    (os.path.join(ROOT_DIR, 'sdd'), 'sdd'),
    (os.path.join(ROOT_DIR, 'templates'), 'templates'),
    (os.path.join(ROOT_DIR, 'tools'), 'tools'),
    (os.path.join(ROOT_DIR, 'verification'), 'verification'),
    (os.path.join(ROOT_DIR, 'vision'), 'vision'),
    (os.path.join(ROOT_DIR, 'voice'), 'voice'),
]

datas = [(src, dst) for src, dst in datas if os.path.exists(src)]

hiddenimports = [
    'PyQt6', 'PyQt6.QtCore', 'PyQt6.QtGui', 'PyQt6.QtWidgets', 'PyQt6.QtNetwork',
    'pygame', 'speech_recognition', 'edge_tts', 'psutil', 'dotenv',
    'requests', 'urllib.parse', 'json', 'sqlite3', 'ctypes', 'threading',
    'core', 'core.orchestrator', 'core.controller', 'core.router', 'core.jobs',
    'interface.ui', 'interface.voice', 'utils.installer', 'utils.udp_auth', 'utils.config',
    'engines', 'agents', 'adapters', 'sdd'
]

binaries = []

for pkg in packages:
    try:
        tmp_datas, tmp_binaries, tmp_hidden = collect_all(pkg)
        datas += tmp_datas
        binaries += tmp_binaries
        hiddenimports += tmp_hidden
    except Exception:
        pass

# Exclude heavy unused libraries and packages with broken PyInstaller contrib hooks
excludes = [
    'torch', 'torchvision', 'torchaudio', 'tensorflow', 'tensorboard',
    'keras', 'jax', 'jaxlib', 'h5py', 'sympy', 'sklearn', 'scipy',
    'matplotlib', 'pandas', 'IPython', 'notebook', 'tkinter', 'pytest',
    'webrtcvad', 'transformers', 'datasets', 'spacy', 'thinc', 'nltk'
]

a = Analysis(
    ['main.py'],
    pathex=[ROOT_DIR],
    binaries=binaries,
    datas=datas,
    hiddenimports=list(set(hiddenimports)),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
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
    name='Flexie',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Flexie',
)
