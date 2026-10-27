"""Invented RFC 5737 rows using documented ArubaOS horizontal table layouts.

The layouts, not operational data, follow HPE's show switches CLI reference:
https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm
The AOS 8.10 CLI PDF physical page 3385 also shows the configuration continuation.
The AOS 8.10 User Guide page 861 documents an absent IPv4 cell (None) with
an IPv6 address. These tests use invented RFC 3849 addresses and complete counts;
the published example itself omits rows and is not a complete CLI capture.
"""
import pytest

from aruba_client_live_tracker.discovery_parsers import parse_switches, role_kind
from aruba_client_live_tracker.parsers import ParseError

IDENTITY_HEADERS = ['IP Address', 'IPv6 Address', 'Name', 'Location', 'Type', 'Model', 'Version']
IDENTITY_ROWS = [
    ['192.0.2.10', 'None', 'LAB-MM', 'Synthetic.floor1', 'conductor', 'ArubaMM-HW-10K', '8.10.0.0'],
    ['192.0.2.11', 'None', 'LAB-STANDBY', 'Synthetic.floor1', 'standby', 'ArubaMM-HW-10K', '8.10.0.0'],
    ['192.0.2.20', 'None', 'LAB-WLC', 'Synthetic.floor2', 'MD', 'Aruba7240XM', '8.10.0.0'],
]
STATUS_HEADERS = ['Status', 'Configuration State', 'Config Sync Time (sec)', 'Config ID']
STATUS_ROWS = [['up', 'UPDATE SUCCESSFUL', '0', str(i)] for i in range(1, 4)]
DEBUG_HEADERS = ['Status', 'Uptime', 'CrashInfo', 'Config Sync Time (sec)', 'License', 'Release Type']
DEBUG_ROWS = [['up', '3d 1h 21m', 'no', '0', 'N/A', 'LSR'] for _ in range(3)]


def table(headers, rows):
    widths = [max([len(header), *(len(row[i]) for row in rows)]) + 3
              for i, header in enumerate(headers)]
    def line(values):
        return ''.join(value.ljust(width) for value, width in zip(values, widths)).rstrip()
    return '\n'.join([line(headers), line(['-' * (width - 3) for width in widths]),
                      *(line(row) for row in rows)])


def switches_output(*, identities=None, status=None, headers=None, total=3):
    identities = IDENTITY_ROWS if identities is None else identities
    status = STATUS_ROWS if status is None else status
    headers = STATUS_HEADERS if headers is None else headers
    return '\n'.join(['Synthetic fixture only', 'All Switches', '------------',
                      table(IDENTITY_HEADERS, identities), '', table(headers, status), '',
                      f'Total Switches:{total}', '(synthetic-mm) [mynode] #'])


@pytest.mark.parametrize('headers,status', [(STATUS_HEADERS, STATUS_ROWS), (DEBUG_HEADERS, DEBUG_ROWS)])
def test_complete_horizontal_switch_tables_resolve_the_same_devices(headers, status):
    rows = parse_switches(switches_output(headers=headers, status=status))
    assert [(row.hostname, row.switch_ip, role_kind(row.reported_role)) for row in rows] == [
        ('LAB-MM', '192.0.2.10', 'MM_PRIMARY'), ('LAB-STANDBY', '192.0.2.11', 'MM_STANDBY'),
        ('LAB-WLC', '192.0.2.20', 'MD')]
    assert [row.model for row in rows] == ['ArubaMM-HW-10K', 'ArubaMM-HW-10K', 'Aruba7240XM']
    assert all(row.version == '8.10.0.0' and row.source == 'show switches' for row in rows)


def test_flat_full_column_table_remains_supported():
    rows = [identity + status for identity, status in zip(IDENTITY_ROWS, STATUS_ROWS)]
    text = table(IDENTITY_HEADERS + STATUS_HEADERS, rows) + '\nTotal Switches:3'
    assert [row.switch_ip for row in parse_switches(text)] == ['192.0.2.10', '192.0.2.11', '192.0.2.20']


def test_complete_empty_horizontal_table_is_explicitly_empty():
    assert parse_switches(switches_output(identities=[], status=[], total=0)) == []


