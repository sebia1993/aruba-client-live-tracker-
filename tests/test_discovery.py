"""Synthetic documentation-address fixtures; these tests never use live SSH."""
import threading

import pytest

from aruba_client_live_tracker.commands import validate_command
from aruba_client_live_tracker.discovery import DiscoveryService, merge_discovered
from aruba_client_live_tracker.discovery_parsers import parse_identity, parse_switches, role_kind
from aruba_client_live_tracker.models import Credentials, Device, DeviceIdentity
from aruba_client_live_tracker.parsers import ParseError
from aruba_client_live_tracker.ssh import SSHError


def switches(rows=None):
    rows = rows if rows is not None else [
        ['192.0.2.10', 'LAB-MM', 'conductor', 'ArubaMM-VA', '8.10.0.0', 'up'],
        ['192.0.2.11', 'LAB-STANDBY', 'standby', 'ArubaMM-VA', '8.10.0.0', 'up'],
        ['192.0.2.20', 'LAB-MD', 'MD', 'Aruba7240XM', '8.10.0.0', 'up'],
    ]
    headers = ['IP Address', 'Name', 'Type', 'Model', 'Version', 'Status']
    widths = [max(len(h), *(len(row[i]) for row in rows), 3) + 3 for i, h in enumerate(headers)]
    def line(values):
        return ''.join(v.ljust(w) for v, w in zip(values, widths)).rstrip()
    return '\n'.join([line(headers), line(['-' * (w - 3) for w in widths]),
                      *(line(row) for row in rows), f'Total Switches: {len(rows)}'])


def test_only_fixed_discovery_commands_allowed():
    for command in ('show switches', 'show version', 'show switchinfo'):
        assert validate_command(command) == command
    for command in ('show switches all', 'show switchinfo\nreload', ' show version', 'show version;reload'):
        with pytest.raises(ValueError):
            validate_command(command)


def test_parse_switches_all_roles_and_complete_rows():
    rows = parse_switches(switches())
    assert [(r.hostname, role_kind(r.reported_role)) for r in rows] == [
        ('LAB-MM', 'MM_PRIMARY'), ('LAB-STANDBY', 'MM_STANDBY'), ('LAB-MD', 'MD')]
    assert rows[2].switch_ip == '192.0.2.20'
    assert rows[2].model == 'Aruba7240XM'


@pytest.mark.parametrize('text', ['', '% Invalid input detected', 'Total Switches: 0',
    switches().replace('Total Switches: 3', 'Total Switches: 4'),
    switches().replace('192.0.2.20', '999.0.2.20')])
def test_parse_switches_rejects_unknown_incomplete_or_bad_ip(text):
    with pytest.raises(ParseError):
        parse_switches(text)


@pytest.mark.parametrize('role', ['master', 'local', '', 'ArubaMM-VA', 'controller', 'primary'])
def test_unknown_roles_never_inferred(role):
    assert role_kind(role) == 'AUTO'


def test_switchinfo_version_identity_parsing():
    identity = parse_identity('Hostname: LAB-MD\nInternet address: 192.0.2.20\nswitchrole:MD',
                              'ArubaOS (MODEL: Aruba7240XM), Version 8.10.0.0')
    assert identity.hostname == 'LAB-MD'
    assert identity.switch_ip == '192.0.2.20'
    assert identity.model == 'Aruba7240XM'
    assert identity.version == '8.10.0.0'
    assert role_kind(identity.reported_role) == 'MD'


class FakeSession:
    outputs = {}
    calls = []
    instances = []

    def __init__(self, device, credentials, known_hosts, approve_host_key=None):
        self.device = device
        self.closed = False
        self.instances.append(self)

    def run(self, command, cancel=None, deadline=None):
        self.calls.append((self.device.host, command))
        output = self.outputs.get((self.device.host, command), '')
        if isinstance(output, Exception):
            raise output
        return output

    def close(self):
        self.closed = True


@pytest.fixture
def service(monkeypatch, tmp_path):
    FakeSession.outputs = {}
    FakeSession.calls = []
    FakeSession.instances = []
    monkeypatch.setattr('aruba_client_live_tracker.discovery.SSHSession', FakeSession)
    result = DiscoveryService(Credentials('synthetic-user', 'synthetic-password'), tmp_path / 'known_hosts')
    yield result
    result.close()


