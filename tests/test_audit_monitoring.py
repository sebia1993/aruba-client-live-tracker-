"""Offline regression tests for monitoring lifecycle audit findings."""

import pytest
from test_collector import MD, MM, FakeSSH, global_output
from test_monitoring import Collector, settle

from aruba_client_live_tracker.collector import LiveCollector
from aruba_client_live_tracker.models import Credentials
from aruba_client_live_tracker.monitoring import MonitoringCoordinator
from aruba_client_live_tracker.session_pool import SharedSessionPool
from aruba_client_live_tracker.storage import HistoryStore


@pytest.mark.parametrize("first_result", ["older", "newer"])
def test_idle_duplicate_releases_collector_without_discarding_history(tmp_path, first_result):
    """A suppressed row must release its SSH ownership even without an active poll."""
    with HistoryStore(tmp_path / "history.db") as store:
        manager = MonitoringCoordinator(store, Collector)
        older = manager.add("192.0.2.100")
        newer = manager.add("02:00:00:00:00:01")
        order = [older, newer] if first_result == "older" else [newer, older]
        try:
            manager.start(order[0])
            settle(manager, lambda: manager.contexts[order[0]].view is not None)
            manager.start(order[1])
            duplicate_collector = manager.contexts[newer].collector
            duplicate_session = manager.contexts[newer].session_id
            settle(manager, lambda: manager.contexts[newer].status == "duplicate")

            assert manager.contexts[older].status == "running"
            assert not manager.contexts[newer].in_flight
            assert duplicate_collector.closed
            assert manager.contexts[newer].collector is None
            assert manager.contexts[newer].session_id == duplicate_session
            assert store.observations(duplicate_session)
        finally:
            manager.close(wait=True)


def test_duplicate_releases_shared_owner_and_can_restart_after_winner_stops(tmp_path, monkeypatch):
    class Transport(FakeSSH):
        instances = []
        failures = {}
        mm_output = global_output()

        def __init__(self, *args):
            super().__init__(*args)
            self.close_count = 0

        def close(self):
            super().close()
            self.close_count += 1

    monkeypatch.setattr("aruba_client_live_tracker.session_pool.SSHSession", Transport)
    credentials = Credentials("synthetic", "synthetic-password")
    pool = SharedSessionPool(credentials, tmp_path / "known_hosts")

    def factory(context):
        return LiveCollector(
            [MM, MD], credentials, tmp_path / "known_hosts",
            command_runner=pool.for_owner(context.id),
        )

    with HistoryStore(tmp_path / "history.db") as store:
        manager = MonitoringCoordinator(store, factory)
        winner = manager.add("192.0.2.100")
        duplicate = manager.add("02:00:00:00:00:01")
        try:
            manager.start(winner)
            settle(manager, lambda: manager.contexts[winner].view is not None)
            manager.start(duplicate)
            old_runner = manager.contexts[duplicate].collector._command_runner
            settle(manager, lambda: manager.contexts[duplicate].status == "duplicate")
            duplicate_context = manager.contexts[duplicate]
            previous_session = duplicate_context.session_id
            previous_view = duplicate_context.view
            previous_records = store.observations(previous_session)

            assert old_runner._closed
            assert duplicate not in pool._runners
            assert len(Transport.instances) == 2
            assert all(transport.close_count == 0 for transport in Transport.instances)

            manager.stop(duplicate)
            manager.stop(duplicate)
            assert duplicate_context.view is previous_view
            assert store.observations(previous_session) == previous_records
            assert all(transport.close_count == 0 for transport in Transport.instances)
            manager.stop(winner)
            assert all(transport.close_count == 1 for transport in Transport.instances)

            manager.start(duplicate)
            settle(manager, lambda: duplicate_context.view is not None)
            assert duplicate_context.status == "running"
            assert duplicate_context.session_id != previous_session
            assert duplicate_context.collector._command_runner is not old_runner
            assert len(Transport.instances) == 4
        finally:
            manager.close(wait=True)
            pool.close()
        assert all(transport.close_count == 1 for transport in Transport.instances)
