"""Collect redistributable dependency license files; fail on missing license material."""
from __future__ import annotations

import argparse
import importlib.metadata as metadata
import json
import shutil
from pathlib import Path

PACKAGES = [
    "PySide6-Essentials", "shiboken6", "paramiko", "platformdirs", "bcrypt",
    "cffi", "cryptography", "PyNaCl", "pycparser", "invoke",
]


def collect(output: Path) -> None:
    root = Path(__file__).resolve().parents[1]
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(root / "LICENSES", output / "upstream", dirs_exist_ok=True)
    manifest = []
    for package in PACKAGES:
        distribution = metadata.distribution(package)
        destination = output / package
        destination.mkdir(exist_ok=True)
        copied = []
        for member in distribution.files or []:
            if any(token in str(member).lower() for token in ("license", "copying", "notice")):
                source = Path(distribution.locate_file(member))
                if source.is_file():
                    # Flatten with collision-safe source path preserving component notices.
                    name = str(member).replace("/", "__").replace("\\", "__")
                    shutil.copy2(source, destination / name)
                    copied.append(name)
        if package in ("PySide6-Essentials", "shiboken6"):
            for source in (root / "LICENSES").glob("*.txt"):
                shutil.copy2(source, destination / source.name)
                copied.append(source.name)
        if not copied:
            raise RuntimeError(f"License text missing: {package}")
        manifest.append({"name": package, "version": distribution.version, "files": copied})
    shutil.copy2(root / "THIRD_PARTY_NOTICES.md", output / "THIRD_PARTY_NOTICES.md")
    # Python license includes bundled software and acknowledgements.
    import sys
    for candidate in (Path(sys.base_prefix) / "LICENSE.txt", Path(sys.base_prefix) / "LICENSE"):
        if candidate.is_file():
            shutil.copy2(candidate, output / "Python-LICENSE.txt")
            break
    else:
        source = root / "LICENSES" / "Python-3.12.10-LICENSE.txt"
        if not source.exists():
            raise RuntimeError("Python license missing")
        shutil.copy2(source, output / source.name)
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    collect(parser.parse_args().output)
