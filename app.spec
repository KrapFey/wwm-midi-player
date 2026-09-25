# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['src/web_app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ("src/input/logo.ico", "src/input"),
        # pywebview resolves web_app.py's "web/static/..." pages against the
        # bundle root (_internal), so the UI must land at exactly this path.
        ("src/web/static", "web/static"),
        ("LICENSE", "."),
        ("TOH.sf2", "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='WWM MIDI Player',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['src\\input\\logo.ico'],
    uac_admin=True,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WWM MIDI Player',
)
