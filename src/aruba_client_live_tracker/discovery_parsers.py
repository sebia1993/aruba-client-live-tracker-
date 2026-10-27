"""Strict discovery parsers. Role evidence never comes from a model or display name."""
from __future__ import annotations

import re
from ipaddress import IPv4Address, IPv4Network, ip_address

from .models import DeviceIdentity, utc_now
from .parsers import ParseError, reject_errors

_ROLE_KINDS = {'conductor': 'MM_PRIMARY', 'standby': 'MM_STANDBY', 'md': 'MD'}
_SAFE_NAME = re.compile(r'[A-Za-z0-9_.:\-]{1,128}\Z')


def role_kind(role: str) -> str:
    return _ROLE_KINDS.get(role.strip().casefold(), 'AUTO')


_CONTINUATION_COLUMNS = {
    ('Status', 'Configuration State', 'Config Sync Time (sec)', 'Config ID'),
    ('Status', 'Uptime', 'CrashInfo', 'Config Sync Time (sec)', 'License', 'Release Type'),
}


def _switch_layout(lines: list[str], header_index: int) -> tuple[list[str], list[int], int]:
    header = lines[header_index]
    separator_index = header_index + 1
    while separator_index < len(lines) and not lines[separator_index].strip():
        separator_index += 1
    if separator_index >= len(lines) or not re.fullmatch(r'\s*-+(?:\s+-+)*\s*', lines[separator_index]):
        raise ParseError('장비 표 열 구분선을 인식하지 못했습니다.')
    spans = list(re.finditer(r'-+', lines[separator_index]))
    if len(spans) == 1:
        starts = [m.start() for m in re.finditer(r'\S(?:.*?\S)?(?=\s{2,}|$)', header)]
    else:
        starts = [m.start() for m in spans]
    labels = [re.sub(r'\s+', ' ', header[start:starts[i + 1] if i + 1 < len(starts) else None].strip())
              for i, start in enumerate(starts)]
    labels = [label.replace('Config Sync Time(sec)', 'Config Sync Time (sec)') for label in labels]
    if not labels or not all(labels) or len(set(labels)) != len(labels):
        raise ParseError('장비 표 열 위치를 인식하지 못했습니다.')
    return labels, starts, separator_index + 1


def _switch_cells(line: str, labels: list[str], starts: list[int]) -> dict[str, str]:
    if line[:starts[0]].strip():
        raise ParseError('장비 표 데이터의 열 위치가 올바르지 않습니다.')
    return {label: line[start:starts[i + 1] if i + 1 < len(starts) else None].strip()
            for i, (label, start) in enumerate(zip(labels, starts))}