@pytest.mark.parametrize('text', [
    switches_output(identities=IDENTITY_ROWS[:-1]),
    switches_output(status=STATUS_ROWS[:-1]),
    switches_output(status=STATUS_ROWS + [STATUS_ROWS[-1]]),
    switches_output(headers=['Status', 'Unknown heading', 'Config Sync Time (sec)', 'Config ID']),
    switches_output(status=STATUS_ROWS[:-1] + [['up', 'UPDATE SUCCESSFUL', '0', '']]),
    switches_output(status=STATUS_ROWS[:-1] + [['192.0.2.99', 'LAB-INJECTED', '0', '9']]),
    switches_output().replace('Total Switches:3', table(STATUS_HEADERS, STATUS_ROWS) + '\nTotal Switches:3'),
    switches_output().replace('Total Switches:3', ''),
    switches_output() + '\nTotal Switches:3',
    switches_output().replace('Total Switches:3', 'Total Switches:4'),
    switches_output() + '\n192.0.2.99 unexpected trailing device',
    switches_output(identities=IDENTITY_ROWS[:-1] + [IDENTITY_ROWS[0]]),
    switches_output().replace('192.0.2.20', '999.0.2.20'),
])
def test_malformed_or_incomplete_horizontal_output_is_never_accepted(text):
    with pytest.raises(ParseError) as caught:
        parse_switches(text)
    assert '192.0.2.' not in str(caught.value)
    assert 'LAB-' not in str(caught.value)


def test_unknown_device_role_stays_auto_even_with_healthy_continuation():
    identities = [row[:] for row in IDENTITY_ROWS]
    identities[0][4] = 'master'
    assert role_kind(parse_switches(switches_output(identities=identities))[0].reported_role) == 'AUTO'


def test_continuation_sync_label_spacing_and_indented_crlf_are_supported():
    headers = ['Status', 'Configuration State', 'Config Sync Time(sec)', 'Config ID']
    output = switches_output(headers=headers)
    output = '\r\n'.join('    ' + line for line in output.splitlines())
    assert [row.hostname for row in parse_switches(output)] == ['LAB-MM', 'LAB-STANDBY', 'LAB-WLC']


@pytest.mark.parametrize('split', [False, True])
def test_documented_none_ipv4_uses_ipv6_without_losing_roles_or_rows(split):
    identities = [row[:] for row in IDENTITY_ROWS]
    identities[0][:2] = ['None', '2001:0db8:0:0::10']
    identities[1][:2] = ['None', '2001:db8::11']
    identities[2][:2] = ['192.0.2.20', '2001:db8::20']
    text = (switches_output(identities=identities) if split else
            table(IDENTITY_HEADERS, identities) + '\nTotal Switches:3')
    result = parse_switches(text)
    assert [(r.switch_ip, role_kind(r.reported_role)) for r in result] == [
        ('2001:db8::10', 'MM_PRIMARY'), ('2001:db8::11', 'MM_STANDBY'), ('192.0.2.20', 'MD')]


@pytest.mark.parametrize('ipv4,ipv6', [
    ('None', 'None'), ('None', ''), ('None', 'not-an-address'), ('None', '192.0.2.99'),
    ('invalid', '2001:db8::99'), ('', '2001:db8::99'), ('999.0.2.99', '2001:db8::99'),
])
def test_missing_or_invalid_addresses_never_skip_rows_or_override_bad_ipv4(ipv4, ipv6):
    identities = [row[:] for row in IDENTITY_ROWS]
    identities[1][:2] = [ipv4, ipv6]
    with pytest.raises(ParseError) as caught:
        parse_switches(switches_output(identities=identities))
    message = str(caught.value)
    assert '출력 7행' in message
    assert f'IP 열 길이 {len(ipv4)}' in message
    assert f'IPv6 열 길이 {len(ipv6)}' in message
    for private_value in ('LAB-', '192.0.2.', '2001:db8:', 'not-an-address', 'invalid', '999.0.2.'):
        assert private_value not in message


def test_documented_none_ipv4_requires_ipv6_column():
    text = table(['IP Address', 'Name', 'Type'], [['None', 'LAB-MM', 'conductor']])
    with pytest.raises(ParseError, match='사용 가능한 IP 주소'):
        parse_switches(text + '\nTotal Switches:1')


def test_equivalent_ipv6_addresses_are_duplicates():
    identities = [row[:] for row in IDENTITY_ROWS]
    identities[0][:2] = ['None', '2001:0db8:0:0::10']
    identities[1][:2] = ['None', '2001:db8::10']
    with pytest.raises(ParseError, match='중복 IP'):
        parse_switches(switches_output(identities=identities))


def test_ipv6_row_does_not_bypass_incomplete_table_checks():
    identities = [row[:] for row in IDENTITY_ROWS]
    identities[0][:2] = ['None', '2001:db8::10']
    with pytest.raises(ParseError, match='실제 행 수'):
        parse_switches(switches_output(identities=identities, total=7))
