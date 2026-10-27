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

    from aruba_client_live_tracker.models import Target

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
    window.collector = collector
    window.target = Target("ip", "192.0.2.100")
    window.active = True
    window.refresh_now()
    qtbot.waitUntil(entered.is_set, timeout=2000)
    for _ in range(20):
        window.refresh_now()
    assert collector.calls == 1
    window.stop_tracking()
    released.set()
    qtbot.waitUntil(lambda: window.worker is None, timeout=3000)
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


def test_ambiguous_choice_suspends_background_scheduling(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from aruba_client_live_tracker.models import Candidate
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.active = True
    checked = []

    def choose(*args):
        checked.append(getattr(window, "selection_pending", False))
        assert window.next_due is None
        return "", False

    monkeypatch.setattr(QInputDialog, "getItem", choose)
    window._result_received(window.generation, PollResult(Outcome.AMBIGUOUS, candidates=[
        Candidate("192.0.2.100", "02:00:00:00:00:01", "192.0.2.11"),
        Candidate("192.0.2.100", "02:00:00:00:00:02", "192.0.2.11"),
    ]))
    assert checked == [True]
    assert window.paused
    assert not window.selection_pending
    window.close()


def test_invalid_settings_file_opens_recoverable_gui(qtbot, tmp_path):
    (tmp_path / "settings.json").write_text("{invalid", encoding="utf-8")
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    assert window.devices == []
    assert "설정" in window.status_note.text()
    assert (tmp_path / "settings.json").read_text(encoding="utf-8") == "{invalid"
    window.close()
