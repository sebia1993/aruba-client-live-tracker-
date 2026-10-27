import csv
import gc
import tracemalloc
from concurrent.futures import ThreadPoolExecutor

import pytest

from aruba_client_live_tracker.demo import SCENARIOS, DemoCollector
from aruba_client_live_tracker.models import Event, Observation, Outcome, PollResult, Target
from aruba_client_live_tracker.storage import HistoryStore

IP = Target("ip", "192.0.2.100")
MAC = Target("mac", "02:00:00:00:00:01")


def test_storage_roundtrip_failure_and_session(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value, simulated=True)
        observation = Observation(ip=IP.value, mac=MAC.value, source="가상 데이터", simulated=True)
        event = Event("connect", "최초 연결", facts={"AP": "DEMO-AP-01"})
        store.save_poll(session, PollResult(Outcome.OK, observation), [event])
        store.save_poll(session, PollResult(Outcome.ERROR, error="MM 조회 실패"), [])
        rows = store.observations(session)
        assert len(rows) == 2
        assert rows[0]["mac"] == MAC.value
        assert rows[0]["source"] == "가상 데이터"
        assert rows[1]["outcome"] == "error"
        assert rows[1]["error"] == "MM 조회 실패"
        assert store.events(session)[0]["facts"] == {"AP": "DEMO-AP-01"}
        store.end_session(session)
        sessions = store.sessions()
        assert sessions[0]["simulated"] is True
        assert sessions[0]["ended_at"]


