"""Offline orchestration tests; all controller responses are synthetic."""
import threading

import pytest
from test_commands_parsers import MAC, global_output, table

from aruba_client_live_tracker.collector import LiveCollector, map_md
from aruba_client_live_tracker.commands import global_user_command, parse_target
from aruba_client_live_tracker.models import Credentials, Device, Outcome
from aruba_client_live_tracker.ssh import SSHError

MM = Device("LAB-MM", "192.0.2.10", "MM_PRIMARY")
STANDBY = Device("LAB-STANDBY", "192.0.2.11", "MM_STANDBY")
MD = Device("LAB-MD", "198.51.100.20", mappings=("192.0.2.20",))


@pytest.mark.parametrize('as_alias', [False, True])
def test_map_md_equivalent_ipv6_spellings(as_alias):
    address = '2001:db8::20'
    md = Device('LAB-IPV6', '192.0.2.20' if as_alias else address, 'MD',
                mappings=(address,) if as_alias else ())
    assert map_md('2001:0DB8:0:0:0:0:0:20', [MM, md]) == md


def test_map_md_equivalent_ipv6_aliases_remain_ambiguous():
    one = Device('LAB-ONE', '192.0.2.20', 'MD', mappings=('2001:db8::20',))
    two = Device('LAB-TWO', '192.0.2.21', 'MD', mappings=('2001:0db8:0:0:0:0:0:20',))
    with pytest.raises(ValueError, match='중복'):
        map_md('2001:db8::20', [one, two])


def test_map_md_hostname_aliases_keep_exact_matching():
    md = Device('LAB-ONE', '192.0.2.20', 'MD', mappings=('LAB-WLC',))
    assert map_md('LAB-WLC', [md]) == md
    with pytest.raises(ValueError, match='매핑이 없습니다'):
        map_md('lab-wlc', [md])


def test_map_md_exact_and_ambiguous():
    assert map_md("192.0.2.20", [MM, MD]) == MD
    with pytest.raises(ValueError):
        map_md("192.0.2.21", [MM, MD])
    with pytest.raises(ValueError):
        map_md("192.0.2.20", [MD, Device("OTHER", "203.0.113.20", mappings=("192.0.2.20",))])


class FakeSSH:
    instances = []
    failures = {}
    mm_output = global_output()

    def __init__(self, device, *_):
        self.device = device
        self.commands = []
        self.closed = False
        self.instances.append(self)

    def run(self, command, **kwargs):
        self.commands.append(command)
        if self.device.name in self.failures:
            raise self.failures[self.device.name]
        if "global-user-table" in command:
            return self.mm_output
        if "show user-table" in command:
            return f"IP: 192.0.2.100, MAC: {MAC}, Role: lab-role\nEssid: LAB-WIFI, Bssid: 02:00:00:00:10:01 AP name/group: LAB-AP-A/lab"
        if "show ap association" in command:
            return table(["Name", "bssid", "mac", "auth", "assoc", "Flags"], [["LAB-AP-A", "02:00:00:00:10:01", MAC, "y", "y", "WA"]], "Num Clients:{count}")
        if "client-stats" in command:
            return "Last SNR 30\nFrames Transmitted 100\nFrames Received 80"
        return "% Invalid input"

    def close(self):
        self.closed = True


@pytest.fixture
def collector(monkeypatch, tmp_path):
    FakeSSH.instances = []
    FakeSSH.failures = {}
    FakeSSH.mm_output = global_output()
    monkeypatch.setattr("aruba_client_live_tracker.collector.SSHSession", FakeSSH)
    col = LiveCollector([MM, STANDBY, MD], Credentials("lab", "synthetic"), tmp_path / "known_hosts", lambda *a: True)
    yield col
    col.close()


