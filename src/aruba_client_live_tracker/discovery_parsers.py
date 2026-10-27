"""Strict discovery parsers. Role evidence never comes from a model or display name."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv4Network, IPv6Address, ip_address

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
_STATUS_COLUMNS = frozenset().union(*_CONTINUATION_COLUMNS)
_KNOWN_COLUMNS = _STATUS_COLUMNS | {
    'IP Address', 'IPv6 Address', 'Name', 'Location', 'Nodepath', 'MAC', 'Type', 'Model', 'Version',
}
SWITCH_PARSER_VERSION = '2'


@dataclass
class _SwitchStructure:
    """Only counts, known column labels and positions may reach diagnostics."""
    lines: int
    completion_markers: int
    expected: int | None = None
    block: str = 'header'
    line_number: int = 0
    line_length: int = 0
    leading: int = 0
    whitespace_runs: int = 0
    letters: int = 0
    digits: int = 0
    other: int = 0
    identities: int = 0
    statuses: int = 0
    repeats: int = 0
    labels: list[str] = field(default_factory=list)
    starts: list[int] = field(default_factory=list)

    def observe(self, line: str, number: int) -> None:
        self.line_number, self.line_length = number, len(line)
        self.leading = len(line) - len(line.lstrip())
        self.whitespace_runs = len(re.findall(r'\s+', line))
        self.letters = sum(char.isalpha() for char in line)
        self.digits = sum(char.isdigit() for char in line)
        self.other = sum(not char.isspace() and not char.isalnum() for char in line)

    def summary(self) -> str:
        columns = ', '.join(
            f'{label if label in _KNOWN_COLUMNS else "unknown"}[{start}:'
            f'{self.starts[i + 1] if i + 1 < len(self.starts) else "end"}]'
            for i, (label, start) in enumerate(zip(self.labels, self.starts)))
        return (f'파서={SWITCH_PARSER_VERSION} · 기준=정규화 출력 1부터 · 출력 {self.line_number}행 · '
                f'파싱 행={self.lines} · 표={self.block} · 행 길이={self.line_length} · '
                f'선행 공백={self.leading} · 공백 구간={self.whitespace_runs} · '
                f'문자 유형={self.letters}/{self.digits}/{self.other} · '
                f'선언={self.expected if self.expected is not None else "unknown"} · '
                f'식별 행={self.identities} · 상태 행={self.statuses} · '
                f'반복 머리글={self.repeats} · 완료 표식={self.completion_markers} · '
                f'열 위치(0부터)={columns}')


def _switch_layout(lines: list[str], header_index: int) -> tuple[list[str], list[int], int]:
    header = lines[header_index]
    separator_index = header_index + 1
    while separator_index < len(lines) and not lines[separator_index].strip():
        separator_index += 1
    if separator_index >= len(lines) or not re.fullmatch(r'\s*-+(?:\s+-+)*\s*', lines[separator_index]):
        raise ParseError('[TABLE_LAYOUT] 장비 표 열 구분선을 인식하지 못했습니다.')
    spans = list(re.finditer(r'-+', lines[separator_index]))
    if len(spans) == 1:
        starts = [m.start() for m in re.finditer(r'\S(?:.*?\S)?(?=\s{2,}|$)', header)]
    else:
        starts = [m.start() for m in spans]
    labels = [re.sub(r'\s+', ' ', header[start:starts[i + 1] if i + 1 < len(starts) else None].strip())
              for i, start in enumerate(starts)]
    labels = [label.replace('Config Sync Time(sec)', 'Config Sync Time (sec)') for label in labels]
    if not labels or not all(labels) or len(set(labels)) != len(labels):
        raise ParseError('[TABLE_LAYOUT] 장비 표 열 위치를 인식하지 못했습니다.')
    return labels, starts, separator_index + 1


def _switch_cells(line: str, labels: list[str], starts: list[int]) -> dict[str, str]:
    if line[:starts[0]].strip():
        raise ParseError('[TABLE_LAYOUT] 장비 표 데이터의 열 위치가 올바르지 않습니다.')
    return {label: line[start:starts[i + 1] if i + 1 < len(starts) else None].strip()
            for i, (label, start) in enumerate(zip(labels, starts))}


def _switch_address(cells: dict[str, str], line_number: int) -> str:
    ipv4, ipv6 = cells['IP Address'], cells.get('IPv6 Address', '')
    # The AOS 8.10 User Guide (p. 861) documents None in IP Address for
    # IPv6-only rows. Keep IPv4 preference; a malformed IPv4 is not absence.
    structure = (f'(출력 {line_number}행 · IP 열 길이 {len(ipv4)} · '
                 f'IPv6 열 길이 {len(ipv6)})')
    if not ipv4:
        raise ParseError(f'[ADDRESS_CELL_EMPTY] 장비 표의 주소 셀이 비어 있습니다. '
                         f'열 위치 또는 잘린 행을 확인하세요. {structure}')
    if ipv4.casefold() == 'none' and (not ipv6 or ipv6.casefold() == 'none'):
        raise ParseError(f'장비 표에 사용 가능한 IP 주소가 없는 행이 있습니다. {structure}')
    try:
        return str(IPv6Address(ipv6) if ipv4.casefold() == 'none' else ip_address(ipv4))
    except ValueError:
        # Expose only position/lengths: remote values or underlying exception
        # text may contain operational addresses, names or injected content.
        raise ParseError(f'[ADDRESS_INVALID] 장비 표의 IP 형식이 올바르지 않습니다. {structure}') from None


def _validate_switch_status(cells: dict[str, str]) -> None:
    """Validate declared status fields equally in flat and continuation tables."""
    status = {key: value for key, value in cells.items() if key in _STATUS_COLUMNS}
    if (any(not value or len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)
            for value in status.values())
            or ('Status' in status and not re.fullmatch(r'[A-Za-z][A-Za-z _/-]{0,63}|-+', status['Status']))
            or any(key in status and not re.fullmatch(r'\d+|N/A|-', status[key], re.I)
                   for key in ('Config Sync Time (sec)', 'Config ID'))):
        raise ParseError('장비 보조 표의 상태 행이 불완전하거나 형식이 올바르지 않습니다.')


def parse_switches(output: str) -> list[DeviceIdentity]:
    """Read flat or horizontal tables, requiring each block's full declared count."""
    state = _SwitchStructure(len(output.splitlines()), len(re.findall(
        r'(?im)^\s*Total\s+Switches\s*:\s*\d+\s*$', output)))
    try:
        return _parse_switches(output, state)
    except ParseError as exc:
        raise ParseError(f'{exc}\n구조 진단: {state.summary()}') from None


