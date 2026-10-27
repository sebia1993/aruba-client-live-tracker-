"""One-shot, user-selected discovery; no topology polling or implicit endpoint probes.

Discovery owns isolated SSH sessions so unresolved AUTO endpoints never enter the
monitoring pool's MM/MD role slots. Every session closes after its operation.
"""
from __future__ import annotations

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from ipaddress import ip_address
from pathlib import Path

from .discovery_parsers import parse_identity, parse_switches, role_kind
from .models import Credentials, Device, DeviceIdentity, Diagnostic, utc_now
from .parsers import ParseError, UnsupportedCommand, reject_errors
from .ssh import SSHError, SSHSession


@dataclass
class DiscoveryResult:
    devices: list[Device] = field(default_factory=list)
    diagnostics: list[Diagnostic] = field(default_factory=list)
    collected_at: str = field(default_factory=utc_now)


class _DiscoveryOutputs(dict[str, str]):
    def __init__(self):
        super().__init__()
        self.structures: dict[str, str] = {}


class _Cancellation(threading.Event):
    def __init__(self, external: threading.Event | None, closed: threading.Event):
        super().__init__()
        self.external = external
        self.closed = closed

    def is_set(self) -> bool:
        return (super().is_set() or self.closed.is_set()
                or (self.external is not None and self.external.is_set()))


def _endpoint(device: Device) -> tuple[str, int]:
    try:
        host = str(ip_address(device.host))
    except (TypeError, ValueError) as exc:
        raise ValueError('장비 관리 주소에는 유효한 IP를 입력하세요.') from exc
    if not isinstance(device.host, str) or type(device.port) is not int or not 1 <= device.port <= 65535:
        raise ValueError('장비 IP 및 SSH 포트 형식을 확인하세요.')
    return host, device.port


def _diagnostic(device: Device, stage: str, code: str, message: str, command: str = '',
                severity: str = '오류') -> Diagnostic:
    return Diagnostic(stage, code, message, device.name, f'{device.host}:{device.port}', command,
                      severity=severity)


def _ssh_diagnostic(device: Device, error: SSHError, command: str) -> Diagnostic:
    code = error.code if re.fullmatch(r'[A-Z_]{1,64}', error.code) else 'SSH_FAILED'
    if code.startswith(('HOST_KEY', 'KNOWN_HOSTS')):
        stage, message = 'host_key', 'SSH 서버 키를 확인하거나 안전하게 저장하지 못했습니다. 변경된 키는 관리자에게 확인하세요.'
    elif code == 'AUTH_FAILED':
        stage, message = 'auth', 'SSH 인증에 실패했습니다. 공통 계정과 조회 권한을 확인하세요.'
    elif code == 'CANCELLED':
        stage, message = 'connect', '장비 조회가 취소되었습니다.'
    else:
        stage, message = 'connect', 'SSH 연결 또는 응답을 확인하지 못했습니다.'
    return _diagnostic(device, stage, code, message, command)


def _mappings(identity: DeviceIdentity | None) -> tuple[str, ...]:
    if identity is None:
        return ()
    return tuple(dict.fromkeys(value for value in (identity.switch_ip, identity.hostname) if value))


def _mapping_key(value: str) -> str:
    """Match the collector's IP equivalence without changing explicit aliases."""
    try:
        return str(ip_address(value))
    except ValueError:
        return value


def _join_identity(old: DeviceIdentity | None, new: DeviceIdentity) -> DeviceIdentity:
    if old is None:
        return new
    return DeviceIdentity(**{key: getattr(new, key) or getattr(old, key)
                             for key in DeviceIdentity.__dataclass_fields__})