def test_mm_md_flow_reuses_sessions_and_optional_rejection(collector):
    for _ in range(3):
        result = collector.poll(parse_target("192.0.2.100"))
        assert result.outcome == Outcome.OK
        assert result.observation.md == "LAB-MD"
        assert result.observation.snr == 30
        assert result.observation.field_status["client_table"] == "지원하지 않음"
    assert len(FakeSSH.instances) == 2
    collector.close()
    assert all(s.closed for s in FakeSSH.instances)


def test_primary_network_error_fails_over(collector):
    FakeSSH.failures[MM.name] = SSHError("network", "연결 실패", retryable=True)
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.OK
    assert STANDBY.name in result.mm_status
    assert len([s for s in FakeSSH.instances if not s.closed]) == 2


def test_primary_host_key_error_never_fails_over(collector):
    FakeSSH.failures[MM.name] = SSHError("host_key", "서버 키 변경", retryable=False)
    assert collector.poll(parse_target(MAC)).outcome == Outcome.ERROR
    assert len(FakeSSH.instances) == 1


def test_mapping_missing_does_not_scan(collector):
    FakeSSH.mm_output = global_output().replace("192.0.2.20", "192.0.2.99")
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert "매핑" in result.error
    assert len(FakeSSH.instances) == 1


def test_ambiguous_ip_requires_selection(collector):
    FakeSSH.mm_output = global_output([["192.0.2.100", MAC, "", "192.0.2.20", "r", "", "A"], ["192.0.2.100", "02:00:00:00:00:02", "", "192.0.2.20", "r", "", "A"]])
    result = collector.poll(parse_target("192.0.2.100"))
    assert result.outcome == Outcome.AMBIGUOUS
    assert len(FakeSSH.instances) == 1
    selected = collector.poll(parse_target("192.0.2.100"), selected_mac=MAC)
    assert selected.outcome == Outcome.OK
    assert FakeSSH.instances[0].commands[-1] == global_user_command(parse_target(MAC))


def test_mm_absent_authoritative_no_md(collector):
    FakeSSH.mm_output = global_output([])
    assert collector.poll(parse_target(MAC)).outcome == Outcome.ABSENT
    assert len(FakeSSH.instances) == 1


def test_md_changed_closes_previous_connection(collector):
    collector.devices.append(Device("LAB-MD-2", "198.51.100.21", mappings=("192.0.2.21",)))
    assert collector.poll(parse_target(MAC)).outcome == Outcome.OK
    old_md = FakeSSH.instances[1]
    FakeSSH.mm_output = global_output().replace("192.0.2.20", "192.0.2.21")
    assert collector.poll(parse_target(MAC)).observation.md == "LAB-MD-2"
    assert old_md.closed
    assert len([s for s in FakeSSH.instances if not s.closed]) == 2


def test_cancelled_poll_opens_no_connections(collector):
    event = threading.Event()
    event.set()
    assert collector.poll(parse_target(MAC), cancel=event).outcome == Outcome.ERROR
    assert not FakeSSH.instances


def test_ip_search_pins_mac_after_resolution(collector):
    assert collector.poll(parse_target("192.0.2.100")).outcome == Outcome.OK
    FakeSSH.mm_output = global_output().replace("192.0.2.100", "192.0.2.101")
    result = collector.poll(parse_target("192.0.2.100"))
    assert result.outcome == Outcome.OK
    assert FakeSSH.instances[0].commands[-1] == global_user_command(parse_target(MAC))


def test_ambiguous_same_mac_multiple_md_does_not_guess(collector):
    FakeSSH.mm_output = global_output([["192.0.2.100", MAC, "", "192.0.2.20", "r", "", "A"], ["192.0.2.100", MAC, "", "192.0.2.21", "r", "", "B"]])
    assert collector.poll(parse_target(MAC), selected_mac=MAC).outcome == Outcome.AMBIGUOUS
    assert len(FakeSSH.instances) == 1


def test_mm_parser_error_never_fails_over_or_disconnects(collector):
    FakeSSH.mm_output = "CLI format changed; no recognizable fields"
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert len(FakeSSH.instances) == 1


