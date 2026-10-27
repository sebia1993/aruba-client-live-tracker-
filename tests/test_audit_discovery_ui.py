"""Discovery worker cleanup must not detach a newer active operation."""
import threading

from aruba_client_live_tracker.discovery import DiscoveryResult
from aruba_client_live_tracker.models import Credentials, Device
from aruba_client_live_tracker.ui_discovery import DiscoveryDialog


def test_previous_worker_cleanup_keeps_current_probe_cancellable(qtbot, tmp_path):
    old_close_entered = threading.Event()
    old_close_release = threading.Event()
    probe_entered = threading.Event()
    probe_release = threading.Event()
    current_closed = threading.Event()
    old_worker = []
    services = []

    class Service:
        def __init__(self, credentials, known_hosts):
            self.first = not services
            services.append(self)

        def discover(self, seed, cancel):
            return DiscoveryResult(devices=[seed])

        def probe(self, devices, cancel):
            probe_entered.set()
            probe_release.wait(5)
            return DiscoveryResult(devices=devices)

        def close(self):
            if self.first:
                old_worker.append(threading.current_thread())
                old_close_entered.set()
                old_close_release.wait(5)
            else:
                current_closed.set()
                probe_release.set()

    dialog = DiscoveryDialog(Device('synthetic', '192.0.2.1', 'MM_PRIMARY'), [],
                             Credentials('synthetic', 'synthetic'), tmp_path / 'known_hosts',
                             service_factory=Service)
    qtbot.addWidget(dialog)
    try:
        qtbot.waitUntil(old_close_entered.is_set)
        qtbot.waitUntil(lambda: dialog.probe_button.isEnabled())
        dialog.probe_button.click()
        qtbot.waitUntil(probe_entered.is_set)
        old_close_release.set()
        old_worker[0].join(timeout=1)
        assert not old_worker[0].is_alive()
        dialog.reject()
        assert current_closed.wait(1), 'Cancel must close the current probe service.'
    finally:
        old_close_release.set()
        probe_release.set()
        dialog.reject()