def _parse_switches(output: str, state: _SwitchStructure) -> list[DeviceIdentity]:
    reject_errors(output)
    lines = output.splitlines()
    totals = list(re.finditer(r'(?im)^\s*Total\s+Switches\s*:\s*(\d+)\s*$', output))
    if not totals:
        raise ParseError('[OUTPUT_INCOMPLETE] 장비 표의 완료 건수가 없습니다.')
    if len(totals) != 1 or int(totals[0].group(1)) > 1000:
        raise ParseError('장비 표의 완료 건수가 없거나 허용 범위를 초과했습니다.')
    expected = int(totals[0].group(1))
    state.expected = expected
    header_index = next((i for i, line in enumerate(lines)
                         if all(label in line for label in ('IP Address', 'Name', 'Type'))), None)
    if header_index is None:
        raise ParseError('[HEADER_NOT_FOUND] 장비 표 머리글을 인식하지 못했습니다.')
    state.observe(lines[header_index], header_index + 1)
    labels, starts, index = _switch_layout(lines, header_index)
    state.labels, state.starts = labels, starts
    if not all(label in labels for label in ('IP Address', 'Name', 'Type')):
        raise ParseError('장비 표 열 위치를 인식하지 못했습니다.')
    rows = []
    complete = False
    addresses = set()
    continuation_count = None
    header_text = re.sub(r'\s+', ' ', lines[header_index].strip())
    state.block = 'identity'
    while index < len(lines):
        line = lines[index]
        index += 1
        state.observe(line, index)
        if not line.strip():
            continue
        if re.fullmatch(r'\s*Total\s+Switches\s*:\s*\d+\s*', line, re.I):
            complete = True
            continue
        if complete:
            # SSH strips the prompt; tolerate one for standalone parser callers.
            if re.fullmatch(r'\s*(?:\([^\r\n]{1,100}\)\s*)?[\w.*^:\[\] -]*[#>]\s*', line):
                continue
            raise ParseError('[UNKNOWN_ROW] 완료 건수 뒤에 알 수 없는 데이터가 있습니다.')
        if re.sub(r'\s+', ' ', line.strip()) == header_text:
            repeated_labels, repeated_starts, index = _switch_layout(lines, index - 1)
            if repeated_labels != labels:
                raise ParseError('[TABLE_LAYOUT] 반복 머리글의 열 구성이 바뀌었습니다.')
            starts = repeated_starts
            state.starts = starts
            state.repeats += 1
            continue
        if line.lstrip().startswith('Status'):
            if continuation_count is not None:
                raise ParseError('장비 보조 표가 중복되어 목록을 확정할 수 없습니다.')
            if len(rows) != expected:
                raise ParseError('[COUNT_MISMATCH] 장비 식별 표 완료 건수와 실제 행 수가 다릅니다.')
            labels, starts, index = _switch_layout(lines, index - 1)
            state.labels, state.starts, state.block = labels, starts, 'status'
            if tuple(labels) not in _CONTINUATION_COLUMNS:
                raise ParseError('[UNKNOWN_TABLE] 장비 보조 표 머리글을 인식하지 못했습니다.')
            continuation_count = 0
            header_text = re.sub(r'\s+', ' ', line.strip())
            continue
        if continuation_count is None and len(line) <= starts[labels.index('Name')]:
            raise ParseError('[ROW_TOO_SHORT] 장비 식별 행이 필수 열보다 짧습니다.')
        cells = _switch_cells(line, labels, starts)
        _validate_switch_status(cells)
        if continuation_count is not None:
            # Status is not role evidence. Validate the whole continuation instead
            # of silently skipping lines that could be truncated or injected rows.
            continuation_count += 1
            state.statuses = continuation_count
            if continuation_count > expected:
                raise ParseError('[COUNT_MISMATCH] 장비 보조 표 완료 건수와 실제 행 수가 다릅니다.')
            continue
        address = _switch_address(cells, index)
        hostname = cells['Name']
        if not _SAFE_NAME.fullmatch(hostname) or address in addresses:
            raise ParseError('장비 표 이름 또는 중복 IP를 확인하세요.')
        values = [cells.get(key, '') for key in ('Type', 'Model', 'Version')]
        if any(len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value) for value in values):
            raise ParseError('장비 식별 정보 형식을 확인하세요.')
        addresses.add(address)
        rows.append(DeviceIdentity(hostname, address, *values, utc_now(), 'show switches'))
        state.identities = len(rows)
        if len(rows) > expected:
            raise ParseError('[COUNT_MISMATCH] 장비 표 완료 건수와 실제 행 수가 다릅니다.')
    if not complete or len(rows) != expected:
        raise ParseError('[COUNT_MISMATCH] 장비 표 완료 건수와 실제 행 수가 다릅니다.')
    if continuation_count is not None and continuation_count != expected:
        raise ParseError('[COUNT_MISMATCH] 장비 보조 표 완료 건수와 실제 행 수가 다릅니다.')
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
    switch_model = model = field('model')
    match = re.search(r'(?i)\bMODEL\s*:\s*([A-Za-z0-9_.-]{1,128})', version)
    version_model = match.group(1) if match else ''
    if match:
        model = version_model
    match = re.search(r'(?i)\bVersion\s*[:=]?\s*([A-Za-z0-9][A-Za-z0-9_.-]{0,127})', version)
    software_version = match.group(1) if match else ''
    if any(len(value) > 256 or any(ord(c) < 32 or ord(c) == 127 for c in value)
           for value in (role, model)):
        raise ParseError('장비 식별 정보 형식을 확인하세요.')
    sources = []
    if any((hostname, address, role, switch_model)):
        sources.append('show switchinfo')
    if version_model or software_version:
        sources.append('show version')
    return DeviceIdentity(hostname, address, role, model, software_version,
                          utc_now() if sources else '', ', '.join(sources))
