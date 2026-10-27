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
