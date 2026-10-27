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


def test_demo_failure_collector_marks_session_as_simulated(tmp_path):
    demo = DemoCollector("invalid_mac")
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value, simulated=getattr(demo, "simulated", False))
        result = demo.poll(IP)
        assert result.outcome == Outcome.ERROR
        store.save_poll(session, result, [])
        assert store.sessions()[0]["simulated"] is True


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


def test_ten_demo_clients_resolve_by_ip_and_mac_with_independent_state():
    from aruba_client_live_tracker.demo import DEMO_CLIENTS

    assert len(DEMO_CLIENTS) == 10
    collectors = [DemoCollector("ip_change") for _ in range(10)]
    for index, (candidate, collector) in enumerate(zip(DEMO_CLIENTS, collectors, strict=True)):
        expected_ip = f"192.0.2.{100 + index}"
        expected_mac = f"02:00:00:00:00:{index + 1:02x}"
        first = collector.poll(Target("ip", expected_ip)).observation
        assert (candidate.ip, candidate.mac) == (expected_ip, expected_mac)
        assert (first.ip, first.mac) == (expected_ip, expected_mac)
        by_mac = DemoCollector("normal").poll(Target("mac", expected_mac)).observation
        assert (by_mac.ip, by_mac.mac) == (expected_ip, expected_mac)
    changed = collectors[0].poll(IP).observation
    assert (changed.ip, changed.mac) == ("192.0.2.101", MAC.value)
    assert collectors[1].poll(Target("ip", "192.0.2.101")).observation.mac == "02:00:00:00:00:02"
    normal = [DemoCollector("normal").poll(Target("ip", item.ip)).observation for item in DEMO_CLIENTS]
    assert normal[0].md == normal[2].md
    assert normal[0].md != normal[1].md
    assert all(item.simulated for item in normal)
    assert all(collector.connection_count == 0 for collector in collectors)


def test_demo_ip_identity_stays_pinned_after_address_change():
    collector = DemoCollector("ip_change")
    first = collector.poll(IP).observation
    changed = collector.poll(IP).observation
    assert first.mac == changed.mac == MAC.value
    assert first.ip != changed.ip
    unknown = collector.poll(Target("ip", "192.0.2.200"))
    assert unknown.outcome == Outcome.ABSENT


def test_demo_duplicate_cannot_select_an_unoffered_inventory_client():
    collector = DemoCollector("duplicate")
    assert collector.poll(IP).outcome == Outcome.AMBIGUOUS
    assert collector.poll(IP, selected_mac="02:00:00:00:00:0a").outcome == Outcome.ABSENT


@pytest.mark.parametrize("scenario,field", [("roam", "ap_name"), ("md_change", "md")])
def test_demo_mobility_scenarios_change_each_inventory_client(scenario, field):
    from aruba_client_live_tracker.demo import DEMO_CLIENTS

    for candidate in DEMO_CLIENTS:
        collector = DemoCollector(scenario)
        target = Target("ip", candidate.ip)
        before = collector.poll(target).observation
        after = collector.poll(target).observation
        assert after.mac == before.mac == candidate.mac
        assert getattr(after, field) != getattr(before, field)


def test_ten_target_combined_export_keeps_separate_sessions_and_inclusive_period(tmp_path):
    from aruba_client_live_tracker.demo import DEMO_CLIENTS

    start, end = "2026-01-02T12:00:00Z", "2026-01-02T12:00:09Z"
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        ids = []
        for index, candidate in enumerate(DEMO_CLIENTS):
            session = store.start_session(candidate.ip, simulated=True)
            ids.append(session)
            result = DemoCollector("normal").poll(Target("ip", candidate.ip))
            result.collected_at = f"2026-01-02T12:00:{index:02d}+00:00"
            result.observation.collected_at = result.collected_at
            store.save_poll(session, result, [Event("connect", f"client {index}", at=result.collected_at)])
        path = store.export_many_csv(reversed(ids), tmp_path / "ten.csv", start, end)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 20
        assert [int(row["세션 ID"]) for row in rows] == [item for item in ids for _ in range(2)]
        for index in range(10):
            for row in rows[2 * index:2 * index + 2]:
                assert row["대상 IP"] == f"192.0.2.{100 + index}"
                assert row["대상 MAC"] == f"02:00:00:00:00:{index + 1:02x}"
                assert row["가상 데이터"] == "예"
        filtered = store.export_many_csv(ids, tmp_path / "one.csv", end, end)
        with filtered.open(encoding="utf-8-sig", newline="") as handle:
            selected_rows = list(csv.DictReader(handle))
        assert len([row for row in selected_rows if row["기록 유형"] == "관측"]) == 1
        assert len([row for row in selected_rows if row["상태"] == "기간 내 기록 없음"]) == 9


