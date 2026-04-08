# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Astro Framing Assistant."""

import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# Collect data files for packages that need runtime data
datas = [
    ('data', 'data'),
    ('src', 'src'),
]
datas += collect_data_files('astropy')
datas += collect_data_files('erfa')
datas += collect_data_files('certifi')
datas += collect_data_files('pyqtdarktheme', include_py_files=False)
datas += collect_data_files('timezonefinder')
datas += collect_data_files('pytz')
datas += collect_data_files('PIL')

# Include package metadata for version checks
from PyInstaller.utils.hooks import copy_metadata
datas += copy_metadata('Pillow')
datas += copy_metadata('astropy')
datas += copy_metadata('numpy')
datas += copy_metadata('xisf')

# Collect submodules for packages with dynamic imports
hiddenimports = []
hiddenimports += collect_submodules('astropy')
hiddenimports += collect_submodules('erfa')
hiddenimports += [
    'matplotlib.backends.backend_qtagg',
    'matplotlib.backends.backend_agg',
    'reproject.interpolation',
    'xisf',
    'PyQt6.sip',
    'sqlite3',
    'qdarktheme',
    'astroplan',
    'timezonefinder',
    'pytz',
    'PIL',
]
hiddenimports += collect_submodules('qdarktheme')
hiddenimports += collect_submodules('astroplan')
hiddenimports += collect_submodules('reproject')
hiddenimports += collect_submodules('xisf')
hiddenimports += collect_submodules('timezonefinder')

# Exclude unnecessary modules
excludes = ['tkinter', 'pytest']

a = Analysis(
    ['run.py'],
    pathex=['src'],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['hooks/rthook_astropy.py'],
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
    name='AstroFramingAssistant',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AstroFramingAssistant',
)

# macOS .app bundle
if sys.platform == 'darwin':
    app = BUNDLE(
        coll,
        name='Astro Framing Assistant.app',
        bundle_identifier='com.astroframing.assistant',
        info_plist={
            'CFBundleDisplayName': 'Astro Framing Assistant',
            'CFBundleShortVersionString': '0.1.0',
            'NSHighResolutionCapable': True,
        },
    )
