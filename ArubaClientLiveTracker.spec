# PyInstaller onedir: Qt remains dynamically linked and replaceable.
from pathlib import Path
from PySide6.QtCore import QLibraryInfo

root = Path(SPECPATH)
a = Analysis(
    [str(root / "scripts" / "run_app.py")],
    pathex=[str(root / "src")],
    binaries=[],
    datas=[(str(root / "LICENSE"), "."), (str(root / "THIRD_PARTY_NOTICES.md"), "."), (str(Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)) / "qtbase_ko.qm"), "PySide6/translations")],
    hiddenimports=[],
    hookspath=[],
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets"],
    noarchive=False,
)
# Raster-only UI does not use the optional Mesa OpenGL software renderer.
a.binaries = [entry for entry in a.binaries if not entry[0].lower().endswith("opengl32sw.dll")]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="ArubaClientLiveTracker", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
    uac_admin=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="ArubaClientLiveTracker")
