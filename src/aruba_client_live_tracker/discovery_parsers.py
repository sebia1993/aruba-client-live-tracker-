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


def parse_switches(output: str) -> list[DeviceIdentity]:
    """Read every type, requiring a complete table and explicit completion count."""
    reject_errors(output)
    lines = output.splitlines()
    totals = list(re.finditer(r'(?im)^\s*Total\s+Switches\s*:\s*(\d+)\s*$', output))
    if len(totals) != 1 or int(totals[0].group(1)) > 1000:
        raise ParseError('장비 표의 완료 건수가 없거나 허용 범위를 초과했습니다.')
    header_index = next((i for i, line in enumerate(lines)
                         if all(label in line for label in ('IP Address', 'Name', 'Type'))), None)
    if header_index is None:
        raise ParseError('장비 표 머리글을 인식하지 못했습니다.')
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
    labels = [header[start:starts[i + 1] if i + 1 < len(starts) else None].strip()
              for i, start in enumerate(starts)]
    if not all(label in labels for label in ('IP Address', 'Name', 'Type')) or len(set(labels)) != len(labels):
        raise ParseError('장비 표 열 위치를 인식하지 못했습니다.')
    rows = []
    complete = False
    addresses = set()
    for line in lines[separator_index + 1:]:
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
        cells = {label: line[start:starts[i + 1] if i + 1 < len(starts) else None].strip()
                 for i, (label, start) in enumerate(zip(labels, starts))}
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
        if len(rows) > 1000:
            raise ParseError('장비 표가 허용 행 수를 초과했습니다.')
    if not complete or len(rows) != int(totals[0].group(1)):
        raise ParseError('장비 표 완료 건수와 실제 행 수가 다릅니다.')
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