def seed_outputs(host='192.0.2.10', self_ip='192.0.2.10', hostname='LAB-MM', role='master'):
    FakeSession.outputs = {
        (host, 'show switches'): switches(),
        (host, 'show switchinfo'): f'Hostname: {hostname}\nInternet address: {self_ip}\nswitchrole:{role}',
        (host, 'show version'): 'ArubaOS (MODEL: ArubaMM-VA), Version 8.10.0.0',
    }


def test_discover_only_contacts_seed_and_matches_unique_self(service):
    seed_outputs()
    seed = Device('INPUT', '192.0.2.10', 'AUTO')
    result = service.discover(seed)
    assert len(result.devices) == 3
    assert result.devices[0].name == 'INPUT'
    assert result.devices[0].kind == 'MM_PRIMARY'
    assert result.devices[0].identity.switch_ip == '192.0.2.10'
    assert {ip for ip, _ in FakeSession.calls} == {'192.0.2.10'}
    assert all(session.closed for session in FakeSession.instances)
    assert result.devices[2].mappings == ('192.0.2.20', 'LAB-MD')


def test_vip_seed_is_retained_without_arbitrary_primary(service):
    seed_outputs('192.0.2.100', '', 'UNKNOWN')
    result = service.discover(Device('VIP', '192.0.2.100', 'AUTO'))
    assert len(result.devices) == 4
    assert result.devices[0].host == '192.0.2.100'
    assert result.devices[0].kind == 'AUTO'
    assert any(d.code == 'IDENTITY_UNRESOLVED' for d in result.diagnostics)


def test_standby_seed_uses_its_matching_row(service):
    seed_outputs('192.0.2.11', '192.0.2.11', 'LAB-STANDBY')
    result = service.discover(Device('standby input', '192.0.2.11', 'AUTO'))
    assert result.devices[0].kind == 'MM_STANDBY'
    assert len(result.devices) == 3


def test_discovery_failure_retains_seed_and_sanitizes_exception(service):
    FakeSession.outputs = {('192.0.2.10', 'show switches'): SSHError('AUTH_FAILED', 'synthetic-password')}
    result = service.discover(Device('seed', '192.0.2.10', 'AUTO'))
    assert len(result.devices) == 1
    assert result.diagnostics[0].stage == 'auth'
    assert 'synthetic-password' not in str(result)


def test_switch_table_failure_explains_static_reason_without_raw_rows(service):
    seed_outputs()
    malformed = switches().replace('Total Switches: 3', 'Total Switches: 4')
    with pytest.raises(ParseError) as reason:
        parse_switches(malformed)
    FakeSession.outputs[('192.0.2.10', 'show switches')] = malformed
    result = service.discover(Device('seed', '192.0.2.10', 'AUTO'))
    diagnostic = next(d for d in result.diagnostics if d.code == 'SWITCH_TABLE_PARSE_FAILED')
    assert str(reason.value) in diagnostic.message
    assert diagnostic.command == 'show switches'
    assert 'LAB-MD' not in diagnostic.message and '192.0.2.20' not in diagnostic.message


def test_probe_selected_only_and_unknown_model_stays_auto(service):
    FakeSession.outputs = {
        ('192.0.2.20', 'show switchinfo'): 'Hostname: LAB-MD\nInternet address: 192.0.2.20\nswitchrole:local',
        ('192.0.2.20', 'show version'): 'ArubaOS (MODEL: Aruba7240XM), Version 8.10.0.0',
    }
    result = service.probe([Device('candidate', '192.0.2.20', 'AUTO', origin='discovered')])
    assert result.devices[0].kind == 'AUTO'
    assert {host for host, _ in FakeSession.calls} == {'192.0.2.20'}
    assert not any(command == 'show switches' for _, command in FakeSession.calls)


def test_cancelled_discovery_never_connects(service):
    cancel = threading.Event()
    cancel.set()
    result = service.discover(Device('seed', '192.0.2.10', 'AUTO'), cancel)
    assert not FakeSession.calls
    assert any(d.code == 'CANCELLED' for d in result.diagnostics)