class DiscoveryService:
    def __init__(self, credentials: Credentials, known_hosts: Path):
        self.credentials = credentials
        self.known_hosts = Path(known_hosts)
        self._closed = threading.Event()
        self._lock = threading.RLock()
        self._sessions: set[SSHSession] = set()
        self._endpoint_locks: dict[tuple[str, int], threading.Lock] = {}
        self._capacity = threading.BoundedSemaphore(2)

    def _read(self, device: Device, commands: tuple[str, ...], cancel: threading.Event | None):
        """Serialize a whole identity operation per endpoint, with two sessions total."""
        linked = _Cancellation(cancel, self._closed)
        outputs = _DiscoveryOutputs()
        diagnostics: list[Diagnostic] = []
        endpoint = _endpoint(device)
        with self._lock:
            endpoint_lock = self._endpoint_locks.setdefault(endpoint, threading.Lock())
        capacity = acquired = False
        session = None
        command = ''
        try:
            while not acquired:
                if linked.is_set():
                    raise SSHError('CANCELLED', '조회가 취소되었습니다.')
                acquired = endpoint_lock.acquire(timeout=0.05)
            while not capacity:
                if linked.is_set():
                    raise SSHError('CANCELLED', '조회가 취소되었습니다.')
                capacity = self._capacity.acquire(timeout=0.05)
            with self._lock:
                if linked.is_set():
                    raise SSHError('CANCELLED', '조회가 취소되었습니다.')
                session = SSHSession(device, self.credentials, self.known_hosts, None)
                self._sessions.add(session)
            for command in commands:
                if linked.is_set():
                    raise SSHError('CANCELLED', '조회가 취소되었습니다.')
                output = session.run(command, cancel=linked)
                if isinstance(session, SSHSession) and hasattr(session, 'read_structure_summary'):
                    outputs.structures[command] = session.read_structure_summary()
                try:
                    reject_errors(output)
                except UnsupportedCommand:
                    diagnostics.append(_diagnostic(device, 'discovery' if command == 'show switches' else 'identity',
                        'COMMAND_REJECTED', '조회 명령이 거부되었습니다. 지원 여부와 조회 권한을 확인하세요.', command))
                except ParseError:
                    diagnostics.append(_diagnostic(device, 'discovery' if command == 'show switches' else 'identity',
                        'EMPTY_OR_INVALID_OUTPUT', '조회 명령의 응답이 없거나 형식을 확인할 수 없습니다.', command))
                else:
                    outputs[command] = output
        except SSHError as exc:
            item = _ssh_diagnostic(device, exc, command)
            if command == 'show switches' and session is not None and hasattr(session, 'read_structure_summary'):
                structure = session.read_structure_summary()
                if structure:
                    item.message += '\n수집 진단: ' + structure
            diagnostics.append(item)
        except Exception:
            diagnostics.append(_diagnostic(device, 'connect', 'DISCOVERY_FAILED',
                                           '장비 조회를 완료하지 못했습니다.', command))
        finally:
            if session is not None:
                session.close()
                with self._lock:
                    self._sessions.discard(session)
            if capacity:
                self._capacity.release()
            if acquired:
                endpoint_lock.release()
        return outputs, diagnostics

    @staticmethod
    def _self_identity(device: Device, outputs: dict[str, str], diagnostics: list[Diagnostic]):
        try:
            return parse_identity(outputs.get('show switchinfo', ''), outputs.get('show version', ''))
        except ParseError:
            diagnostics.append(_diagnostic(device, 'identity', 'IDENTITY_PARSE_FAILED',
                '장비 식별 응답을 해석하지 못했습니다.', 'show switchinfo'))
            # A bad switchinfo must not discard independently usable version evidence.
            return parse_identity('', outputs.get('show version', ''))

    def discover(self, seed: Device, cancel: threading.Event | None = None) -> DiscoveryResult:
        outputs, diagnostics = self._read(seed, ('show switches', 'show switchinfo', 'show version'), cancel)
        identity = self._self_identity(seed, outputs, diagnostics)
        rows: list[DeviceIdentity] = []
        if 'show switches' in outputs:
            try:
                rows = parse_switches(outputs['show switches'])
            except ParseError as exc:
                # Parser reasons include only fixed text and structural counts,
                # never remote rows or field values. Do not append raw CLI.
                structure = getattr(outputs, 'structures', {}).get('show switches', '')
                message = f'장비 목록을 해석하지 못했습니다. {exc}'
                if structure:
                    message += '\n수집 진단: ' + structure
                diagnostics.append(_diagnostic(seed, 'discovery', 'SWITCH_TABLE_PARSE_FAILED',
                    message, 'show switches'))
        # An endpoint match is definitive. Otherwise self identity must select
        # exactly one row; conflicts across address and hostname remain unresolved.
        matches = [row for row in rows if row.switch_ip == _endpoint(seed)[0]]
        if not matches:
            matches = [row for row in rows if
                       (identity.switch_ip and row.switch_ip == identity.switch_ip)
                       or (identity.hostname and row.hostname.casefold() == identity.hostname.casefold())]
        matched = matches[0] if len(matches) == 1 else None
        if matched and identity.switch_ip and identity.switch_ip != matched.switch_ip:
            diagnostics.append(_diagnostic(seed, 'identity', 'IDENTITY_CONFLICT',
                'SSH 주소의 목록 행과 현재 장비의 자체 IP가 달라 목록 역할을 적용하지 않았습니다.', severity='주의'))
            matched = None
        combined = _join_identity(matched, identity) if matched else identity
        # A known table Type is stronger than legacy self switchrole:master/local.
        if matched and role_kind(combined.reported_role) == 'AUTO':
            combined = replace(combined, reported_role=matched.reported_role)
        resolved = role_kind(combined.reported_role)
        if matched and role_kind(matched.reported_role) != 'AUTO' and resolved != role_kind(matched.reported_role):
            diagnostics.append(_diagnostic(seed, 'identity', 'ROLE_CONFLICT',
                '목록의 역할과 장비 자체 역할이 달라 자동 확정하지 않았습니다.'))
            resolved = 'AUTO'
        kind = resolved if seed.kind == 'AUTO' else seed.kind
        seed_device = replace(seed, kind=kind, identity=combined, origin='discovered',
                              mappings=seed.mappings or (_mappings(combined) if kind == 'MD' else ()))
        devices = [seed_device]
        for row in rows:
            if row is matched:
                continue
            row_kind = role_kind(row.reported_role)
            devices.append(Device(row.hostname[:100], row.switch_ip, row_kind, identity=row, origin='discovered',
                                  mappings=_mappings(row) if row_kind == 'MD' else ()))
        if kind == 'AUTO':
            diagnostics.append(_diagnostic(seed, 'identity', 'IDENTITY_UNRESOLVED',
                '장비 역할을 확정하지 못했습니다. 모델명이나 표시 이름으로 역할을 추정하지 않습니다.', severity='주의'))
        # Assign safe distinct display names; do not treat names as endpoint identity.
        devices, name_diagnostics = merge_discovered([], devices)
        return DiscoveryResult(devices, diagnostics + name_diagnostics)

    def _probe_one(self, device: Device, cancel: threading.Event | None):
        outputs, diagnostics = self._read(device, ('show switchinfo', 'show version'), cancel)
        identity = self._self_identity(device, outputs, diagnostics)
        stale_identity = bool(device.identity and identity.switch_ip and device.identity.switch_ip
                              and identity.switch_ip != device.identity.switch_ip)
        if stale_identity:
            diagnostics.append(_diagnostic(device, 'identity', 'IDENTITY_CONFLICT',
                '기존 식별 IP와 현재 장비의 자체 IP가 달라 현재 응답만 사용합니다.', severity='주의'))
        previous_identity = None if stale_identity else device.identity
        existing_kind = role_kind(previous_identity.reported_role) if previous_identity else 'AUTO'
        self_kind = role_kind(identity.reported_role)
        combined = _join_identity(previous_identity, identity)
        if existing_kind != 'AUTO' and self_kind == 'AUTO' and device.identity:
            combined = replace(combined, reported_role=device.identity.reported_role)
        kind = 'AUTO' if stale_identity and device.origin == 'discovered' else device.kind
        if existing_kind != 'AUTO' and self_kind != 'AUTO' and existing_kind != self_kind:
            diagnostics.append(_diagnostic(device, 'identity', 'ROLE_CONFLICT',
                '장비 목록과 자체 역할이 서로 다릅니다. 역할을 확인하세요.'))
            if device.origin == 'discovered':
                kind = 'AUTO'
        elif kind == 'AUTO':
            kind = role_kind(combined.reported_role)
        elif self_kind != 'AUTO' and kind != self_kind:
            diagnostics.append(_diagnostic(device, 'identity', 'ROLE_CONFLICT',
                '등록된 장비 유형과 자체 역할이 다릅니다. 수동 설정을 확인하세요.'))
        mappings = () if stale_identity and device.origin == 'discovered' else device.mappings
        if (device.origin == 'discovered' and kind == 'MD' and previous_identity
                and identity.hostname and identity.hostname != previous_identity.hostname):
            old_aliases = {_mapping_key(alias) for alias in _mappings(previous_identity)}
            explicit = tuple(alias for alias in mappings if _mapping_key(alias) not in old_aliases)
            mappings = tuple(dict.fromkeys((*explicit, *_mappings(combined))))
        result = replace(device, identity=combined, kind=kind,
                         mappings=mappings or (_mappings(combined) if kind == 'MD' else ()))
        if kind == 'AUTO':
            diagnostics.append(_diagnostic(device, 'identity', 'IDENTITY_UNRESOLVED',
                '장비 역할을 확정하지 못해 활성 추적에서 제외됩니다.', severity='주의'))
        return result, diagnostics

    def probe(self, devices: list[Device], cancel: threading.Event | None = None) -> DiscoveryResult:
        unique, diagnostics = merge_discovered([], devices)
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='aruba-discovery') as executor:
            futures = [executor.submit(self._probe_one, device, cancel) for device in unique]
            results = [future.result() for future in futures]
        return DiscoveryResult([device for device, _ in results],
                               diagnostics + [item for _, items in results for item in items])

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            sessions = list(self._sessions)
        for session in sessions:
            session.close()


