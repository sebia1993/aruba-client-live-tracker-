"""Synthetic regression checks for bounded history and independent exports."""
import csv
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from aruba_client_live_tracker import storage
from aruba_client_live_tracker.models import Event, Observation, Outcome, PollResult
from aruba_client_live_tracker.storage import HistoryStore
from aruba_client_live_tracker.ui import HistoryDialog


def populate(store, count=401):
    session = store.start_session("192.0.2.100", simulated=True)
    for i in range(count):
        stamp = f"2026-10-27T00:{i // 60:02}:{i % 60:02}+00:00"
        store.save_poll(session, PollResult(Outcome.OK, Observation(collected_at=stamp, snr=i),
                                          collected_at=stamp), [])
    return session


def test_preview_decodes_only_latest_two_hundred_records(qtbot, tmp_path, monkeypatch):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store)
        calls = []
        original = storage._read_history_record
        def read(encoded, **kwargs):
            calls.append(encoded)
            return original(encoded, **kwargs)
        monkeypatch.setattr(storage, "_read_history_record", read)
        dialog = HistoryDialog(store)
        qtbot.addWidget(dialog)
        dialog.selection = lambda: ([session], None, None)
        dialog.show_history()
        text = dialog.preview.toPlainText()
        assert "관측 401건" in text
        assert len(text.splitlines()) == 202
        assert "SNR 400" in text
        assert "SNR 200 |" not in text
        assert len(calls) <= 200, "Preview must bound JSON decoding before fetching history."


def test_preview_uses_session_time_index_instead_of_global_history_sort(tmp_path, monkeypatch):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 3)
        queries = []
        connect = sqlite3.connect
        def traced_connect(*args, **kwargs):
            connection = connect(*args, **kwargs)
            connection.set_trace_callback(queries.append)
            return connection
        monkeypatch.setattr(storage.sqlite3, "connect", traced_connect)
        store.history_preview([session])
        sorted_queries = [query for query in queries if "ORDER BY" in query]
        assert sorted_queries
        assert all("session_id =" in query for query in sorted_queries), sorted_queries


def test_preview_keeps_existing_selection_order_for_equal_timestamps(tmp_path):
    with HistoryStore(tmp_path / "history.db") as store:
        first = populate(store, 1)
        second = populate(store, 1)
        rows, _, count, _ = store.history_preview([second, first])
        assert count == 2
        assert [row["session_id"] for row in rows] == [second, first]


def test_slow_export_reader_does_not_hold_runtime_store_lock(tmp_path, monkeypatch):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 2)
        entered, release = threading.Event(), threading.Event()
        original = storage._read_history_record
        def slow_read(encoded, **kwargs):
            entered.set()
            assert release.wait(3)
            return original(encoded, **kwargs)
        monkeypatch.setattr(storage, "_read_history_record", slow_read)
        with ThreadPoolExecutor(max_workers=2) as pool:
            exporting = pool.submit(store.export_many_csv, [session], tmp_path / "report.csv")
            assert entered.wait(2)
            writing = pool.submit(store.start_session, "192.0.2.101", True)
            try:
                assert writing.result(timeout=.3) > session
            finally:
                release.set()
            exporting.result(timeout=3)


def test_dialog_export_returns_while_worker_runs_and_close_cancels(qtbot, tmp_path, monkeypatch):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 1)
        entered, release = threading.Event(), threading.Event()
        received = []
        def slow_export(*args, **kwargs):
            received.append(kwargs.get("cancel_event"))
            entered.set()
            release.wait(1)
        monkeypatch.setattr(store, "export_many_csv", slow_export)
        monkeypatch.setattr("aruba_client_live_tracker.ui.QFileDialog.getSaveFileName",
                            lambda *a: (str(tmp_path / "report.csv"), ""))
        monkeypatch.setattr("aruba_client_live_tracker.ui.QMessageBox.information", lambda *a: None)
        dialog = HistoryDialog(store)
        qtbot.addWidget(dialog)
        dialog.selection = lambda: ([session], None, None)
        started = time.monotonic()
        dialog.export("csv")
        try:
            assert time.monotonic() - started < .3
            assert entered.wait(1)
            dialog.close()
            assert received[0] is not None and received[0].is_set()
        finally:
            release.set()
        qtbot.waitUntil(lambda: not dialog.export_running, timeout=3000)