def test_combined_reports_order_events_with_observations_and_preserve_identity(tmp_path):
    import html
    import re

    with HistoryStore(tmp_path / "history.sqlite3") as store:
        first = store.start_session("=QUERY<script>", simulated=True)
        second = store.start_session("192.0.2.101")
        early, middle, late = [f"2026-01-02T12:00:{seconds:02d}+00:00" for seconds in (0, 5, 10)]
        obs = Observation(collected_at=late, ip=IP.value, mac=MAC.value, ssid="=1+1",
                          field_status={"snr": "이전 조회값 · 조회 실패"},
                          evidence={"snr": f"조회={early}"}, snr=36.0)
        store.save_poll(first, PollResult(Outcome.OK, obs, collected_at=late), [])
        store.save_poll(second, PollResult(Outcome.ERROR, error="<script>bad</script>", collected_at=early), [
            Event("failure", "<script>event</script>", at=middle, facts={"fact": "seen"},
                  hypothesis="=unknown", recommendation="@check"),
        ])
        csv_path = store.export_many_csv([first, second], tmp_path / "combined.csv")
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [row["기록 유형"] for row in rows] == ["관측", "이벤트", "관측"]
        assert [row["세션 ID"] for row in rows] == [str(second), str(second), str(first)]
        assert rows[0]["검색 조건"] == rows[1]["검색 조건"] == "192.0.2.101"
        assert rows[0]["대상 IP"] == rows[1]["대상 IP"] == "192.0.2.101"
        assert rows[2]["대상 MAC"] == MAC.value
        assert rows[2]["검색 조건"] == "'=QUERY<script>"
        assert [row["가상 데이터"] for row in rows] == ["아니요", "아니요", "예"]
        assert rows[1]["추정 원인"] == "'=unknown"
        assert rows[1]["추가 확인 사항"] == "'@check"
        assert "seen" in rows[1]["관측 사실"]
        assert "이전 조회값" in rows[2]["SNR (dB)"]
        assert early in rows[2]["수집 근거/항목별 관측 시각"]
        report = store.export_many_html([first, second], tmp_path / "combined.html").read_text(encoding="utf-8")
        assert "<script>" not in report
        assert "&lt;script&gt;" in report
        headers = [html.unescape(value) for value in re.findall(r"<th>(.*?)</th>", report)]
        records = [dict(zip(headers, [html.unescape(value) for value in re.findall(r"<td>(.*?)</td>", row)], strict=True))
                   for row in re.findall(r"<tr>(.*?)</tr>", report) if "<td>" in row]
        assert [row["기록 유형"] for row in records] == ["관측", "이벤트", "관측"]
        assert records[1]["대상 IP"] == "192.0.2.101"
        assert records[1]["추가 확인 사항"] == "@check"
        assert "조회 실패" in records[2]["항목별 상태"]


def test_combined_filtered_failure_uses_previous_identity_without_claiming_current_measurement(tmp_path):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value)
        old, current = "2026-01-02T12:00:00Z", "2026-01-02T12:00:10Z"
        store.save_poll(session, PollResult(Outcome.OK, Observation(
            collected_at=old, ip="192.0.2.150", mac=MAC.value), collected_at=old), [])
        store.save_poll(session, PollResult(Outcome.ERROR, error="MM failed", collected_at=current), [
            Event("failure", "query failed", at="2026-01-02T13:00:10+01:00"),
        ])
        path = store.export_many_csv([session], tmp_path / "failure.csv", current, current)
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 2
        assert all(row["대상 IP"] == "192.0.2.150" and row["대상 MAC"] == MAC.value for row in rows)
        assert all(row["대상 식별 관측 시각"] == old for row in rows)
        assert all(row["유효 관측 시각"] == "확인 불가" for row in rows)
        assert all(row["IP"] == row["MAC"] == "확인 불가" for row in rows)


@pytest.mark.parametrize("kind", ["csv", "html"])
def test_combined_export_validates_all_ids_before_writing_and_preserves_empty_sessions(tmp_path, kind):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session("02:00:00:00:00:0a", simulated=True)
        export = getattr(store, f"export_many_{kind}")
        path = tmp_path / f"combined.{kind}"
        for ids in ([], [session, session + 1], [None], [True]):
            with pytest.raises(ValueError):
                export(ids, path)
            assert not path.exists()
        export([session, session], path, "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z")
        text = path.read_text(encoding="utf-8-sig")
        assert "02:00:00:00:00:0a" in text
        assert "기간 내 기록 없음" in text
        assert "가상" in text
        with pytest.raises(ValueError):
            export([session], path, "2026-01-02T00:00:00Z", "2026-01-01T00:00:00Z")


