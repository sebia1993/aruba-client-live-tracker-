"""Export reviewed public sources, never recursively copy a developer checkout.

Git determines the path list in a checkout; a release's source-manifest.json
provides it without Git. Hashes describe each export, not a signature: source
edits are permitted for rebuilding, and hashes are refreshed on re-export.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

MANIFEST = "source-manifest.json"
ROOT_FILES = {
    ".gitignore", "AGENTS.md", "ArubaClientLiveTracker.spec", "CHANGELOG.md", "LICENSE",
    "README.md", "SECURITY.md", "THIRD_PARTY_NOTICES.md", "build_windows.ps1",
    "pyproject.toml", "requirements.txt", "requirements-dev.txt",
}
PRIVATE_DIRECTORIES = {
    ".git", ".venv", ".ssh", "__pycache__", ".pytest_cache", ".ruff_cache",
    "raw-output", "local-data", "build", "dist", "artifacts", "htmlcov",
}
PRIVATE_SUFFIXES = {".db", ".log", ".pem", ".key", ".pfx", ".p12", ".bak", ".pyc", ".pyo"}


def public_path(entry: str) -> PurePosixPath:
    """Validate the same portable relative spelling on Windows and POSIX."""
    if not isinstance(entry, str) or not entry or "\\" in entry or ":" in entry:
        raise ValueError("Invalid source path")
    parts = entry.split("/")
    if any(not part or part in {".", ".."} or part.rstrip(" .") != part for part in parts):
        raise ValueError("Invalid source path components")
    if any(any(ord(char) < 32 or char in '<>"|?*' for char in part) for part in parts):
        raise ValueError("Invalid source path characters")
    if any(PureWindowsPath(part).is_reserved() for part in parts):
        raise ValueError("Reserved Windows source path")
    relative = PurePosixPath(entry)
    if relative.is_absolute():
        raise ValueError("Absolute source path")
    for part in parts:
        lower = part.casefold()
        if lower in PRIVATE_DIRECTORIES or lower.endswith(".egg-info"):
            raise ValueError("Private or generated source path")
        if lower.startswith(("settings.json", "known_hosts", "credentials", ".env", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa")):
            raise ValueError("Private source file")
        if ".sqlite" in lower or ".db-" in lower or PurePosixPath(lower).suffix in PRIVATE_SUFFIXES:
            raise ValueError("Private or generated source file")
    if entry in ROOT_FILES:
        return relative
    suffix = relative.suffix.casefold()
    if len(parts) > 1 and parts[0] in {"src", "scripts", "tests"} and suffix == ".py":
        return relative
    if len(parts) > 1 and parts[0] == "LICENSES":
        return relative
    if len(parts) == 2 and parts[0] == "docs" and suffix == ".md":
        return relative
    if len(parts) == 3 and parts[:2] == ["docs", "assets"] and suffix in {".png", ".jpg", ".svg"}:
        return relative
    if len(parts) == 4 and parts[:2] == ["docs", "validation"] and suffix in {".md", ".json", ".txt"}:
        return relative
    if len(parts) == 3 and parts[:2] == [".github", "workflows"] and suffix in {".yml", ".yaml"}:
        return relative
    raise ValueError("Source path is not in the public allowlist")


def regular_source(root: Path, relative: PurePosixPath) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError("Source links and reparse points are forbidden")
    if not stat.S_ISREG(info.st_mode) or not current.resolve().is_relative_to(root):
        raise ValueError("Source must be a regular file inside the source root")
    return current


def source_entries(root: Path) -> list[str]:
    if (root / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "-C", str(root), "ls-files", "--stage", "-z"],
                check=True, capture_output=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Unable to read tracked source files from Git") from exc
        entries = []
        for record in result.stdout.decode("utf-8").split("\0"):
            if not record:
                continue
            metadata, entry = record.split("\t", 1)
            mode, _object_id, stage = metadata.split()
            try:
                public_path(entry)
            except ValueError:
                continue
            if mode not in {"100644", "100755"}:
                raise ValueError("Tracked source links and submodules are forbidden")
            if stage != "0":
                raise ValueError("Unresolved source merge conflicts")
            entries.append(entry)
        return entries
    manifest_path = root / MANIFEST
    if not manifest_path.exists():
        raise ValueError("SOURCE requires Git metadata or source-manifest.json; older sources must use their original build script")
    regular_source(root, PurePosixPath(MANIFEST))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError("Unreadable source manifest") from exc
    if not isinstance(manifest, dict) or manifest.get("version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("Unsupported source manifest")
    return manifest["files"]


def export(source: Path, output: Path) -> None:
    root = source.resolve(strict=True)
    destination = output.absolute()
    if destination.is_symlink() or destination.is_junction():
        raise ValueError("Export destination must not be a link")
    resolved_output = destination.resolve()
    if root == resolved_output or root.is_relative_to(resolved_output):
        raise ValueError("Export destination overlaps the source root")
    if destination.exists() and (not destination.is_dir() or any(destination.iterdir())):
        raise ValueError("Export destination must be absent or empty")
    entries = source_entries(root)
    files = []
    seen = set()
    for entry in entries:
        relative = public_path(entry)
        key = entry.casefold()
        if key in seen:
            raise ValueError("Duplicate source paths")
        seen.add(key)
        files.append((entry, regular_source(root, relative)))
    if not files:
        raise ValueError("No public source files to export")
    destination.parent.mkdir(parents=True, exist_ok=True)
    # TemporaryDirectory owns only this unique sibling; existing exports are never removed.
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".source-export-") as temporary:
        staging = Path(temporary) / "SOURCE"
        staging.mkdir()
        hashes = {}
        for entry, original in sorted(files):
            target = staging.joinpath(*PurePosixPath(entry).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, target)
            with target.open("rb") as stream:
                hashes[entry] = hashlib.file_digest(stream, "sha256").hexdigest()
        (staging / MANIFEST).write_text(
            json.dumps({"version": 1, "files": sorted(hashes), "sha256": hashes}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        if destination.exists():
            destination.rmdir()  # Only an empty directory is accepted; never recurse here.
        staging.replace(destination)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    export(arguments.source, arguments.output)
