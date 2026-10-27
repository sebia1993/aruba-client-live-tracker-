"""Provide exact LGPL corresponding sources alongside executable downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import urllib.request
import zipfile
from pathlib import Path

QT_BASE = "https://download.qt.io/archive/qt/6.8/6.8.3/submodules/"
SOURCES = {
    "qtbase-everywhere-src-6.8.3.tar.xz": (QT_BASE + "qtbase-everywhere-src-6.8.3.tar.xz", "56001b905601bb9023d399f3ba780d7fa940f3e4861e496a7c490331f49e0b80"),
    "qtimageformats-everywhere-src-6.8.3.tar.xz": (QT_BASE + "qtimageformats-everywhere-src-6.8.3.tar.xz", "049bfb99845e4801672aca07c3c4fc4c140f932a3a33faa899419579e33ef1c8"),
    "qtsvg-everywhere-src-6.8.3.tar.xz": (QT_BASE + "qtsvg-everywhere-src-6.8.3.tar.xz", "35eb516460f00f264eb504baa253432384351cf23fb9980a5857190e8deef438"),
    "qttranslations-everywhere-src-6.8.3.tar.xz": (QT_BASE + "qttranslations-everywhere-src-6.8.3.tar.xz", "c3c61d79c3d8fe316a20b3617c64673ce5b5519b2e45535f49bee313152fa531"),
    "pyside-setup-everywhere-src-6.8.3.tar.xz": ("https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/pyside-setup-everywhere-src-6.8.3.tar.xz", "d2c896f7f1a6a7ea4c9f98cfe317272fd139703ddf612b86999f09e48aeef0e6"),
    "paramiko-5.0.0.tar.gz": ("https://files.pythonhosted.org/packages/62/93/dcc25d52f49022ae6175d15e6bd751f1acc99b98bc61fc55e5155a7be2e7/paramiko-5.0.0.tar.gz", "36763b5b95c2a0dcfdf1abc48e48156ee425b21efe2f0e787c2dd5a95c0e5e79"),
}


def bundle(output: Path, cache: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    manifest = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
        for filename, (url, expected) in SOURCES.items():
            local = cache / filename
            if not local.exists():
                with urllib.request.urlopen(url, timeout=120) as response, local.open("wb") as target:
                    shutil.copyfileobj(response, target)
            actual = hashlib.sha256(local.read_bytes()).hexdigest()
            if actual != expected:
                raise RuntimeError(f"Upstream source checksum mismatch: {filename}")
            archive.write(local, "third-party-sources/" + filename)
            manifest.append({"file": filename, "source": url, "sha256": actual})
        archive.writestr("third-party-sources/manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("third-party-sources/README.txt", "Exact unmodified corresponding sources for bundled LGPL libraries. Qt uses qtbase, qtimageformats and qtsvg; Korean translations use qttranslations. PySide6 and Shiboken share pyside-setup sources. Each archive contains its upstream build instructions. Application source and build scripts are included in the executable ZIP's SOURCE folder. The onedir Qt DLLs can be replaced with compatible rebuilt libraries. No library modifications were made.\n")
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_text(f"{digest}  {output.name}\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, default=Path("build/upstream-sources"))
    args = parser.parse_args()
    bundle(args.output, args.cache)
