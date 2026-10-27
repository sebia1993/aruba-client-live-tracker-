"""Local non-secret settings. Credentials never belong in this schema."""
from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict
from ipaddress import ip_address
from pathlib import Path

from platformdirs import user_data_dir

from .models import Device


def data_dir() -> Path:
    path = Path(user_data_dir('ArubaClientLiveTracker', appauthor=False))
    path.mkdir(parents=True, exist_ok=True)
    return path


def _validate(devices: list[Device]) -> None:
    names = set()
    roles = set()
    for device in devices:
        if not device.name or len(device.name) > 100 or any(ord(c) < 32 for c in device.name):
            raise ValueError('장비 이름은 제어 문자 없이 1~100자로 입력하세요.')
        if device.name in names:
            raise ValueError('장비 이름이 중복되었습니다.')
        names.add(device.name)
        try:
            ip_address(device.host)
        except ValueError as exc:
            raise ValueError('장비 관리 주소에는 유효한 IP를 입력하세요.') from exc
        if type(device.port) is not int or not 1 <= device.port <= 65535:
            raise ValueError('SSH 포트는 1~65535 범위입니다.')
        if type(device.enabled) is not bool or device.kind not in ('MM_PRIMARY', 'MM_STANDBY', 'MD'):
            raise ValueError('장비 유형 또는 사용 여부가 올바르지 않습니다.')
        if device.enabled and device.kind != 'MD':
            if device.kind in roles:
                raise ValueError('사용 중인 Primary/Standby MM은 각각 하나만 등록하세요.')
            roles.add(device.kind)
        if not isinstance(device.mappings, (tuple, list)) or any(
            not isinstance(x, str) or not re.fullmatch(r'[A-Za-z0-9_.:\-]{1,128}', x)
            for x in device.mappings
        ):
            raise ValueError('MD 매핑에는 IP 또는 안전한 장비 이름만 사용할 수 있습니다.')


def load_devices(path: Path) -> list[Device]:
    path = Path(path)
    if not path.exists():
        return []
    if path.stat().st_size > 1024 * 1024:
        raise ValueError('설정 파일이 너무 큽니다.')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or set(data) - {'version','devices'} or data.get('version',1) != 1:
            raise ValueError('지원하지 않는 설정 형식입니다. 계정/비밀번호는 저장하지 마세요.')
        if not isinstance(data.get('devices'), list) or len(data['devices']) > 1000:
            raise ValueError('장비 설정 목록이 올바르지 않습니다.')
        devices = []
        for item in data['devices']:
            item = dict(item)
            item['mappings'] = tuple(item.get('mappings', ()))
            devices.append(Device(**item))
        _validate(devices)
        return devices
    except (TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('장비 설정 파일 형식을 확인하세요.') from exc


def save_devices(path: Path, devices: list[Device]) -> None:
    _validate(devices)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.settings-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump({'version': 1, 'devices': [asdict(d) for d in devices]}, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
