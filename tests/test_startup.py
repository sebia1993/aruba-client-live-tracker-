"""Startup and smoke failures use only temporary synthetic local data."""
import json
import os
import subprocess
import sys

import pytest


def run_smoke(tmp_path, *extra):
    environment = dict(os.environ, QT_QPA_PLATFORM='offscreen')
    try:
        return subprocess.run([
            sys.executable, '-m', 'aruba_client_live_tracker.main', '--demo', '--smoke-test',
            '--data-dir', str(tmp_path / 'data'), *map(str, extra),
        ], capture_output=True, text=True, timeout=10, env=environment)
    except subprocess.TimeoutExpired:
        pytest.fail('Smoke failure did not terminate within ten seconds')


def test_unusable_data_directory_reports_korean_startup_error(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from aruba_client_live_tracker import main
    bad_path = tmp_path / 'not-a-directory'
    bad_path.write_text('synthetic', encoding='utf-8')
    messages = []
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args: messages.append(args[1:]))
    assert main.main(['--data-dir', str(bad_path)]) != 0
    assert len(messages) == 1
    assert '시작' in messages[0][0] and '데이터' in messages[0][1]
    assert 'Traceback' not in messages[0][1]


def test_smoke_startup_failure_is_nonmodal_and_writes_failure(tmp_path):
    (tmp_path / 'data').write_text('synthetic', encoding='utf-8')
    report = tmp_path / 'failure.json'
    result = run_smoke(tmp_path, '--smoke-result', report)
    assert result.returncode != 0
    assert report.is_file()
    assert json.loads(report.read_text(encoding='utf-8'))['success'] is False
    assert 'Traceback' not in result.stderr


def test_smoke_result_write_failure_exits_nonzero(tmp_path):
    result = run_smoke(tmp_path, '--smoke-result', tmp_path)
    assert result.returncode != 0
    assert 'Traceback' not in result.stderr


def test_smoke_screenshot_directory_failure_exits_nonzero(tmp_path):
    obstruction = tmp_path / 'not-a-directory'
    obstruction.write_text('synthetic', encoding='utf-8')
    report = tmp_path / 'failure.json'
    result = run_smoke(tmp_path, '--screenshot', obstruction / 'capture.png', '--smoke-result', report)
    assert result.returncode != 0
    assert json.loads(report.read_text(encoding='utf-8'))['success'] is False
    assert 'Traceback' not in result.stderr


@pytest.mark.parametrize('method', ['end_session', 'close'])
def test_smoke_shutdown_storage_failure_cannot_report_success(tmp_path, method):
    report = tmp_path / 'result.json'
    code = '''
import sqlite3
import sys
from aruba_client_live_tracker.storage import HistoryStore
from aruba_client_live_tracker.main import main
def fail(*args, **kwargs):
    raise sqlite3.OperationalError('synthetic shutdown failure')
setattr(HistoryStore, sys.argv[1], fail)
raise SystemExit(main(['--demo', '--smoke-test', '--data-dir', sys.argv[2], '--smoke-result', sys.argv[3]]))
'''
    result = subprocess.run([sys.executable, '-c', code, method, str(tmp_path / 'data'), str(report)],
                            capture_output=True, text=True, encoding='utf-8', timeout=15,
                            env=dict(os.environ, QT_QPA_PLATFORM='offscreen', PYTHONUTF8='1'))
    assert result.returncode != 0
    saved = json.loads(report.read_text(encoding='utf-8'))
    assert saved['success'] is False
    assert 'HISTORY_SHUTDOWN_FAILED' in saved['reason']
    assert 'synthetic shutdown failure' not in saved['reason']