def test_storage_filters_period_and_rejects_reversed_period(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session("query")
        for day in (1, 2, 3):
            at = f"2026-01-0{day}T12:00:00+00:00"
            store.save_poll(session, PollResult(Outcome.OK, Observation(collected_at=at), collected_at=at), [Event("x", "x", at=at)])
        start, end = "2026-01-02T00:00:00+00:00", "2026-01-02T23:59:59+00:00"
        assert len(store.observations(session, start, end)) == 1
        assert len(store.events(session, start, end)) == 1
        with pytest.raises(ValueError):
            store.observations(session, end, start)


def test_export_csv_formula_and_html_script_escape(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session("<script>alert(1)</script>", simulated=True)
        obs = Observation(ssid="=1+1", role="<script>bad</script>", simulated=True)
        store.save_poll(session, PollResult(Outcome.OK, obs), [Event("role", "<script>bad</script>", hypothesis="미확인", recommendation="장비 확인")])
        store.export_csv(session, tmp_path / "report.csv")
        store.export_html(session, tmp_path / "report.html")
        csv_text = (tmp_path / "report.csv").read_text(encoding="utf-8-sig")
        assert "'=1+1" in csv_text
        assert "수집 시각" in csv_text
        html_text = (tmp_path / "report.html").read_text(encoding="utf-8")
        assert "<script>" not in html_text
        assert "&lt;script&gt;" in html_text
        assert "추정 원인" in html_text
        assert "추가 확인 사항" in html_text
        assert "가상 데이터" in html_text


def test_storage_concurrent_writes(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session("query")
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(lambda _: store.save_poll(session, PollResult(Outcome.OK, Observation()), []), range(80)))
        assert len(store.observations(session)) == 80


@pytest.mark.parametrize("target", [IP, MAC])
def test_demo_search_normal(target):
    demo = DemoCollector("normal")
    result = demo.poll(target)
    assert result.outcome == Outcome.OK
    assert result.observation.mac == MAC.value
    assert result.observation.simulated
    assert "가상" in result.observation.source


def test_demo_unknown_client_not_arbitrary():
    assert DemoCollector("normal").poll(Target("ip", "192.0.2.200")).outcome == Outcome.ABSENT
    assert DemoCollector("normal").poll(Target("mac", "02:00:00:00:00:ff")).outcome == Outcome.ABSENT


@pytest.mark.parametrize("scenario,field,expected", [
    ("ip_change", "ip", "192.0.2.101"),
    ("snr_drop", "snr", 12.0),
    ("rate_drop", "tx_rate", 24.0),
    ("roam", "ap_name", "DEMO-AP-02"),
    ("role_change", "role", "demo-quarantine"),
    ("retries", "retries", 350),
    ("md_change", "md", "DEMO-MD-02"),
])
def test_demo_changes_after_baseline(scenario, field, expected):
    demo = DemoCollector(scenario)
    first = demo.poll(IP)
    second = demo.poll(MAC)
    assert first.outcome == second.outcome == Outcome.OK
    assert getattr(second.observation, field) == expected
    assert getattr(first.observation, field) != expected


@pytest.mark.parametrize("scenario", ["mm_failure", "md_failure", "format_change"])
def test_demo_failure_not_absent(scenario):
    demo = DemoCollector(scenario)
    assert demo.poll(IP).outcome == Outcome.OK
    result = demo.poll(MAC)
    assert result.outcome == Outcome.ERROR
    assert result.error
    assert result.observation is None


def test_demo_disconnect_and_reconnect():
    demo = DemoCollector("disconnect")
    outcomes = [demo.poll(MAC).outcome for _ in range(4)]
    assert outcomes == [Outcome.OK, Outcome.ABSENT, Outcome.ABSENT, Outcome.OK]
    reconnect = DemoCollector("reconnect")
    assert [reconnect.poll(MAC).outcome for _ in range(4)] == outcomes


def test_duplicate_requires_explicit_selection_and_pins_mac():
    demo = DemoCollector("duplicate")
    result = demo.poll(IP)
    assert result.outcome == Outcome.AMBIGUOUS
    assert len(result.candidates) == 2
    chosen = result.candidates[1].mac
    selected = demo.poll(IP, selected_mac=chosen)
    assert selected.outcome == Outcome.OK
    assert selected.observation.mac == chosen
    assert demo.poll(IP, selected_mac="02:00:00:00:00:ff").outcome == Outcome.ABSENT


def test_demo_can_close_restart_and_cancel():
    import threading
    demo = DemoCollector("normal")
    demo.close()
    assert demo.poll(IP).outcome == Outcome.OK
    cancel = threading.Event()
    cancel.set()
    assert demo.poll(IP, cancel=cancel).outcome == Outcome.ERROR


def test_all_17_scenario_labels():
    assert {"cycle", "normal", "ip_search", "mac_search", "ip_change", "snr_drop", "rate_drop", "roam", "role_change", "retries", "disconnect", "reconnect", "mm_failure", "md_failure", "md_change", "format_change", "invalid_mac", "duplicate"} <= SCENARIOS.keys()


def test_long_demo_collection_has_bounded_memory_and_no_connections():
    demo = DemoCollector("cycle")
    tracemalloc.start()
    try:
        for _ in range(100):
            demo.poll(MAC)
        gc.collect()
        initial = tracemalloc.get_traced_memory()[0]
        for _ in range(10000):
            demo.poll(MAC)
        gc.collect()
        final = tracemalloc.get_traced_memory()[0]
        assert final - initial < 200000
        assert demo.connection_count == 0
    finally:
        tracemalloc.stop()


def test_cycle_duplicate_selection_remains_valid_next_poll():
    demo = DemoCollector("cycle")
    for _ in range(19):
        result = demo.poll(IP)
    assert result.outcome == Outcome.AMBIGUOUS
    selected = result.candidates[1].mac
    assert demo.poll(IP, selected_mac=selected).observation.mac == selected


def test_csv_failure_and_events_remain_marked_simulated(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value, simulated=True)
        store.save_poll(session, PollResult(Outcome.ERROR, error="가상 MM 오류"), [Event("failure", "가상 실패")])
        path = store.export_csv(session, tmp_path / "report.csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert all(row["가상 데이터"] == "예" for row in rows)


def test_demo_counter_source_is_explicit_for_ratio_calculation():
    result = DemoCollector("normal").poll(MAC)
    assert result.observation.evidence.get("counter_source") == "demo"


def test_exports_distinguish_unknown_connection_and_previous_metric_timestamp(tmp_path):
    import html
    import re

    old_at = "2026-01-02T12:00:00+00:00"
    current_at = "2026-01-02T12:00:15+00:00"
    evidence = f"show ap debug client-table ap-name DEMO-AP-01 | 조회={old_at}"
    obs = Observation(
        collected_at=current_at, connected=True, snr=36.0,
        field_status={"connected": "확인 불가", "snr": "이전 조회값 · 조회 실패"},
        evidence={"snr": evidence},
    )
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value)
        store.save_poll(session, PollResult(Outcome.OK, obs, collected_at=current_at), [])
        csv_path = store.export_csv(session, tmp_path / "report.csv")
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            row = next(csv.DictReader(handle))
        assert row["연결 여부"] == "확인 불가"
        assert "36.0" in row["SNR (dB)"] and "이전 조회값" in row["SNR (dB)"]
        assert "조회 실패" in row["항목별 상태"]
        assert evidence in row["수집 근거/항목별 관측 시각"]
        assert row["유효 관측 시각"] == current_at
        html_path = store.export_html(session, tmp_path / "report.html")
        report = html_path.read_text(encoding="utf-8")
        headers = [html.unescape(value) for value in re.findall(r"<th>(.*?)</th>", report)]
        values = [html.unescape(value) for value in re.findall(r"<td>(.*?)</td>", report)]
        html_row = dict(zip(headers, values, strict=True))
        assert html_row["연결 여부"] == "확인 불가"
        assert "36.0" in html_row["SNR (dB)"] and "이전 조회값" in html_row["SNR (dB)"]
        assert "조회 실패" in html_row["항목별 상태"]
        assert evidence in html_row["수집 근거/항목별 관측 시각"]
