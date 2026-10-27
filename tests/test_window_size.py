"""Initial windows must leave native frame space on small/high-DPI screens."""
import pytest
from PySide6.QtCore import QRect

from aruba_client_live_tracker.ui import MainWindow


@pytest.mark.parametrize('multi', [False, True])
@pytest.mark.parametrize('width,height', [(1366, 720), (1280, 672), (1280, 680), (1536, 816), (910, 480)])
def test_initial_dashboard_fits_available_logical_screen(qtbot, tmp_path, monkeypatch, multi, width, height):
    class Screen:
        def availableGeometry(self):
            return QRect(0, 0, width, height)

    monkeypatch.setattr(MainWindow, 'screen', lambda self: Screen())
    window = MainWindow(data_path=tmp_path, demo=True, multi=multi)
    qtbot.addWidget(window)
    window.show()
    window.layout().activate()
    assert window.width() <= width - 32
    assert window.height() <= height - 64
    window.close()