def merge_discovered(existing: list[Device], discovered: list[Device]) -> tuple[list[Device], list[Diagnostic]]:
    """Merge on SSH endpoint, preserving explicit manual names, roles and mappings."""
    merged = list(existing)
    diagnostics: list[Diagnostic] = []
    endpoints = {_endpoint(device): i for i, device in enumerate(merged)}
    names = {device.name for device in merged}
    for device in discovered:
        endpoint = _endpoint(device)
        if endpoint in endpoints:
            index = endpoints[endpoint]
            old = merged[index]
            auto_resolution = (old.kind == 'AUTO' and device.kind != 'AUTO' and device.identity is not None
                               and role_kind(device.identity.reported_role) == device.kind)
            identity_conflict = bool(old.identity and device.identity and old.identity.switch_ip
                                     and device.identity.switch_ip
                                     and old.identity.switch_ip != device.identity.switch_ip)
            if auto_resolution and not identity_conflict:
                aliases = _mappings(device.identity) if device.kind == 'MD' else ()
                # Explicit mappings stay first; only verified IP/hostname aliases are appended.
                merged[index] = replace(old, kind=device.kind,
                    identity=_join_identity(old.identity, device.identity),
                    mappings=tuple(dict.fromkeys((*old.mappings, *aliases))))
                continue
            conflict = ((device.kind != 'AUTO' and old.kind != 'AUTO' and old.kind != device.kind)
                        or (bool(old.mappings) and bool(device.mappings) and old.mappings != device.mappings)
                        or (old.identity is not None and device.identity is not None
                            and old.identity.switch_ip and device.identity.switch_ip
                            and old.identity.switch_ip != device.identity.switch_ip))
            fresh_self_report = bool(device.identity and 'show switchinfo' in device.identity.source.split(', '))
            if conflict:
                message = '같은 SSH 주소의 기존 유형·매핑·식별 정보와 발견 결과가 다릅니다.'
                if old.origin == 'manual':
                    message += ' 기존 수동 설정을 보존했습니다.'
                elif fresh_self_report:
                    message += ' 현재 장비의 자체 응답으로 발견 정보를 갱신했습니다.'
                diagnostics.append(_diagnostic(old, 'identity', 'CONFIG_CONFLICT', message, severity='주의'))
            if conflict and old.origin == 'discovered' and fresh_self_report:
                # A selected endpoint's new self report supersedes stale topology metadata.
                merged[index] = replace(device, name=old.name, origin='discovered')
                continue
            if old.origin == 'manual' or conflict:
                # Metadata may be refreshed only when its physical switch identity agrees.
                if not conflict and device.identity:
                    merged[index] = replace(old, identity=_join_identity(old.identity, device.identity))
                continue
            merged[index] = replace(device, name=old.name, origin='discovered',
                                    identity=_join_identity(old.identity, device.identity) if device.identity else old.identity)
            continue
        name = device.name
        if name in names:
            suffix = f' ({device.host})'
            name = f'{device.name[:100 - len(suffix)]}{suffix}'
            serial = 2
            while name in names:
                suffix = f' ({device.host}, {serial})'
                name = f'{device.name[:100 - len(suffix)]}{suffix}'
                serial += 1
            diagnostics.append(_diagnostic(device, 'discovery', 'NAME_COLLISION',
                '서로 다른 SSH 주소의 표시 이름이 같아 주소를 붙였습니다.', severity='주의'))
        endpoints[endpoint] = len(merged)
        names.add(name)
        merged.append(replace(device, name=name))
    # The active collector also matches each MD's SSH host. Automatic aliases
    # must never claim another endpoint or shared hostname arbitrarily.
    alias_owners: dict[str, set[tuple[str, int]]] = {}
    manual_mappings = {_endpoint(device): {_mapping_key(alias) for alias in device.mappings}
                       for device in existing if device.origin == 'manual'}
    for device in merged:
        if device.kind == 'MD':
            for alias in (device.host, *device.mappings):
                alias_owners.setdefault(_mapping_key(alias), set()).add(_endpoint(device))
    for index, device in enumerate(merged):
        if device.kind != 'MD':
            continue
        endpoint = _endpoint(device)
        automatic = {_mapping_key(alias) for alias in _mappings(device.identity)}
        if device.origin == 'manual':
            automatic -= manual_mappings.get(endpoint, {_mapping_key(alias) for alias in device.mappings})
        conflicted = {_mapping_key(alias) for alias in device.mappings
                      if len(alias_owners.get(_mapping_key(alias), ())) > 1}
        if conflicted:
            diagnostics.append(_diagnostic(device, 'md_mapping', 'MAPPING_CONFLICT',
                '여러 WLC가 같은 매핑을 사용합니다. 충돌한 자동 별칭을 제외하고 수동 매핑을 보존했습니다.', severity='주의'))
            merged[index] = replace(device, mappings=tuple(alias for alias in device.mappings
                if _mapping_key(alias) not in conflicted or _mapping_key(alias) not in automatic))
    return merged, diagnostics
