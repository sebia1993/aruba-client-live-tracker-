"""Provide exact LGPL corresponding sources alongside executable downloads."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
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


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verified_source(cache: Path, filename: str, url: str, expected: str) -> Path:
    local = cache / filename
    if local.is_symlink():
        raise ValueError(f"Source cache must not contain links: {filename}")
    if local.exists():
        if sha256(local) == expected:
            return local
        # An interrupted old download must never be mistaken for a reusable entry.
        local.unlink()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, prefix=f".{filename}.", suffix=".part", delete=False) as target:
            temporary = Path(target.name)
            with urllib.request.urlopen(url, timeout=120) as response:
                shutil.copyfileobj(response, target)
            target.flush()
            os.fsync(target.fileno())
        if sha256(temporary) != expected:
            raise RuntimeError(f"Upstream source checksum mismatch: {filename}")
        # The sibling temporary file and final cache file are on the same volume.
        temporary.replace(local)
        return local
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def bundle(output: Path, cache: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    temporary = digest_file = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
        manifest = []
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            for filename, (url, expected) in SOURCES.items():
                local = verified_source(cache, filename, url, expected)
                archive.write(local, "third-party-sources/" + filename)
                manifest.append({"file": filename, "source": url, "sha256": expected})
            archive.writestr("third-party-sources/manifest.json", json.dumps(manifest, indent=2))
            archive.writestr("third-party-sources/README.txt", "Exact unmodified corresponding sources for bundled LGPL libraries. Qt uses qtbase, qtimageformats and qtsvg; Korean translations use qttranslations. PySide6 and Shiboken share pyside-setup sources. Each archive contains its upstream build instructions. Application source and build scripts are included in the executable ZIP's SOURCE folder. The onedir Qt DLLs can be replaced with compatible rebuilt libraries. No library modifications were made.\n")
        digest = sha256(temporary)
        with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", suffix=".sha256.part", delete=False) as stream:
            digest_file = Path(stream.name)
            stream.write(f"{digest}  {output.name}\n".encode("utf-8"))
        backup = None
        if output.exists():
            # Keep the previous ZIP until its matching new checksum is published.
            # Rename within this directory avoids copying a large source archive.
            with tempfile.NamedTemporaryFile(dir=output.parent, prefix=f".{output.name}.", suffix=".rollback", delete=False) as stream:
                backup = Path(stream.name)
            try:
                output.replace(backup)
            except BaseException:
                backup.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(output)
            digest_file.replace(output.with_suffix(output.suffix + ".sha256"))
        except BaseException:
            if backup is not None:
                try:
                    backup.replace(output)
                except OSError as restore_error:
                    # Never delete the only old ZIP if filesystem access also blocks rollback.
                    raise RuntimeError(f"Bundle rollback failed; previous ZIP preserved at {backup}") from restore_error
            else:
                output.unlink(missing_ok=True)
            raise
        else:
            if backup is not None:
                backup.unlink()
    finally:
        for path in (temporary, digest_file):
            if path is not None:
                path.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=Path("dist/ArubaClientLiveTracker_v0.3.8_third_party_sources.zip"))
    parser.add_argument("--cache", type=Path, default=Path("build/upstream-sources"))
    args = parser.parse_args()
    bundle(args.output, args.cache)