def test_target_switch_restarts_ip_resolution(collector):
    assert collector.poll(parse_target(MAC)).outcome == Outcome.OK
    assert collector.poll(parse_target("192.0.2.100")).outcome == Outcome.OK
    assert FakeSSH.instances[0].commands[-1] == global_user_command(parse_target("192.0.2.100"))


def test_history_collection_is_throttled(collector):
    for _ in range(10):
        assert collector.poll(parse_target(MAC)).outcome == Outcome.OK
    md = [s for s in FakeSSH.instances if s.device.kind == "MD"][0]
    assert len([command for command in md.commands if "auth-tracebuf" in command]) == 1


def test_history_raw_retained_with_collection_time_between_polls(collector):
    first = collector.poll(parse_target(MAC))
    second = collector.poll(parse_target(MAC))
    history = {key: value for key, value in first.raw.items() if "auth-tracebuf" in key}
    assert history
    assert all("이력 조회=" in key for key in history)
    assert all(second.raw.get(key) == value for key, value in history.items())


def test_shared_runner_collectors_reuse_and_close_only_their_owner(monkeypatch, tmp_path):
    from aruba_client_live_tracker.session_pool import SharedSessionPool

    FakeSSH.instances = []
    FakeSSH.failures = {}
    FakeSSH.mm_output = global_output()
    monkeypatch.setattr('aruba_client_live_tracker.session_pool.SSHSession', FakeSSH)
    credentials = Credentials('lab', 'synthetic')
    pool = SharedSessionPool(credentials, tmp_path / 'known_hosts', None)
    collectors = [LiveCollector([MM, MD], credentials, tmp_path / 'known_hosts',
                                command_runner=pool.for_owner(str(index))) for index in range(2)]
    try:
        for collector in collectors:
            assert collector.poll(parse_target(MAC)).outcome == Outcome.OK
        assert len(FakeSSH.instances) == 2
        collectors[0].close()
        assert not any(session.closed for session in FakeSSH.instances)
        assert collectors[1].poll(parse_target(MAC)).outcome == Outcome.OK
        collectors[1].close()
        assert all(session.closed for session in FakeSSH.instances)
    finally:
        pool.close()


def test_shared_md_change_releases_only_changed_owner_and_refreshes_history(monkeypatch, tmp_path):
    from aruba_client_live_tracker.session_pool import SharedSessionPool

    FakeSSH.instances = []
    FakeSSH.failures = {}
    FakeSSH.mm_output = global_output()
    monkeypatch.setattr('aruba_client_live_tracker.session_pool.SSHSession', FakeSSH)
    credentials = Credentials('lab', 'synthetic')
    pool = SharedSessionPool(credentials, tmp_path / 'known_hosts', None)
    devices = [MM, MD, Device('MD-2', '198.51.100.21', mappings=('192.0.2.21',))]
    collectors = [LiveCollector(devices, credentials, tmp_path / 'known_hosts',
                                command_runner=pool.for_owner(str(index))) for index in range(2)]
    try:
        for collector in collectors:
            assert collector.poll(parse_target(MAC)).outcome == Outcome.OK
        old = FakeSSH.instances[1]
        FakeSSH.mm_output = global_output().replace('192.0.2.20', '192.0.2.21')
        assert collectors[0].poll(parse_target(MAC)).outcome == Outcome.OK
        assert not old.closed
        new = FakeSSH.instances[2]
        assert any('auth-tracebuf' in command for command in new.commands)
        collectors[1].close()
        assert old.closed
    finally:
        for collector in collectors:
            collector.close()
        pool.close()


