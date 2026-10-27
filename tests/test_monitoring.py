import queue
import threading
import time

import pytest

from aruba_client_live_tracker.models import Candidate, Observation, Outcome, PollResult
from aruba_client_live_tracker.monitoring import MonitoringCoordinator
from aruba_client_live_tracker.storage import HistoryStore


class Collector:
    def __init__(self, context):
        self.context = context
        self.closed = False
        self.calls = 0
        self.gate = None
        self.result = None

    def poll(self, target, selected_mac=None, cancel=None):
        self.calls += 1
        if self.gate:
            self.gate.wait(2)
        if self.result:
            return self.result
        suffix = (
            int(target.value.rsplit(".", 1)[-1]) - 99 if target.kind == "ip" else int(target.value[-2:], 16)
        )
        return PollResult(
            Outcome.OK,
            Observation(
                ip=f"192.0.2.{99 + suffix}",
                mac=selected_mac or f"02:00:00:00:00:{suffix:02x}",
                snr=20 + suffix,
                simulated=True,
            ),
        )

    def close(self):
        self.closed = True


@pytest.fixture
def manager(tmp_path):
    store = HistoryStore(tmp_path / "history.db")
    value = MonitoringCoordinator(store, Collector)
    yield value
    value.close(wait=True)
    store.close()


