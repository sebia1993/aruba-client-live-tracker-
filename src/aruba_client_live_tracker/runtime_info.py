"""Local build identity; no Git command, network request, or device data."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from . import __version__


def source_fingerprint(package_dir: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(package_dir.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        digest.update(path.relative_to(package_dir).as_posix().encode('utf-8') + b'\0')
        # Identical Windows/Linux source should have the same identity.
        digest.update(path.read_bytes().replace(b'\r\n', b'\n') + b'\0')
    return digest.hexdigest()


def runtime_identity(*, include_path: bool = False) -> dict[str, str]:
    from .discovery_parsers import SWITCH_PARSER_VERSION
    from .ssh import SSH_READER_VERSION
    package_dir = Path(__file__).resolve().parent
    frozen = bool(getattr(sys, 'frozen', False))
    try:
        fingerprint = (json.loads((package_dir / 'runtime-build.json').read_text(encoding='utf-8'))
                       ['source_sha256'] if frozen else source_fingerprint(package_dir))
        if not isinstance(fingerprint, str) or len(fingerprint) != 64 or any(
                c not in '0123456789abcdef' for c in fingerprint):
            raise ValueError('Invalid build identity')
    except (OSError, ValueError, KeyError, TypeError):
        fingerprint = 'unavailable'
    info = {'version': __version__, 'build_id': f'{__version__}-{fingerprint[:12]}',
            'collector_revision': f'ssh-stream-{SSH_READER_VERSION}',
            'parser_revision': f'switch-table-{SWITCH_PARSER_VERSION}',
            'mode': 'frozen' if frozen else 'source'}
    if include_path:
        # The full local path is shown only in the local help window.
        info['executable_path'] = sys.executable
        if not frozen:
            info['source_path'] = str(package_dir)
    return info


def runtime_help_text() -> str:
    info = runtime_identity(include_path=True)
    lines = ['실행 정보', f"앱 버전: {info['version']}", f"빌드 식별자: {info['build_id']}",
             f"실행 형태: {info['mode']}", f"실행 경로: {info['executable_path']}",
             f"수집기: {info['collector_revision']}", f"장비 표 파서: {info['parser_revision']}"]
    if 'source_path' in info:
        lines.append(f"소스 경로: {info['source_path']}")
    return '\n'.join(lines)
