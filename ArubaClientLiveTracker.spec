# PyInstaller onedir: Qt remains dynamically linked and replaceable.
import hashlib
import json
from pathlib import Path
from PySide6.QtCore import QLibraryInfo

root = Path(SPECPATH)
digest = hashlib.sha256()
package_root = root / 'src' / 'aruba_client_live_tracker'
for source in sorted(package_root.rglob('*.py')):
    if '__pycache__' not in source.parts:
        digest.update(source.relative_to(package_root).as_posix().encode('utf-8') + b'\0')
        digest.update(source.read_bytes().replace(b'\r\n', b'\n') + b'\0')
build_metadata = root / 'build' / 'runtime-build.json'
build_metadata.parent.mkdir(parents=True, exist_ok=True)
build_metadata.write_text(json.dumps({'source_sha256': digest.hexdigest()}), encoding='utf-8')
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
a.datas.append(('aruba_client_live_tracker/runtime-build.json', str(build_metadata), 'DATA'))
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