@pytest.mark.parametrize("code,stage", [
    ("NETWORK", "connect"), ("AUTH_FAILED", "auth"), ("HOST_KEY_CHANGED", "host_key"),
    ("HOST_KEY_TIMEOUT", "host_key"), ("KNOWN_HOSTS_LOCK", "host_key"),
    ("KNOWN_HOSTS_WRITE", "host_key"), ("KNOWN_HOSTS_INVALID", "host_key"),
])
def test_mm_diagnostic_stages_sanitize_exception_and_block_trust_failover(collector, code, stage):
    FakeSSH.failures[MM.name] = SSHError(code, "password=synthetic\nserver private banner", retryable=True)
    result = collector.poll(parse_target(MAC))
    diagnostic = result.diagnostics[0]
    assert (diagnostic.stage, diagnostic.code) == (stage, code)
    assert diagnostic.device_name == MM.name
    assert diagnostic.endpoint == f"{MM.host}:{MM.port}"
    assert diagnostic.command == global_user_command(parse_target(MAC))
    assert "synthetic" not in repr(diagnostic)
    assert "private banner" not in result.error
    if stage in ("host_key", "auth"):
        assert result.outcome == Outcome.ERROR
        assert len(FakeSSH.instances) == 1
    else:
        assert result.outcome == Outcome.OK
        assert STANDBY.name in result.mm_status


@pytest.mark.parametrize("output,stage,code", [
    ("Permission denied: invented policy", "md_command", "COMMAND_REJECTED"),
    ("Changed synthetic output without required fields", "parse", "PARSE_FAILED"),
    (table(["IP Address", "MAC Address", "Role"], [["bad-ip", MAC, "r"]]), "parse", "PARSE_FAILED"),
])
def test_md_command_vs_parser_diagnostics_keep_mm_evidence(collector, monkeypatch, output, stage, code):
    original_run = FakeSSH.run

    def run(session, command, **kwargs):
        if "show user-table" in command:
            return output
        return original_run(session, command, **kwargs)

    monkeypatch.setattr(FakeSSH, "run", run)
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert "연결 정상" in result.mm_status
    assert result.md_status == f"{MD.name} 조회 실패"
    diagnostic = result.diagnostics[-1]
    assert (diagnostic.stage, diagnostic.code, diagnostic.device_name) == (stage, code, MD.name)
    assert diagnostic.command == f"show user-table mac {MAC}"
    assert any("global-user-table" in command for command in result.raw)
    assert output in result.raw.values()


def test_optional_failures_have_commands_and_retain_successful_observation(collector):
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.OK
    assert result.observation.snr == 30
    optional = result.diagnostics
    assert len(optional) == 4  # AP client table and three optional history commands.
    assert all(d.stage == "wireless" and d.code == "COMMAND_REJECTED" for d in optional)
    assert all(d.device_name == MD.name and d.command for d in optional)
    assert all(any(d.command in key for key in result.raw) for d in optional)


def test_optional_parser_failure_is_distinct_from_command_denial(collector, monkeypatch):
    original_run = FakeSSH.run

    def run(session, command, **kwargs):
        if "client-stats" in command:
            return "invented unrecognized stats"
        return original_run(session, command, **kwargs)

    monkeypatch.setattr(FakeSSH, "run", run)
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.OK
    diagnostic = next(d for d in result.diagnostics if "client-stats" in d.command)
    assert diagnostic.stage == "parse"
    assert result.observation.field_status["client_stats"] == "조회 실패"


def test_late_parser_validation_preserves_accumulated_status_and_raw(collector, monkeypatch):
    def fail(*args):
        raise ValueError("synthetic password should never escape")

    monkeypatch.setattr("aruba_client_live_tracker.collector.parse_user", fail)
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert "연결 정상" in result.mm_status
    assert result.md_status == f"{MD.name} 조회 실패"
    assert len(result.raw) == 2
    assert result.diagnostics[-1].code == "VALIDATION_FAILED"
    assert "password" not in result.error