def test_merge_endpoint_preserves_manual_configuration_and_reports_conflicts():
    old = Device('manual', '192.0.2.20', 'MD', mappings=('EXPLICIT',))
    discovered = Device('renamed', '192.0.2.20', 'MM_PRIMARY', mappings=('LAB-MM',),
                        identity=DeviceIdentity(hostname='LAB-MM', switch_ip='192.0.2.20'), origin='discovered')
    merged, diagnostics = merge_discovered([old], [discovered])
    assert len(merged) == 1
    assert (merged[0].name, merged[0].kind, merged[0].mappings, merged[0].origin) == (
        old.name, old.kind, old.mappings, 'manual')
    assert diagnostics


def test_merge_names_do_not_merge_different_endpoints():
    merged, diagnostics = merge_discovered([Device('LAB', '192.0.2.10')],
        [Device('LAB', '192.0.2.20', 'MD', origin='discovered')])
    assert len(merged) == 2
    assert len({d.name for d in merged}) == 2
    assert diagnostics


def test_probe_unique_endpoint_uses_single_session(service):
    seed_outputs()
    result = service.probe([Device('one', '192.0.2.10', 'AUTO'), Device('two', '192.0.2.10', 'AUTO')])
    assert len(FakeSession.instances) == 1
    assert len(result.devices) == 1


def test_manual_auto_resolves_with_proven_aliases_preserving_manual_mapping():
    old = Device('manual name', '192.0.2.20', 'AUTO', port=2222, mappings=('EXPLICIT',))
    identity = DeviceIdentity(hostname='LAB-MD', switch_ip='192.0.2.20', reported_role='MD')
    found = Device('LAB-MD', old.host, 'MD', port=2222, identity=identity,
                   mappings=('192.0.2.20', 'LAB-MD'), origin='discovered')
    merged, diagnostics = merge_discovered([old], [found])
    assert merged[0].kind == 'MD'
    assert (merged[0].name, merged[0].host, merged[0].port, merged[0].origin) == (
        old.name, old.host, old.port, old.origin)
    assert merged[0].mappings == ('EXPLICIT', '192.0.2.20', 'LAB-MD')
    assert not diagnostics


def test_probe_fresh_self_ip_drops_stale_role(service):
    old_identity = DeviceIdentity(hostname='OLD-MD', switch_ip='192.0.2.20', reported_role='MD')
    candidate = Device('edited', '192.0.2.30', 'MD', identity=old_identity,
                       mappings=('192.0.2.20', 'OLD-MD'), origin='discovered')
    FakeSession.outputs = {
        ('192.0.2.30', 'show switchinfo'): 'Hostname: NEW-UNKNOWN\nInternet address: 192.0.2.30\nswitchrole:master',
        ('192.0.2.30', 'show version'): 'ArubaOS (MODEL: ArubaMM-VA), Version 8.10.0.0',
    }
    result = service.probe([candidate])
    assert result.devices[0].kind == 'AUTO'
    assert result.devices[0].identity.switch_ip == '192.0.2.30'
    assert result.devices[0].identity.reported_role == 'master'
    assert result.devices[0].mappings == ()
    assert any(d.code == 'IDENTITY_CONFLICT' for d in result.diagnostics)


def test_probe_preserves_known_table_role_when_self_role_is_legacy(service):
    identity = DeviceIdentity(hostname='LAB-MD', switch_ip='192.0.2.20', reported_role='MD')
    candidate = Device('LAB-MD', '192.0.2.20', 'MD', identity=identity, origin='discovered')
    FakeSession.outputs = {
        ('192.0.2.20', 'show switchinfo'): 'Hostname: LAB-MD\nInternet address: 192.0.2.20\nswitchrole:local',
        ('192.0.2.20', 'show version'): 'ArubaOS (MODEL: Aruba7240XM), Version 8.10.0.0',
    }
    assert service.probe([candidate]).devices[0].kind == 'MD'


