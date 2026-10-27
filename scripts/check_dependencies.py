"""Build-time PyPI advisory check. The desktop application never calls this."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote


def read_pins(path: Path) -> list[tuple[str, str]]:
    pins = []
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line.startswith('-r '):
            pins.extend(read_pins(path.parent / line[3:].strip()))
            continue
        requirement = line.split(';', 1)[0].strip()
        if '==' not in requirement:
            raise ValueError(f'고정 버전이 필요합니다: {requirement}')
        name, version = requirement.split('==', 1)
        pins.append((name, version))
    return list(dict.fromkeys(pins))


def fetch_pypi(name: str, version: str) -> dict:
    url = f'https://pypi.org/pypi/{quote(name, safe="")}/{quote(version, safe="")}/json'
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def audit(pins: list[tuple[str, str]], fetch=fetch_pypi) -> list[dict]:
    def inspect(item):
        name, version = item
        data = fetch(name, version)
        return {'package': name, 'version': version,
                'vulnerabilities': [
                    {'id': entry['id'], 'aliases': entry.get('aliases', []),
                     'fixed_in': entry.get('fixed_in', []), 'link': entry.get('link')}
                    for entry in data.get('vulnerabilities', []) if not entry.get('withdrawn')
                ]}
    with ThreadPoolExecutor(max_workers=5) as pool:
        return list(pool.map(inspect, pins))


def main() -> int:
    # Redirected Windows build output otherwise uses the legacy ANSI code page.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description='빌드 의존성 공개 보안 공지 검사')
    parser.add_argument('--requirements', type=Path, default=Path('requirements-dev.txt'))
    parser.add_argument('--output', type=Path, default=Path('artifacts/dependency-advisories.json'))
    args = parser.parse_args()
    rows = audit(read_pins(args.requirements))
    project = tomllib.loads((Path(__file__).resolve().parents[1] / 'pyproject.toml').read_text(encoding='utf-8'))
    report = {'application_version': project['project']['version'],
              'checked_at': datetime.now(UTC).isoformat(), 'source': 'PyPI version JSON advisories',
              'scope': '패키지 버전 공지 검사이며 내장 네이티브 라이브러리 전체 감사는 아닙니다.', 'packages': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    vulnerable = [row for row in rows if row['vulnerabilities']]
    print(f'의존성 {len(rows)}개 검사 · 공개 공지 영향 패키지 {len(vulnerable)}개')
    for row in vulnerable:
        print(row['package'], row['version'], ', '.join(v['id'] for v in row['vulnerabilities']))
    return 1 if vulnerable else 0


if __name__ == '__main__':
    raise SystemExit(main())
