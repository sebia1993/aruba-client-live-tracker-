"""Timed diagnostic runs never touch user data or claim an early exit passed."""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest


def run_soak(tmp_path, *extra, duration='3'):
    return subprocess.run([
        sys.executable, '-m', 'aruba_client_live_tracker.main', '--multi-demo',
        '--soak-seconds', duration, '--data-dir', str(tmp_path / 'data'),
        '--smoke-result', str(tmp_path / 'result.json'), *map(str, extra),
    ], capture_output=True, text=True, encoding='utf-8', timeout=20,
        env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'))


def test_soak_waits_requested_time_and_closes_ten_sessions(tmp_path):
    started = time.monotonic()
    result = run_soak(tmp_path)
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started >= 3
    saved = json.loads((tmp_path / 'result.json').read_text(encoding='utf-8'))
    assert saved['success'] and saved['diagnostic'] == 'timed-demo-soak'
    assert saved['scenario'] == 'normal'
    assert saved['elapsed_seconds'] >= 3
    assert saved['target_count'] == saved['independent_macs'] == 10
    assert len(saved['target_observations']) == 10
    assert min(saved['target_observations'].values()) >= 1
    assert saved['heartbeat_count'] >= 2
    assert saved['db_integrity'] == 'ok' and saved['unclosed_sessions'] == 0
    progress = json.loads((tmp_path / 'result.progress.json').read_text(encoding='utf-8'))
    assert progress['run_id'] == saved['run_id']
    with sqlite3.connect(tmp_path / 'data/history.sqlite3') as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 10
        assert db.execute('SELECT count(*) FROM sessions WHERE ended_at IS NULL').fetchone()[0] == 0


def test_soak_rejects_existing_data_without_modifying_it(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    original = b'preserve synthetic prior data'
    (data / 'settings.json').write_bytes(original)
    result = run_soak(tmp_path)
    assert result.returncode == 2
    assert 'SOAK_DATA_NOT_EMPTY' in result.stderr
    assert (data / 'settings.json').read_bytes() == original
    assert not (data / 'history.sqlite3').exists()


@pytest.mark.parametrize('duration', ['0', '-1', '86401'])
def test_soak_invalid_duration_never_creates_data(tmp_path, duration):
    result = run_soak(tmp_path, duration=duration)
    assert result.returncode == 2
    assert 'SOAK_DURATION_INVALID' in result.stderr
    assert not (tmp_path / 'data').exists()


def test_soak_reports_heartbeat_stall_instead_of_counting_suspended_time(qtbot, tmp_path):
    from aruba_client_live_tracker.soak import SoakMonitor
    from aruba_client_live_tracker.ui import MainWindow
    window = MainWindow(data_path=tmp_path / 'data', demo=True, multi=True)
    qtbot.addWidget(window)
    now = [0.0]
    outcomes = []
    monitor = SoakMonitor(window, 100, tmp_path / 'result.json',
                          lambda *values: outcomes.append(values), clock=lambda: now[0])
    now[0] = 16
    monitor.tick()
    assert len(outcomes) == 1
    assert outcomes[0][0:2] == (9, 'SOAK_HEARTBEAT_STALLED')
    assert outcomes[0][2]['max_heartbeat_gap_seconds'] == 16
    window.close()


def test_early_window_close_cannot_pass_timed_soak(tmp_path):
    code = '''
import sys
from PySide6.QtCore import QTimer
from aruba_client_live_tracker import main
original = main.MainWindow.show
def early_close(window):
    original(window)
    QTimer.singleShot(500, window.close)
main.MainWindow.show = early_close
raise SystemExit(main.main(['--multi-demo', '--soak-seconds', '10', '--data-dir', sys.argv[1],
                           '--smoke-result', sys.argv[2]]))
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'data'), str(tmp_path / 'result.json')],
                            capture_output=True, text=True, encoding='utf-8', timeout=15,
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'))
    assert result.returncode == 9, result.stderr
    saved = json.loads((tmp_path / 'result.json').read_text(encoding='utf-8'))
    assert not saved['success'] and saved['reason'].startswith('SOAK_INTERRUPTED')


def test_live_gui_heartbeat_cannot_hide_stalled_collection(qtbot, tmp_path):
    from aruba_client_live_tracker.demo import DEMO_CLIENTS
    from aruba_client_live_tracker.soak import SoakMonitor
    from aruba_client_live_tracker.ui import MainWindow
    window = MainWindow(data_path=tmp_path / 'data', demo=True, multi=True)
    qtbot.addWidget(window)
    window.scenario.setCurrentIndex(window.scenario.findData('normal'))
    window.interval.setCurrentIndex(window.interval.findData(10))
    window.add_many_targets('\n'.join(c.ip for c in DEMO_CLIENTS))
    window.start_all()
    qtbot.waitUntil(lambda: all(c.last_result is not None for c in window.coordinator.contexts.values()), timeout=5000)
    window.timer.stop()  # Simulate stalled scheduling while the Qt event loop still runs.
    now, outcomes = [0.0], []
    monitor = SoakMonitor(window, 100, tmp_path / 'result.json',
                          lambda *values: outcomes.append(values), clock=lambda: now[0])
    try:
        for value in (0, 10, 20, 31):
            now[0] = value
            monitor.tick()
        assert len(outcomes) == 1
        assert outcomes[0][0:2] == (9, 'SOAK_COLLECTION_STALLED')
    finally:
        window.close()


def diagnostic_database(tmp_path, count=1):
    from aruba_client_live_tracker.models import Event, Observation, Outcome, PollResult
    from aruba_client_live_tracker.storage import HistoryStore
    path = tmp_path / 'synthetic.db'
    started = datetime.now(timezone.utc).isoformat()
    with HistoryStore(path) as store:
        for index in range(10):
            session = store.start_session(f'192.0.2.{index + 100}', simulated=True)
            for _ in range(count):
                store.save_poll(session, PollResult(Outcome.OK, Observation(simulated=True)),
                                [Event('synthetic', 'synthetic')])
            store.end_session(session)
    return path, {'requested_seconds': 3, 'interval_seconds': 10, 'started_at': started,
                  'elapsed_seconds': 3}


def test_database_check_releases_its_read_handle(tmp_path):
    from aruba_client_live_tracker.soak import verify_soak_database
    path, metrics = diagnostic_database(tmp_path)
    verify_soak_database(path, metrics)
    path.unlink()  # Windows rejects deletion if the verification connection leaked.
    assert not path.exists()


def test_initial_burst_cannot_pass_a_later_stalled_run(tmp_path):
    from aruba_client_live_tracker.soak import verify_soak_database
    path, metrics = diagnostic_database(tmp_path, count=8)
    metrics.update(requested_seconds=100, elapsed_seconds=100)
    with pytest.raises(ValueError, match='SOAK_PERSISTENCE_STALLED'):
        verify_soak_database(path, metrics)