def test_probe_never_uses_more_than_two_sessions(service, monkeypatch):
    import time
    active = maximum = 0
    lock = threading.Lock()
    original = FakeSession.run
    def counted(self, command, cancel=None, deadline=None):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(active, maximum)
        time.sleep(0.01)
        try:
            return original(self, command, cancel, deadline)
        finally:
            with lock:
                active -= 1
    monkeypatch.setattr(FakeSession, 'run', counted)
    devices = [Device(f'LAB-{i}', f'192.0.2.{i}', 'AUTO') for i in range(1, 7)]
    result = service.probe(devices)
    assert len(result.devices) == 6
    assert maximum == 2
    assert all(session.closed for session in FakeSession.instances)


def test_switchinfo_official_is_syntax_and_address_netmask():
    identity = parse_identity('Hostname is LAB-MM\nInternet address is 192.0.2.10 255.255.255.0\nswitchrole:master',
                              'ArubaOS (MODEL: ArubaMM-VA), Version 8.10.0.0')
    assert identity.hostname == 'LAB-MM'
    assert identity.switch_ip == '192.0.2.10'
    assert role_kind(identity.reported_role) == 'AUTO'


@pytest.mark.parametrize('address', [
    '192.0.2.10 arbitrary', '192.0.2.10 255.255.255.0 extra', '192.0.2.10 255.0.255.0',
])
def test_switchinfo_rejects_arbitrary_or_invalid_address_suffix(address):
    with pytest.raises(ParseError):
        parse_identity(f'Hostname is LAB-MM\nInternet address is {address}')


def test_merge_rejects_automatic_alias_conflicting_with_manual_endpoint():
    existing = Device('manual', '192.0.2.20', 'MD', mappings=('LAB-SHARED',))
    found = Device('new', '192.0.2.30', 'MD',
                   identity=DeviceIdentity(hostname='LAB-SHARED', switch_ip='192.0.2.20', reported_role='MD'),
                   mappings=('192.0.2.20', 'LAB-SHARED'), origin='discovered')
    devices, diagnostics = merge_discovered([existing], [found])
    assert devices[0] == existing
    assert devices[1].mappings == ()
    assert any(d.code == 'MAPPING_CONFLICT' for d in diagnostics)


def test_discovered_hostname_collision_has_no_arbitrary_mapping_winner():
    found = [Device(f'device-{i}', f'192.0.2.{i}', 'MD',
                    identity=DeviceIdentity(hostname='LAB-SHARED', switch_ip=f'192.0.2.{i}', reported_role='MD'),
                    mappings=(f'192.0.2.{i}', 'LAB-SHARED'), origin='discovered') for i in (20, 30)]
    devices, diagnostics = merge_discovered([], found)
    assert [device.mappings for device in devices] == [('192.0.2.20',), ('192.0.2.30',)]
    assert any(d.code == 'MAPPING_CONFLICT' for d in diagnostics)


def test_seed_endpoint_conflicting_with_self_ip_never_infers_primary(service):
    seed_outputs('192.0.2.10', '192.0.2.11', 'LAB-STANDBY', 'master')
    result = service.discover(Device('seed', '192.0.2.10', 'AUTO'))
    assert result.devices[0].kind == 'AUTO'
    assert result.devices[0].identity.switch_ip == '192.0.2.11'
    assert any(d.code == 'IDENTITY_CONFLICT' for d in result.diagnostics)


def test_merge_fresh_self_identity_replaces_conflicting_discovered_metadata():
    stale = Device('LAB', '192.0.2.30', 'MD', mappings=('192.0.2.20', 'OLD-MD'),
                   identity=DeviceIdentity(hostname='OLD-MD', switch_ip='192.0.2.20', reported_role='MD',
                                           source='show switches'), origin='discovered')
    fresh = Device('LAB', stale.host, 'AUTO', identity=DeviceIdentity(
        hostname='NEW-UNKNOWN', switch_ip='192.0.2.30', reported_role='master', source='show switchinfo'),
        origin='discovered')
    devices, diagnostics = merge_discovered([stale], [fresh])
    assert devices[0].kind == 'AUTO'
    assert devices[0].identity == fresh.identity
    assert devices[0].mappings == ()
    assert diagnostics