def test_cancellation_after_read_keeps_local_raw_and_stage(collector, monkeypatch):
    event = threading.Event()
    original_run = FakeSSH.run

    def run(session, command, **kwargs):
        output = original_run(session, command, **kwargs)
        if "show user-table" in command:
            event.set()
        return output

    monkeypatch.setattr(FakeSSH, "run", run)
    result = collector.poll(parse_target(MAC), cancel=event)
    assert result.outcome == Outcome.ERROR
    assert result.md_status == "중지"
    assert len(result.raw) == 2
    assert any(d.code == "CANCELLED" for d in result.diagnostics)
    assert "연결 정상" in result.mm_status


def test_auto_devices_are_excluded_from_controller_and_mapping(collector):
    auto = Device("UNRESOLVED", "192.0.2.20", "AUTO", mappings=("192.0.2.20",))
    collector.devices = [auto, MD]
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert result.diagnostics[-1].code == "MM_NOT_CONFIGURED"
    assert not FakeSSH.instances
    collector.devices = [MM, auto]
    result = collector.poll(parse_target(MAC))
    assert result.diagnostics[-1].stage == "md_mapping"
    assert result.diagnostics[-1].code == "MD_MAPPING_FAILED"
    assert len(FakeSSH.instances) == 1
    assert all(s.device.kind != "AUTO" for s in FakeSSH.instances)


def test_diagnostic_metadata_is_bounded_and_redacted(collector):
    from aruba_client_live_tracker.collector import MAX_POLL_DIAGNOSTICS, _PollContext

    context = _PollContext(collector.credentials)
    context.device = Device("synthetic\n" + "N" * 200, "192.0.2.10")
    context.command = "synthetic\x1b" + "C" * 600
    for _ in range(100):
        context.diagnose("FAILED", "synthetic\n" + "M" * 700)
    assert len(context.result.diagnostics) == MAX_POLL_DIAGNOSTICS
    diagnostic = context.result.diagnostics[0]
    assert len(diagnostic.message) <= 512
    assert len(diagnostic.command) <= 512
    assert len(diagnostic.device_name) <= 128
    assert "synthetic" not in repr(diagnostic)
    assert "\n" not in diagnostic.message
    assert "\x1b" not in diagnostic.command


@pytest.mark.parametrize("code,stage", [("AUTH_FAILED", "auth"), ("HOST_KEY_CHANGED", "host_key"),
                                        ("NETWORK", "connect")])
def test_md_ssh_failure_diagnostics_preserve_mm_success(collector, code, stage):
    FakeSSH.failures[MD.name] = SSHError(code, "untrusted synthetic exception")
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert result.mm_status == f"{MM.name} 연결 정상"
    assert result.diagnostics[-1].stage == stage
    assert result.diagnostics[-1].device_name == MD.name
    assert result.diagnostics[-1].command == f"show user-table mac {MAC}"
    assert len(result.raw) == 1


def test_mm_command_rejection_is_not_parser_failure_or_failover(collector):
    FakeSSH.mm_output = "Access denied: synthetic policy"
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    diagnostic = result.diagnostics[-1]
    assert (diagnostic.stage, diagnostic.code) == ("mm_lookup", "COMMAND_REJECTED")
    assert FakeSSH.mm_output in result.raw.values()
    assert len(FakeSSH.instances) == 1


def test_output_budget_failure_keeps_prior_raw(collector, monkeypatch):
    from aruba_client_live_tracker.collector import MAX_POLL_RAW_BYTES

    original_run = FakeSSH.run

    def run(session, command, **kwargs):
        if "show user-table" in command:
            return "X" * (MAX_POLL_RAW_BYTES + 1)
        return original_run(session, command, **kwargs)

    monkeypatch.setattr(FakeSSH, "run", run)
    result = collector.poll(parse_target(MAC))
    assert result.outcome == Outcome.ERROR
    assert result.diagnostics[-1].code == "OUTPUT_LIMIT"
    assert result.diagnostics[-1].stage == "md_command"
    assert result.mm_status == f"{MM.name} 연결 정상"
    assert list(result.raw.values()) == [global_output()]
