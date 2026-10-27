import os
import sqlite3
import time
from pathlib import Path

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from aruba_client_live_tracker.models import Event, Observation, Outcome, PollResult
from aruba_client_live_tracker.storage import HistoryStore


@pytest.mark.parametrize('method', ['export_csv', 'export_html', 'export_many_csv', 'export_many_html'])
def test_report_partial_write_failure_preserves_existing_file(tmp_path, monkeypatch, method):
    with HistoryStore(tmp_path / 'history.db') as store:
        session = store.start_session('192.0.2.100', simulated=True)
        store.save_poll(session, PollResult(Outcome.OK, Observation(simulated=True)), [])
        destination = tmp_path / ('report.csv' if method.endswith('csv') else 'report.html')
        original = b'previous complete report'
        destination.write_bytes(original)
        real_open = Path.open

        class FailedWrite:
            def __init__(self, handle):
                self.handle = handle

            def __enter__(self):
                return self

            def __exit__(self, *args):
                self.handle.close()

            def write(self, text):
                self.handle.write(text[:20])
                self.handle.flush()
                raise OSError('synthetic disk full')

        def open_report(path, mode='r', *args, **kwargs):
            handle = real_open(path, mode, *args, **kwargs)
            if 'w' in mode and path.parent == tmp_path:
                return FailedWrite(handle)
            return handle

        monkeypatch.setattr(Path, 'open', open_report)
        selection = [session] if 'many' in method else session
        with pytest.raises(OSError, match='synthetic disk full'):
            getattr(store, method)(selection, destination)
        assert destination.read_bytes() == original
        assert not list(tmp_path.glob('.report-*'))


@pytest.mark.parametrize('encoded', ['{', '[]', 'null', '{"field_status": []}'])
def test_corrupt_observation_json_has_safe_actionable_error(tmp_path, encoded):
    with HistoryStore(tmp_path / 'history.db') as store:
        session = store.start_session('192.0.2.100', simulated=True)
        store.save_poll(session, PollResult(Outcome.OK, Observation(simulated=True)), [])
        with store._db:
            store._db.execute('UPDATE polls SET observation = ?', (encoded,))
        with pytest.raises(ValueError, match='HISTORY_DATA_INVALID'):
            store.observations(session)
        assert store.sessions()[0]['id'] == session


@pytest.mark.parametrize('encoded', ['{', '[]', 'null', '{"kind": "synthetic"}'])
def test_corrupt_event_json_has_safe_actionable_error(tmp_path, encoded):
    with HistoryStore(tmp_path / 'history.db') as store:
        session = store.start_session('192.0.2.100', simulated=True)
        store.save_poll(session, PollResult(Outcome.OK), [Event('synthetic', '가상 이벤트')])
        with store._db:
            store._db.execute('UPDATE events SET data = ?', (encoded,))
        with pytest.raises(ValueError, match='HISTORY_DATA_INVALID'):
            store.events(session)
        assert store.sessions()[0]['id'] == session


def test_history_preview_corruption_is_shown_without_raw_payload(qtbot, tmp_path):
    from aruba_client_live_tracker.ui import HistoryDialog

    with HistoryStore(tmp_path / 'history.db') as store:
        session = store.start_session('192.0.2.100', simulated=True)
        store.save_poll(session, PollResult(Outcome.OK, Observation(simulated=True)), [])
        with store._db:
            store._db.execute('UPDATE polls SET observation = ?', ('{"private-payload"',))
        dialog = HistoryDialog(store)
        qtbot.addWidget(dialog)
        dialog.grid.selectRow(0)
        dialog.show_history()
        assert 'HISTORY_DATA_INVALID' in dialog.preview.toPlainText()
        assert 'private-payload' not in dialog.preview.toPlainText()


def test_external_write_lock_returns_promptly_without_creating_session(tmp_path):
    with HistoryStore(tmp_path / 'history.db') as store:
        with sqlite3.connect(store.path) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            started = time.monotonic()
            with pytest.raises(sqlite3.OperationalError, match='locked'):
                store.start_session('192.0.2.100', simulated=True)
            elapsed = time.monotonic() - started
            blocker.rollback()
        assert elapsed < 0.5, f'GUI history write blocked for {elapsed:.2f}s'
        assert store.sessions() == []
        session = store.start_session('192.0.2.100', simulated=True)
        assert store.sessions()[0]['id'] == session


def test_store_close_failure_keeps_window_open_and_can_retry(qtbot, tmp_path, monkeypatch):
    from PySide6.QtGui import QCloseEvent

    from aruba_client_live_tracker.ui import MainWindow

    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    original_close = window.store.close
    def failed_close():
        raise sqlite3.OperationalError('synthetic close error')
    monkeypatch.setattr(window.store, 'close', failed_close)
    event = QCloseEvent()
    try:
        window.closeEvent(event)
        assert not event.isAccepted()
        assert not window._closed
        assert not window.pending_close
        assert 'HISTORY_CLOSE_FAILED' in window.status_note.text()
    finally:
        monkeypatch.setattr(window.store, 'close', original_close)
        window.close()
    assert window._closed
    with pytest.raises(RuntimeError, match='닫혀'):
        window.store.sessions()


@pytest.mark.parametrize('action', ['stop', 'start', 'remove', 'close'])
def test_failed_session_end_remains_retryable_without_losing_history(tmp_path, action):
    from aruba_client_live_tracker.demo import DemoCollector
    from aruba_client_live_tracker.monitoring import MonitoringCoordinator

    with HistoryStore(tmp_path / 'history.db') as store:
        manager = MonitoringCoordinator(store, lambda _: DemoCollector())
        identifier = manager.add('192.0.2.100')
        manager.start(identifier)
        session = manager.contexts[identifier].session_id
        with sqlite3.connect(store.path) as blocker:
            blocker.execute('BEGIN IMMEDIATE')
            if action == 'close':
                assert not manager.close(wait=False)
            else:
                manager.stop(identifier)
                getattr(manager, action)(identifier)
            blocker.rollback()
        assert identifier in manager.contexts
        assert manager.contexts[identifier].session_id == session
        assert len(store.sessions()) == 1
        assert store.sessions()[0]['ended_at'] is None
        assert manager.close(wait=True)
        assert store.sessions()[0]['ended_at'] is not None


def test_shutdown_session_write_failure_stays_visible_until_retry(qtbot, tmp_path):
    from PySide6.QtGui import QCloseEvent

    from aruba_client_live_tracker.ui import MainWindow

    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    identifier = window.coordinator.add('192.0.2.100')
    window.coordinator.start(identifier)
    history_path = window.store.path
    with sqlite3.connect(window.store.path) as blocker:
        blocker.execute('BEGIN IMMEDIATE')
        event = QCloseEvent()
        try:
            window.closeEvent(event)
            assert not event.isAccepted()
            assert not window.pending_close
            assert not window._closed
            assert 'HISTORY_END_FAILED' in window.status_note.text()
        finally:
            blocker.rollback()
    window.close()
    assert window._closed
    with HistoryStore(history_path) as reopened:
        assert reopened.sessions()[0]['ended_at'] is not None