@pytest.mark.parametrize("failed", [False, True])
def test_dialog_reports_finished_export_in_status_and_reenables_controls(qtbot, tmp_path, monkeypatch, failed):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 1)
        destination = tmp_path / "report.csv" if not failed else tmp_path / "missing" / "report.csv"
        monkeypatch.setattr("aruba_client_live_tracker.ui.QFileDialog.getSaveFileName",
                            lambda *a: (str(destination), ""))
        messages = []
        monkeypatch.setattr("aruba_client_live_tracker.ui.QMessageBox.information",
                            lambda *a: messages.append("complete"))
        monkeypatch.setattr("aruba_client_live_tracker.ui.QMessageBox.warning",
                            lambda *a: messages.append("failed"))
        dialog = HistoryDialog(store)
        qtbot.addWidget(dialog)
        dialog.selection = lambda: ([session], None, None)
        dialog.export("csv")
        qtbot.waitUntil(lambda: bool(messages), timeout=3000)
        assert messages == ["failed" if failed else "complete"]
        assert "저장하는 중" not in dialog.preview.toPlainText()
        assert ("REPORT_WRITE_FAILED" if failed else "저장했습니다") in dialog.preview.toPlainText()
        assert all(button.isEnabled() for button in dialog._history_controls)


@pytest.mark.parametrize("extension", ["csv", "html"])
def test_cancelled_export_preserves_existing_report_and_cleans_temporary(tmp_path, extension):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 3)
        destination = tmp_path / f"report.{extension}"
        destination.write_bytes(b"previous complete report")
        cancellation = threading.Event()
        cancellation.set()
        with pytest.raises(storage.ReportCancelled):
            getattr(store, f"export_many_{extension}")([session], destination, cancel_event=cancellation)
        assert destination.read_bytes() == b"previous complete report"
        assert not list(tmp_path.glob(".report-*.tmp"))


def test_streaming_export_keeps_snapshot_while_monitoring_writes(tmp_path, monkeypatch):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 2)
        original = storage._read_history_record
        changed = False
        def write_during_read(encoded, **kwargs):
            nonlocal changed
            if not changed:
                changed = True
                store.save_poll(session, PollResult(Outcome.ERROR, collected_at="2026-10-27T01:00:00Z"), [])
            return original(encoded, **kwargs)
        monkeypatch.setattr(storage, "_read_history_record", write_during_read)
        destination = store.export_many_csv([session], tmp_path / "report.csv")
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            assert len(list(csv.DictReader(handle))) == 2
        assert len(store.observations(session)) == 3


def test_export_same_timestamp_identity_includes_last_poll_at_that_instant(tmp_path):
    with HistoryStore(tmp_path / "history.db") as store:
        session = store.start_session("192.0.2.100", simulated=True)
        stamp = "2026-10-27T00:00:00Z"
        for mac in ("02:00:00:00:00:01", "02:00:00:00:00:02"):
            store.save_poll(session, PollResult(Outcome.OK, Observation(collected_at=stamp, mac=mac),
                                              collected_at=stamp), [])
        store.save_poll(session, PollResult(Outcome.ERROR, collected_at=stamp), [Event("test", "test", at=stamp)])
        destination = store.export_many_csv([session], tmp_path / "report.csv")
        with destination.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 4
        assert [row["기록 유형"] for row in rows] == ["관측", "관측", "관측", "이벤트"]
        assert all(row["대상 MAC"] == "02:00:00:00:00:02" for row in rows)


def test_export_reader_survives_runtime_store_close_without_using_closed_connection(tmp_path, monkeypatch):
    store = HistoryStore(tmp_path / "history.db")
    session = populate(store, 2)
    entered, release = threading.Event(), threading.Event()
    original = storage._read_history_record
    def paused_read(encoded, **kwargs):
        entered.set()
        assert release.wait(3)
        return original(encoded, **kwargs)
    monkeypatch.setattr(storage, "_read_history_record", paused_read)
    with ThreadPoolExecutor(max_workers=1) as pool:
        exporting = pool.submit(store.export_many_csv, [session], tmp_path / "report.csv")
        assert entered.wait(2)
        store.close()
        release.set()
        assert exporting.result(timeout=3).exists()


@pytest.mark.parametrize("extension", ["csv", "html"])
def test_cancellation_after_flush_before_publish_preserves_existing_file(tmp_path, monkeypatch, extension):
    with HistoryStore(tmp_path / "history.db") as store:
        session = populate(store, 2)
        destination = tmp_path / f"report.{extension}"
        destination.write_bytes(b"previous complete report")
        cancellation = threading.Event()
        fsync = storage.os.fsync
        def cancel_at_flush(fd):
            fsync(fd)
            cancellation.set()
        monkeypatch.setattr(storage.os, "fsync", cancel_at_flush)
        with pytest.raises(storage.ReportCancelled):
            getattr(store, f"export_many_{extension}")([session], destination, cancel_event=cancellation)
        assert destination.read_bytes() == b"previous complete report"
        assert not list(tmp_path.glob(".report-*.tmp"))