def parse_switches(output: str) -> list[DeviceIdentity]:
    """Read flat or horizontal tables, requiring each block's full declared count."""
    reject_errors(output)
    lines = output.splitlines()
    totals = list(re.finditer(r'(?im)^\s*Total\s+Switches\s*:\s*(\d+)\s*$', output))
    if len(totals) != 1 or int(totals[0].group(1)) > 1000:
        raise ParseError('장비 표의 완료 건수가 없거나 허용 범위를 초과했습니다.')
    expected = int(totals[0].group(1))
    header_index = next((i for i, line in enumerate(lines)
                         if all(label in line for label in ('IP Address', 'Name', 'Type'))), None)
    if header_index is None:
        raise ParseError('장비 표 머리글을 인식하지 못했습니다.')
    labels, starts, index = _switch_layout(lines, header_index)
    if not all(label in labels for label in ('IP Address', 'Name', 'Type')):
        raise ParseError('장비 표 열 위치를 인식하지 못했습니다.')
    rows = []
    complete = False
    addresses = set()
    continuation_count = None
    while index < len(lines):
        line = lines[index]
        index += 1
        if not line.strip():
            continue
        if re.fullmatch(r'\s*Total\s+Switches\s*:\s*\d+\s*', line, re.I):
            complete = True
            continue
        if complete:
            # SSH strips the prompt; tolerate one for standalone parser callers.
            if re.fullmatch(r'\s*(?:\([^\r\n]{1,100}\)\s*)?[\w.*^:\[\] -]*[#>]\s*', line):
                continue
            raise ParseError('완료 건수 뒤에 알 수 없는 데이터가 있습니다.')
        if line.lstrip().startswith('Status'):
            if continuation_count is not None:
                raise ParseError('장비 보조 표가 중복되어 목록을 확정할 수 없습니다.')
            if len(rows) != expected:
                raise ParseError('장비 식별 표 완료 건수와 실제 행 수가 다릅니다.')
            labels, starts, index = _switch_layout(lines, index - 1)
            if tuple(labels) not in _CONTINUATION_COLUMNS:
                raise ParseError('장비 보조 표 머리글을 인식하지 못했습니다.')
            continuation_count = 0
            continue
        cells = _switch_cells(line, labels, starts)
        if continuation_count is not None:
            # Status is not role evidence. Validate the whole continuation instead
            # of silently skipping lines that could be truncated or injected rows.
            if (any(not value or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)
                    for value in cells.values())
                    or not re.fullmatch(r'[A-Za-z][A-Za-z _/-]{0,63}|-+', cells['Status'])
                    or not re.fullmatch(r'\d+|N/A|-', cells['Config Sync Time (sec)'], re.I)
                    or ('Config ID' in cells and not re.fullmatch(r'\d+|N/A|-', cells['Config ID'], re.I))):
                raise ParseError('장비 보조 표의 상태 행이 불완전하거나 형식이 올바르지 않습니다.')
            continuation_count += 1
            if continuation_count > expected:
                raise ParseError('장비 보조 표 완료 건수와 실제 행 수가 다릅니다.')
            continue
        try:
            address = str(ip_address(cells['IP Address']))
        except ValueError as exc:
            raise ParseError('장비 표의 IP 형식이 올바르지 않습니다.') from exc
        hostname = cells['Name']
        if not _SAFE_NAME.fullmatch(hostname) or address in addresses:
            raise ParseError('장비 표 이름 또는 중복 IP를 확인하세요.')
        values = [cells.get(key, '') for key in ('Type', 'Model', 'Version')]
        if any(len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value) for value in values):
            raise ParseError('장비 식별 정보 형식을 확인하세요.')
        addresses.add(address)
        rows.append(DeviceIdentity(hostname, address, *values, utc_now(), 'show switches'))
        if len(rows) > expected:
            raise ParseError('장비 표 완료 건수와 실제 행 수가 다릅니다.')
    if not complete or len(rows) != expected:
        raise ParseError('장비 표 완료 건수와 실제 행 수가 다릅니다.')
    if continuation_count is not None and continuation_count != expected:
        raise ParseError('장비 보조 표 완료 건수와 실제 행 수가 다릅니다.')
    return rows


def parse_identity(switchinfo: str = '', version: str = '') -> DeviceIdentity:
    """Optional self-identity fields; unsupported commands are checked by caller."""
    for output in (switchinfo, version):
        if output:
            reject_errors(output)
    def field(labels: str) -> str:
        match = re.search(r'(?im)^\s*(?:' + labels + r')(?:\s*[:=]\s*|\s+is\s+)([^\r\n]*)', switchinfo)
        return match.group(1).strip() if match else ''
    hostname = field('hostname|switchname|switch name')
    if hostname and not _SAFE_NAME.fullmatch(hostname):
        raise ParseError('장비 식별 이름 형식이 올바르지 않습니다.')
    address = field('Internet address|IP Address|switch IP|switchip')
    if address:
        try:
            parts = address.split()
            if len(parts) == 2:
                # Official switchinfo prints IPv4 and subnet mask; no other suffix is accepted.
                parsed_address = IPv4Address(parts[0])
                IPv4Address(parts[1])
                IPv4Network(f'{parsed_address}/{parts[1]}', strict=False)
                address = str(parsed_address)
            elif len(parts) == 1:
                address = str(ip_address(parts[0]))
            else:
                raise ValueError('address token count')
        except ValueError as exc:
            raise ParseError('장비 식별 IP 형식이 올바르지 않습니다.') from exc
    role = field('switchrole|switch role|role|type')
    model = field('model')
    match = re.search(r'(?i)\bMODEL\s*:\s*([A-Za-z0-9_.-]{1,128})', version)
    if match:
        model = match.group(1)
    match = re.search(r'(?i)\bVersion\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,127})', version)
    software_version = match.group(1) if match else ''
    if any(len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)
           for value in (role, model)):
        raise ParseError('장비 식별 정보 형식을 확인하세요.')
    sources = [command for command, text in [('show switchinfo', switchinfo), ('show version', version)] if text]
    return DeviceIdentity(hostname, address, role, model, software_version, utc_now(), ', '.join(sources))