def settle(manager, predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        manager.tick()
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("coordinator did not reach expected state")


def test_independent_targets_results_and_sqlite_sessions(manager):
    ids = [manager.add(f"192.0.2.{n}") for n in range(100, 110)]
    manager.start_all()
    settle(manager, lambda: all(manager.contexts[i].view for i in ids))
    assert len({manager.contexts[i].session_id for i in ids}) == 10
    for n, identity in enumerate(ids, 1):
        context = manager.contexts[identity]
        assert context.view.observation.mac.endswith(f"{n:02x}")
        rows = manager.store.observations(context.session_id)
        assert {r["mac"] for r in rows} == {context.view.observation.mac}
    assert len(manager.store.sessions()) == 10


def test_duplicate_normalization_capacity_and_partial_input(manager):
    first = manager.add("02-00-00-00-00-01")
    with pytest.raises(ValueError):
        manager.add("0200.0000.0001")
    ids, errors = manager.add_many("192.0.2.101\nbad\n192.0.2.102")
    assert len(ids) == 2 and errors[0][0] == 2
    for n in range(103, 110):
        manager.add(f"192.0.2.{n}")
    with pytest.raises(ValueError):
        manager.add("192.0.2.110")
    assert manager.contexts[first].target.value == "02:00:00:00:00:01"


def test_two_worker_bound_refresh_coalesces_and_stop_discards_late_result(manager):
    ids = [manager.add(f"192.0.2.{n}") for n in range(100, 103)]
    gate = threading.Event()
    for identity in ids:
        manager.start(identity)
        manager.contexts[identity].collector.gate = gate
    manager.tick()
    assert sum(c.in_flight for c in manager.contexts.values()) == 2
    old = manager.contexts[ids[0]].collector
    manager.refresh(ids[0])
    manager.refresh(ids[0])
    manager.stop(ids[0])
    gate.set()
    settle(manager, lambda: not manager.busy)
    assert manager.contexts[ids[0]].view is None and old.closed
    assert old.calls == 1
    assert manager.contexts[ids[2]].view is not None


def test_ambiguous_only_pauses_own_row_and_explicit_selection(manager):
    one, two = manager.add("192.0.2.100"), manager.add("192.0.2.101")
    manager.start_all()
    context = manager.contexts[one]
    candidate = Candidate("192.0.2.100", "02:00:00:00:00:01", "192.0.2.20")
    context.collector.result = PollResult(Outcome.AMBIGUOUS, candidates=[candidate])
    settle(manager, lambda: context.status == "selection_required" and manager.contexts[two].view)
    assert manager.contexts[two].status == "running"
    context.collector.result = None
    manager.select_candidate(one, candidate.mac)
    settle(manager, lambda: context.view and context.view.state == "연결됨")
    assert context.selected_mac == candidate.mac


def test_same_resolved_mac_does_not_merge_histories(manager):
    one, two = manager.add("192.0.2.100"), manager.add("0200.0000.0001")
    manager.start_all()
    settle(manager, lambda: manager.contexts[two].status == "duplicate")
    assert manager.contexts[one].status == "running"
    assert manager.contexts[one].session_id != manager.contexts[two].session_id
    assert not any(row.get("mac") for row in manager.store.observations(manager.contexts[two].session_id))


def test_paused_removed_and_restarted_rows_do_not_affect_others(manager):
    one, two = manager.add("192.0.2.100"), manager.add("192.0.2.101")
    manager.start_all()
    settle(manager, lambda: all(c.view for c in manager.contexts.values()))
    first_session = manager.contexts[one].session_id
    manager.pause(one)
    manager.refresh(two)
    settle(manager, lambda: len(manager.contexts[two].samples) == 2)
    assert len(manager.contexts[one].samples) == 1
    manager.stop(one)
    manager.start(one)
    settle(manager, lambda: manager.contexts[one].view is not None)
    assert manager.contexts[one].session_id != first_session
    manager.remove(two)
    assert two not in manager.contexts and manager.contexts[one].status == "running"


def test_restart_during_inflight_waits_and_late_result_cannot_win(manager):
    identity = manager.add("192.0.2.100")
    manager.start(identity)
    context = manager.contexts[identity]
    old = context.collector
    old.gate = threading.Event()
    manager.tick()
    manager.stop(identity)
    manager.start(identity)
    old.gate.set()
    settle(manager, lambda: context.collector is not old and context.view is not None)
    assert old.closed and context.status == "running"


def test_storage_failure_is_visible_and_other_rows_continue(manager, monkeypatch):
    ids = [manager.add(f"192.0.2.{n}") for n in (100, 101)]
    original = manager.store.save_poll
    manager.start_all()
    first = manager.contexts[ids[0]].session_id

    def fail_one(session, *args):
        if session == first:
            raise OSError("synthetic disk failure")
        return original(session, *args)

    monkeypatch.setattr(manager.store, "save_poll", fail_one)
    settle(manager, lambda: all(c.view for c in manager.contexts.values()))
    assert "저장" in manager.contexts[ids[0]].note
    assert manager.store.observations(manager.contexts[ids[1]].session_id)


def test_oldest_registered_target_wins_even_when_newer_resolves_first(manager):
    first = manager.add("192.0.2.100")
    second = manager.add("02:00:00:00:00:01")
    manager.start_all()
    gate = threading.Event()
    manager.contexts[first].collector.gate = gate
    settle(manager, lambda: manager.contexts[second].view is not None)
    assert manager.contexts[second].status == "running"
    gate.set()
    settle(manager, lambda: manager.contexts[second].status == "duplicate")
    assert manager.contexts[first].status == "running"
    records = len(manager.store.observations(manager.contexts[second].session_id))
    manager.refresh_all()
    settle(manager, lambda: len(manager.contexts[first].samples) == 2)
    assert len(manager.store.observations(manager.contexts[second].session_id)) == records


def test_paused_manual_refresh_is_once_and_remains_paused(manager):
    identity = manager.add("192.0.2.100")
    manager.start(identity)
    settle(manager, lambda: manager.contexts[identity].view is not None)
    manager.pause(identity)
    manager.refresh(identity)
    settle(manager, lambda: len(manager.contexts[identity].samples) == 2)
    assert manager.contexts[identity].status == "paused"
    assert manager.contexts[identity].next_due is None


def test_ten_clients_300_rounds_bound_buffers_and_preserve_fairness(tmp_path):
    from aruba_client_live_tracker.demo import DemoCollector

    clock = [0.0]
    store = HistoryStore(tmp_path / "soak.db")
    coordinator = MonitoringCoordinator(
        store, lambda context: DemoCollector("normal"), clock=lambda: clock[0]
    )
    identities = [coordinator.add(f"192.0.2.{number}") for number in range(100, 110)]
    coordinator.start_all()
    counts = {identity: 0 for identity in identities}
    last = {}
    try:
        # This is a sample-count/fairness soak, not a disk-throughput benchmark.
        # Every iteration must make progress; a stuck worker has its own timeout.
        for _ in range(300 * len(identities) + 1):
            coordinator.tick()
            assert sum(c.in_flight for c in coordinator.contexts.values()) <= 2
            for identity, context in coordinator.contexts.items():
                if context.last_result is not None and last.get(identity) is not context.last_result:
                    last[identity] = context.last_result
                    counts[identity] += 1
                    if counts[identity] == 300:
                        coordinator.pause(identity)
            assert max(counts.values()) - min(counts.values()) <= 1
            if min(counts.values()) >= 300:
                break
            pending = tuple(coordinator._inflight.values())
            assert pending, f"scheduler stalled before completing all rounds: {counts}"
            # Wait for real worker callbacks, then leave their records queued for
            # tick() to apply normally (including real SQLite persistence). Waiting
            # only on Future.result() can race the callback that enqueues the work.
            completed = []
            try:
                for _work in pending:
                    completed.append(coordinator._completed.get(timeout=10))
            except queue.Empty:
                pytest.fail(f"poll worker stalled before completing a batch: {counts}")
            finally:
                for work in completed:
                    coordinator._completed.put(work)
            assert {id(work) for work in completed} == {id(work) for work in pending}
            clock[0] += 15
        assert min(counts.values()) >= 300
        assert max(counts.values()) <= 301
        assert all(len(c.samples) == 240 and len(c.events) <= 500 for c in coordinator.contexts.values())
        sessions = [c.session_id for c in coordinator.contexts.values()]
        coordinator.close(wait=True)
        assert all(len(store.observations(session)) >= 300 for session in sessions)
        assert all(row["ended_at"] for row in store.sessions())
    finally:
        coordinator.close(wait=True)
        store.close()


def test_start_storage_failure_stays_local_and_other_targets_start(manager, monkeypatch):
    first, second = manager.add("192.0.2.100"), manager.add("192.0.2.101")
    original = manager.store.start_session

    def fail_first(query, simulated=False):
        if query == "192.0.2.100":
            raise OSError("synthetic failure")
        return original(query, simulated=simulated)

    monkeypatch.setattr(manager.store, "start_session", fail_first)
    manager.start_all()
    settle(manager, lambda: manager.contexts[second].view is not None)
    assert manager.contexts[first].status == "stopped"
    assert "저장" in manager.contexts[first].note
    assert manager.contexts[first].collector is None
    assert manager.store.observations(manager.contexts[second].session_id)


@pytest.mark.parametrize("retire", ["stop", "remove"])
def test_dormant_duplicate_cannot_block_new_owner_after_winner_retires(manager, retire):
    first = manager.add("192.0.2.100")
    duplicate = manager.add("02:00:00:00:00:01")
    manager.start_all()
    settle(manager, lambda: manager.contexts[duplicate].status == "duplicate")
    getattr(manager, retire)(first)

    third = manager.add("192.0.2.101")
    manager.start(third)
    current = manager.contexts[third]
    current.collector.result = PollResult(Outcome.OK, Observation(mac="02:00:00:00:00:01"))
    settle(manager, lambda: current.view is not None)

    assert current.status == "running"
    assert current.view.result.outcome == Outcome.OK
    assert manager.contexts[duplicate].status == "duplicate"
    assert manager.store.observations(current.session_id)[-1]["mac"] == "02:00:00:00:00:01"

    # A dormant row takes ownership only after an explicit restart and fresh result.
    previous_session = manager.contexts[duplicate].session_id
    manager.resume(duplicate)
    settle(manager, lambda: current.status == "duplicate")
    assert manager.contexts[duplicate].status == "running"
    assert manager.contexts[duplicate].session_id != previous_session


@pytest.mark.parametrize("owner_state", ["running", "paused", "selection_required"])
def test_active_owner_keeps_mac_claim_while_paused_or_awaiting_selection(manager, owner_state):
    first = manager.add("192.0.2.100")
    manager.start(first)
    owner = manager.contexts[first]
    settle(manager, lambda: owner.view is not None)
    if owner_state == "paused":
        manager.pause(first)
    elif owner_state == "selection_required":
        owner.collector.result = PollResult(Outcome.AMBIGUOUS, candidates=[
            Candidate("192.0.2.100", "02:00:00:00:00:01", "192.0.2.20")
        ])
        manager.refresh(first)
        settle(manager, lambda: owner.status == "selection_required")

    second = manager.add("02:00:00:00:00:01")
    manager.start(second)
    settle(manager, lambda: manager.contexts[second].view is not None)
    assert owner.status == owner_state
    assert manager.contexts[second].status == "duplicate"


def test_duplicate_with_inflight_poll_discards_late_result_and_releases_collector(manager):
    first = manager.add("192.0.2.100")
    second = manager.add("02:00:00:00:00:01")
    manager.start_all()
    first_gate = threading.Event()
    second_gate = threading.Event()
    owner = manager.contexts[first]
    newer = manager.contexts[second]
    owner.collector.gate = first_gate
    try:
        settle(manager, lambda: newer.view is not None)
        newer_collector = newer.collector
        newer_collector.gate = second_gate
        manager.refresh(second)
        manager.tick()
        assert newer.in_flight and owner.in_flight
        records = len(manager.store.observations(newer.session_id))

        first_gate.set()
        settle(manager, lambda: newer.status == "duplicate")
        assert newer.cancel.is_set()
        second_gate.set()
        settle(manager, lambda: not manager.busy)

        assert owner.status == "running"
        assert newer.status == "duplicate" and newer.collector is None
        assert newer_collector.closed
        assert len(manager.store.observations(newer.session_id)) == records
        assert len(newer.samples) == 1
    finally:
        first_gate.set()
        second_gate.set()
