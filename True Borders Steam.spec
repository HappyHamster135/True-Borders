# -*- mode: python ; coding: utf-8 -*-
# STEAM-UTGÅVAN.  Bygg:  pyinstaller "True Borders Steam.spec" --noconfirm
#
# Skillnader mot standalone ("True Borders.spec"):
#   * onedir istället för onefile — Steams depot-system patchar då bara de
#     filer som ändrats, och antivirus bråkar mindre än med onefile.
#   * packaging/steam_edition.marker bundlas -> IS_STEAM_BUILD i main.py blir
#     True och GitHub-självuppdateraren stängs av (Steam sköter uppdateringar).
#   * updater.exe bundlas INTE (skulle aldrig få köras).
#   * upx=False av samma antivirus-skäl som standalone.
#
# Resultatet hamnar i dist/True Borders Steam/ — ladda upp HELA mappen som
# depot i Steamworks, med "True Borders.exe" som launch-target.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web', 'web'),
        ('packaging/steam_edition.marker', '.'),
        ('packaging/tb_icon_64.png', '.'),
    ],
    hiddenimports=[
        'webview.platforms.winforms',
        'webview.platforms.edgechromium',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='True Borders',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='packaging/trueborders.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='True Borders Steam',
)
