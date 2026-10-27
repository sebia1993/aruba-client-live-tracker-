import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from aruba_client_live_tracker.models import Observation, Outcome, PollResult
from aruba_client_live_tracker.ui import MainWindow, SignalChart


def test_demo_background_start_stop_restart(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.show()
    window.start_tracking()
    qtbot.waitUntil(lambda: window.last_result is not None, timeout=8000)
    assert window.last_result.outcome == Outcome.OK
    assert window.fields["mac"].text() == "02:00:00:00:00:01"
    assert "가상" in window.banner.text()
    assert window.store.sessions()
    first_session = window.session_id
    window.stop_tracking()
    qtbot.waitUntil(lambda: window.worker is None, timeout=5000)
    window.start_tracking()
    qtbot.waitUntil(lambda: window.last_result is not None, timeout=8000)
    assert window.session_id != first_session
    window.stop_tracking()
    qtbot.waitUntil(lambda: window.worker is None, timeout=5000)
    window.close()


def test_chart_keeps_bounded_history_and_gaps(qtbot):
    chart = SignalChart()
    qtbot.addWidget(chart)
    for _ in range(260):
        chart.append(Observation(snr=30, tx_rate=144, rx_rate=72))
    chart.append(None)
    assert len(chart.samples) == 240
    assert chart.samples[-1][1] is None


def test_invalid_target_never_starts_worker(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.query.setText("aa:bb;reload")
    window.start_tracking()
    assert window.worker is None
    assert window.session_id is None
    window.close()


def test_stale_results_do_not_clear_last_valid_values(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window._consume_result(PollResult(Outcome.OK, Observation(mac="02:00:00:00:00:01", snr=31)))
    window._consume_result(PollResult(Outcome.ERROR, error="MD 조회 실패"))
    assert window.fields["snr"].text().startswith("31")
    assert "이전 조회값" in window.connection_state.text()
    window.close()


def test_missing_metric_has_visible_age_and_chart_gap(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    initial = Observation(mac="02:00:00:00:00:01", ap_name="DEMO-AP-01", bssid="02:10:00:00:00:01", snr=31)
    window._consume_result(PollResult(Outcome.OK, initial))
    missing = Observation(mac=initial.mac, ap_name=initial.ap_name, bssid=initial.bssid, snr=None)
    window._consume_result(PollResult(Outcome.OK, missing))
    assert "이전 조회값" in window.fields["snr"].text()
    assert window.chart.samples[-1][1] is None
    window.close()


def test_no_overlapping_polls_and_cancelled_response_ignored(qtbot, tmp_path):
    import threading


    entered = threading.Event()
    released = threading.Event()

    class ControlledCollector:
        calls = 0
        closed = False

        def poll(self, target, selected_mac=None, cancel=None):
            self.calls += 1
            entered.set()
            released.wait(2)
            return PollResult(Outcome.OK, Observation(mac="02:00:00:00:00:01", snr=20))

        def close(self):
            self.closed = True

    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    collector = ControlledCollector()
    window.coordinator.collector_factory = lambda context: collector
    window.start_tracking()
    qtbot.waitUntil(entered.is_set, timeout=2000)
    for _ in range(20):
        window.refresh_now()
    assert collector.calls == 1
    window.stop_tracking()
    released.set()
    qtbot.waitUntil(lambda: not window.coordinator.busy, timeout=3000)
    assert window.last_result is None
    assert window.fields["snr"].text() == "확인 불가"
    assert collector.closed
    window.close()


def test_scroll_keeps_main_controls_accessible_at_small_window(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.resize(910, 512)  # Logical size near 1366x768 at 150% scaling.
    window.show()
    qtbot.wait(20)
    scroll = window.centralWidget()
    assert scroll.verticalScrollBar().maximum() > 0
    assert window.start_button.isVisible()
    scroll.ensureWidgetVisible(window.settings_button)
    assert scroll.verticalScrollBar().value() > 0
    window.close()


def test_demo_mode_selection_populates_empty_query(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=False)
    qtbot.addWidget(window)
    assert not window.query.text()
    window.mode.setCurrentIndex(0)
    assert window.query.text() == "192.0.2.100"
    window.close()


def test_cli_field_values_are_plain_text(qtbot, tmp_path):
    from PySide6.QtCore import Qt
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window._consume_result(PollResult(Outcome.OK, Observation(ssid="<b>DEMO</b>")))
    assert window.fields["ssid"].textFormat() == Qt.TextFormat.PlainText
    window.close()


def test_disconnected_observation_stores_normalized_absence(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.session_id = window.store.start_session("192.0.2.100", simulated=True)
    window._consume_result(PollResult(Outcome.OK, Observation(mac="02:00:00:00:00:01", connected=True)))
    window._consume_result(PollResult(Outcome.OK, Observation(mac="02:00:00:00:00:01", connected=False)))
    rows = window.store.observations(window.session_id)
    assert rows[-1]["outcome"] == Outcome.ABSENT
    assert rows[-1].get("connected") is None
    assert window.chart.samples[-1][1] is None
    window.close()


def test_ambiguous_choice_requires_explicit_button(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from aruba_client_live_tracker.models import Candidate
    calls = []
    class AmbiguousCollector:
        def poll(self, *args, **kwargs):
            return PollResult(Outcome.AMBIGUOUS, candidates=[
                Candidate("192.0.2.100", "02:00:00:00:00:01", "192.0.2.11"),
                Candidate("192.0.2.100", "02:00:00:00:00:02", "192.0.2.11")])
        def close(self):
            pass
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (calls.append(True) or "", False))
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.coordinator.collector_factory = lambda context: AmbiguousCollector()
    window.start_tracking()
    qtbot.waitUntil(lambda: window.last_result is not None, timeout=3000)
    context = window.coordinator.contexts[window.selected_id]
    assert context.status == "selection_required"
    assert context.next_due is None
    assert calls == []
    assert window.candidate_button.isEnabled()
    window.choose_candidate()
    assert calls == [True]
    window.stop_all()
    window.close()


def test_invalid_settings_file_opens_recoverable_gui(qtbot, tmp_path):
    (tmp_path / "settings.json").write_text("{invalid", encoding="utf-8")
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    assert window.devices == []
    assert "설정" in window.status_note.text()
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == "{invalid"
    window.close()


def test_multi_registration_selection_keeps_sessions_and_no_extra_poll(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True, multi=True)
    qtbot.addWidget(window)
    ids, errors = window.add_many_targets('192.0.2.100\n192.0.2.101\ninvalid\n192.0.2.100')
    assert len(ids) == 2 and len(errors) == 2
    window.start_all()
    qtbot.waitUntil(lambda: all(c.last_result is not None for c in window.coordinator.contexts.values()), timeout=8000)
    contexts = list(window.coordinator.contexts.values())
    sessions = [c.session_id for c in contexts]
    lengths = [len(c.samples) for c in contexts]
    window.targets_table.selectRow(1)
    qtbot.wait(150)
    assert window.selected_id == ids[1]
    assert [c.session_id for c in contexts] == sessions
    assert [len(c.samples) for c in contexts] == lengths
    assert window.fields['ip'].text() == '192.0.2.101'
    window.stop_all()
    qtbot.waitUntil(lambda: not window.coordinator.busy, timeout=5000)
    window.close()


def test_multi_cap_and_locked_settings(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True, multi=True)
    qtbot.addWidget(window)
    ids, errors = window.add_many_targets('\n'.join(f'192.0.2.{i}' for i in range(100,111)))
    assert len(ids) == 10 and len(errors) == 1
    window.start_all()
    assert not window.mode.isEnabled()
    assert not window.monitor_kind.isEnabled()
    assert not window.settings_button.isEnabled()
    window.stop_all()
    qtbot.waitUntil(lambda: not window.coordinator.busy, timeout=5000)
    window.close()


def test_no_host_approval_ui_or_signal_exists(qtbot, tmp_path):
    from aruba_client_live_tracker import ui_monitoring
    window = MainWindow(data_path=tmp_path, demo=False)
    qtbot.addWidget(window)
    assert not hasattr(ui_monitoring, 'HostApproval')
    assert not hasattr(window, 'host_key_requested')
    assert not hasattr(window, '_approval_queue')
    assert not hasattr(window, '_request_host_key')
    window.close()


def test_multi_demo_cli_smoke_verifies_every_target(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path
    project = Path(__file__).resolve().parents[1]
    result_path = tmp_path / 'result.json'
    env = dict(os.environ, PYTHONPATH=str(project / 'src'), QT_QPA_PLATFORM='offscreen')
    process = subprocess.run([sys.executable, '-m', 'aruba_client_live_tracker.main', '--multi-demo',
                              '--smoke-test', '--smoke-result', str(result_path)],
                             cwd=project, env=env, capture_output=True, text=True, timeout=35)
    assert process.returncode == 0, process.stdout + process.stderr + result_path.read_text(encoding="utf-8")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result['success'] and result['target_count'] == 10
    assert result['independent_macs'] == 10
    assert len(result['target_observations']) == 10
    assert min(result['target_observations'].values()) >= 5


def test_selected_status_and_storage_errors_remain_visible(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.start_tracking()
    qtbot.waitUntil(lambda: window.last_result is not None, timeout=3000)
    context = window.coordinator.contexts[window.selected_id]
    context.note = '이력 저장 실패: 저장 공간과 권한을 확인하세요.'
    window._tick()
    assert '이력 저장 실패' in window.status_note.text()
    window.stop_tracking()
    assert '중지' in window.connection_state.text()
    assert window.fields['mac'].text() == '02:00:00:00:00:01'
    window.close()


def test_selecting_unstarted_row_clears_context_labels(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True, multi=True)
    qtbot.addWidget(window)
    ids, _ = window.add_many_targets('192.0.2.100\n192.0.2.101')
    window.start_tracking()
    qtbot.waitUntil(lambda: window.last_result is not None, timeout=3000)
    window.targets_table.selectRow(1)
    assert window.selected_id == ids[1]
    assert window.mm_label.text() == 'MM · 대기'
    assert window.md_label.text() == 'MD · 대기'
    assert window.fields['mac'].text() == '확인 불가'
    assert '없음' in window.valid_time.text()
    assert not window.chart.samples
    headers = [window.targets_table.horizontalHeaderItem(i).text() for i in range(window.targets_table.columnCount())]
    assert '연결 상태' in headers and '담당 MD' in headers and '마지막 정상 시각' in headers
    window.stop_all()
    qtbot.waitUntil(lambda: not window.coordinator.busy, timeout=3000)
    window.close()


def test_first_live_connection_never_opens_key_dialog_and_credentials_reused(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from aruba_client_live_tracker import collector, session_pool
    from aruba_client_live_tracker.models import Credentials, Device

    class FakeSSH:
        def __init__(self, device, credentials, known_hosts, approve=None):
            self.device = device
            assert approve is None
        def run(self, command, cancel=None, deadline=None):
            return 'synthetic'
        def close(self):
            pass

    class FakeLive:
        def __init__(self, devices, credentials, known_hosts, command_runner=None):
            self.runner = command_runner
            self.device = devices[0]
        def poll(self, target, selected_mac=None, cancel=None):
            self.runner.run(self.device, 'show user-table', cancel=cancel)
            return PollResult(Outcome.OK, Observation(ip=target.value, mac=f'02:00:00:00:00:{int(target.value.split(".")[-1]):02x}'))
        def close(self):
            self.runner.close()

    def unexpected_dialog(*args, **kwargs):
        raise AssertionError('First SSH connection must never ask for host key approval')
    monkeypatch.setattr(QMessageBox, 'exec', unexpected_dialog)
    monkeypatch.setattr(QMessageBox, 'open', unexpected_dialog)
    monkeypatch.setattr(session_pool, 'SSHSession', FakeSSH)
    monkeypatch.setattr(collector, 'LiveCollector', FakeLive)
    window = MainWindow(data_path=tmp_path, demo=False, multi=True)
    qtbot.addWidget(window)
    window.devices = [Device('가상 SSH', '192.0.2.1', 'MM_PRIMARY')]
    requests = []
    credentials = Credentials('synthetic', 'synthetic')
    monkeypatch.setattr(window, '_credentials', lambda: requests.append(True) or credentials)
    ids, _ = window.add_many_targets('192.0.2.100\n192.0.2.101')
    window.start_all()
    qtbot.waitUntil(lambda: all(window.coordinator.contexts[i].last_result for i in ids), timeout=3000)
    assert requests == [True]
    assert all(window.coordinator.contexts[i].last_result.outcome == Outcome.OK for i in ids), [(window.coordinator.contexts[i].last_result, window.coordinator.contexts[i].note) for i in ids]
    window.stop_all()
    qtbot.waitUntil(lambda: not window.coordinator.busy, timeout=3000)
    window._tick()
    assert window.pool is None and window._credentials_value is credentials
    window.start_all()
    qtbot.waitUntil(lambda: all(window.coordinator.contexts[i].last_result for i in ids), timeout=3000)
    assert requests == [True]
    window.stop_all()
    qtbot.waitUntil(lambda: not window.coordinator.busy, timeout=3000)
    window.close()
    assert window._credentials_value is None


def test_session_start_failure_is_visible_and_other_rows_continue(qtbot, tmp_path, monkeypatch):
    window = MainWindow(data_path=tmp_path, demo=True, multi=True)
    qtbot.addWidget(window)
    ids, _ = window.add_many_targets('192.0.2.100\n192.0.2.101')
    start_session = window.store.start_session
    def fail_one(query, simulated=False):
        if query == '192.0.2.100':
            raise OSError('synthetic database unavailable')
        return start_session(query, simulated=simulated)
    monkeypatch.setattr(window.store, 'start_session', fail_one)
    window.start_all()
    qtbot.waitUntil(lambda: window.coordinator.contexts[ids[1]].last_result is not None, timeout=3000)
    assert window.coordinator.contexts[ids[0]].status == 'stopped'
    assert window.status_note.text() == window.coordinator.contexts[ids[0]].note
    assert '시작' in window.status_note.text() and '저장' in window.status_note.text()
    assert window.coordinator.contexts[ids[1]].last_result.outcome == Outcome.OK
    window.stop_all()
    window.close()


def test_removed_targets_release_large_poll_results(qtbot, tmp_path):
    class RawCollector:
        simulated = True
        def poll(self, target, **kwargs):
            return PollResult(Outcome.OK, Observation(mac='02:00:00:00:00:01'), raw={'synthetic': 'x'*100_000})
        def close(self):
            pass
    window = MainWindow(data_path=tmp_path, demo=True, multi=True)
    qtbot.addWidget(window)
    window.coordinator.collector_factory = lambda context: RawCollector()
    for _ in range(3):
        ids, _ = window.add_many_targets('192.0.2.100')
        window.start_tracking()
        qtbot.waitUntil(lambda: window.last_result is not None, timeout=3000)
        window.remove_selected()
        assert ids[0] not in window._emitted_results
        assert window.last_result is None
    window.close()