def test_diagnostics_upgrade_roundtrip_and_safe_reports(tmp_path):
    import sqlite3

    from aruba_client_live_tracker.models import Diagnostic

    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE sessions (id INTEGER PRIMARY KEY, query TEXT NOT NULL,
                simulated INTEGER NOT NULL, started_at TEXT NOT NULL, ended_at TEXT);
            CREATE TABLE polls (id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                collected_at TEXT NOT NULL, outcome TEXT NOT NULL, error TEXT NOT NULL,
                mm_status TEXT NOT NULL, md_status TEXT NOT NULL, observation TEXT);
            INSERT INTO sessions VALUES (1, '192.0.2.100', 0, '2026-01-01T00:00:00Z', NULL);
            INSERT INTO polls VALUES (1, 1, '2026-01-01T00:00:00+00:00', 'error', 'old', '', '', NULL);
        """)
    with HistoryStore(path) as store:
        assert store.observations(1)[0]["diagnostics"] == []
        diagnostic = Diagnostic("md_command", "=BAD", "<script>bad</script> password=secret",
                                device_name="@WLC", endpoint="192.0.2.1:22", command="show user-table",
                                at="2026-01-02T00:00:00Z")
        store.save_poll(1, PollResult(Outcome.ERROR, error="failed", collected_at=diagnostic.at,
                                    diagnostics=[diagnostic], raw={"command": "RAW_SECRET"}), [])
    with HistoryStore(path) as store:
        rows = store.observations(1)
        assert len(rows) == 2
        assert rows[1]["diagnostics"][0]["stage"] == "md_command"
        assert "secret" not in rows[1]["diagnostics"][0]["message"]
        for many in (False, True):
            args = ([1],) if many else (1,)
            prefix = "export_many_" if many else "export_"
            csv_path = getattr(store, prefix + "csv")(*args, tmp_path / f"{many}.csv")
            with csv_path.open(encoding="utf-8-sig", newline="") as handle:
                records = list(csv.DictReader(handle))
            assert records[-1]["진단 단계"] == "md_command"
            assert records[-1]["진단 단계명"] == "WLC 명령 실행"
            assert records[-1]["진단 코드"] == "'=BAD"
            assert records[-1]["진단 장비"] == "'@WLC"
            assert records[-1]["진단 명령"] == "show user-table"
            html_path = getattr(store, prefix + "html")(*args, tmp_path / f"{many}.html")
            report = html_path.read_text(encoding="utf-8")
            assert "<script>" not in report
            assert "&lt;script&gt;" in report
            assert "secret" not in report
    assert b"RAW_SECRET" not in path.read_bytes()


@pytest.mark.parametrize("encoded", ["invalid", "{}", '[null]', '[{"stage": 1}]', '"oops"', '[' * 2000])
def test_corrupt_diagnostics_are_unavailable_instead_of_crashing(tmp_path, encoded):
    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value)
        store.save_poll(session, PollResult(Outcome.ERROR), [])
        with store._db:
            store._db.execute("UPDATE polls SET diagnostics = ?", (encoded,))
        row = store.observations(session)[0]
        assert row["diagnostics"][0]["code"] == "diagnostics_unavailable"
        for prefix, selection in (("export_", session), ("export_many_", [session])):
            for kind in ("csv", "html"):
                path = getattr(store, prefix + kind)(selection, tmp_path / f"{prefix}.{kind}")
                assert "진단 기록 확인 불가" in path.read_text(encoding="utf-8-sig")


def test_diagnostics_and_events_rollback_together_on_save_failure(tmp_path):
    from aruba_client_live_tracker.models import Diagnostic

    with HistoryStore(tmp_path / "history.sqlite3") as store:
        session = store.start_session(IP.value)
        result = PollResult(Outcome.ERROR, diagnostics=[Diagnostic("auth", "auth_failed", "인증 실패")])
        with pytest.raises(ValueError):
            store.save_poll(session, result, [Event("failure", "failed", at="not a timestamp")])
        assert store.observations(session) == []
        assert store.events(session) == []


def test_diagnostics_combined_identity_order_and_bounds(tmp_path):
    import json

    from aruba_client_live_tracker.models import Diagnostic

    with HistoryStore(tmp_path / "history.sqlite3") as store:
        ids = [store.start_session(ip) for ip in ("192.0.2.100", "192.0.2.101")]
        for index in (1, 0):
            at = f"2026-01-02T00:00:0{index}Z"
            diagnostics = [Diagnostic("connect", "failed", "safe", device_name="  =unsafe", at=at),
                           Diagnostic("auth", "denied", "x" * 5000, at=at)]
            store.save_poll(ids[index], PollResult(Outcome.ERROR, collected_at=at, diagnostics=diagnostics), [])
        path = store.export_many_csv(reversed(ids), tmp_path / "diagnostics.csv")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [int(row["세션 ID"]) for row in rows] == ids
        assert [row["대상 IP"] for row in rows] == ["192.0.2.100", "192.0.2.101"]
        assert all(row["진단 장비"].startswith("'  =unsafe") for row in rows)
        assert all(row["진단 단계"] == "connect\nauth" for row in rows)
        assert len(store.observations(ids[0])[0]["diagnostics"][1]["message"]) == 2048
        for encoded in (json.dumps([{}] * 129), " " * (512 * 1024 + 1)):
            with store._db:
                store._db.execute("UPDATE polls SET diagnostics = ?", (encoded,))
            assert store.observations(ids[0])[0]["diagnostics"][0]["code"] == "diagnostics_unavailable"
