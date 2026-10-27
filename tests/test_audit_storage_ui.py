import sqlite3

from aruba_client_live_tracker.storage import HistoryStore
from aruba_client_live_tracker.ui import HistoryDialog, MainWindow


def test_history_list_keeps_newest_session_after_five_hundred(qtbot, tmp_path):
    with HistoryStore(tmp_path / 'history.db') as store:
        for _ in range(501):
            store.start_session('192.0.2.100', simulated=True)

        dialog = HistoryDialog(store)
        qtbot.addWidget(dialog)
        visible = {int(dialog.grid.item(row, 0).text()) for row in range(dialog.grid.rowCount())}

        assert 501 in visible, 'The newest session must remain available for viewing and export.'
        assert visible == set(range(1, 502))
        assert dialog.grid.item(0, 0).text() == '501'


def test_selected_stop_remains_available_when_session_end_needs_retry(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    window.timer.stop()
    identifier = window.coordinator.add('192.0.2.100')
    window.selected_id = identifier
    window.coordinator.start(identifier)
    context = window.coordinator.contexts[identifier]
    session_id = context.session_id
    blocker = sqlite3.connect(window.store.path)
    try:
        blocker.execute('BEGIN IMMEDIATE')
        window.stop_tracking()

        assert context.session_id == session_id
        assert 'HISTORY_END_FAILED' in window.status_note.text()
        assert window.stop_button.isEnabled(), 'The advertised Stop retry must remain actionable.'

        blocker.rollback()
        window.stop_button.click()
        assert context.session_id is None
        assert window.store.sessions()[0]['ended_at'] is not None
        assert all(session['ended_at'] is not None for session in window.store.sessions())
        assert not window.stop_button.isEnabled()
    finally:
        blocker.rollback()
        blocker.close()
        window.close()
