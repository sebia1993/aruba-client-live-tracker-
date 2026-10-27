"""Repeated loopback failures through coordinator, SQLite, pool and real Paramiko.

Aruba replies reuse the existing synthetic integration fixture. No real device,
external DNS, credentials, GUI timing simulation or modified parser is involved.
"""
from __future__ import annotations

import re
import socket
import sqlite3
import sys
import threading
import time
from contextlib import ExitStack, closing

import pytest
from test_commands_parsers import MAC
from test_live_ssh_integration import _LabSSH

from aruba_client_live_tracker.collector import LiveCollector
from aruba_client_live_tracker.models import Credentials, Device, Outcome
from aruba_client_live_tracker.monitoring import MonitoringCoordinator
from aruba_client_live_tracker.session_pool import SharedSessionPool
from aruba_client_live_tracker.storage import HistoryStore

ROUNDS = 20
OTHER_MAC = "02:00:00:00:00:02"
FALSE_CLIENT_EVENTS = {"disconnected", "reconnected", "roam"}


class FaultSSH(_LabSSH):
    """Same SSH implementation/replies, with explicit listener/response faults."""

    def __init__(self, role, mac=MAC):
        self.mac = mac
        self.fault = None
        self.fault_seen = threading.Event()
        self.release_response = threading.Event()
        super().__init__(role)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    def reply(self, command):
        return super().reply(command).replace(MAC, self.mac)

    def arm(self, fault):
        self.fault = fault
        self.fault_seen.clear()
        self.release_response.clear()

    def _send_reply(self, channel, command, prompt):
        if command.startswith("show user-table mac") and self.fault:
            fault, self.fault = self.fault, None
            self.fault_seen.set()
            if fault == "disconnect":
                channel.get_transport().close()
                return False
            assert fault == "silent"
            while not self.release_response.wait(0.01):
                if self.closed.is_set() or channel.closed or not channel.get_transport().is_active():
                    return False
        return super()._send_reply(channel, command, prompt)

    def halt_listener(self):
        self.listener.close()
        self.thread.join(2)
        assert not self.thread.is_alive()
        for transport in self.transports:
            transport.close()

    def restart_listener(self):
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", self.port))
        self.listener.listen(8)
        self.listener.settimeout(0.1)
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def close(self):
        self.release_response.set()
        super().close()


def wait_until(predicate, *, manager=None, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if manager is not None:
            manager.tick()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("loopback lifecycle did not reach the expected state")


class RecoveryRig:
    def __init__(self, tmp_path):
        self._cleanup = ExitStack()
        self.servers = []
        self.manager = None

        def collector(context):
            start = 0 if context.target.value == MAC else 2
            mm, md = self.servers[start:start + 2]
            devices = [Device("LAB-MM", "127.0.0.1", "MM_PRIMARY", mm.port),
                       Device("LAB-MD", "127.0.0.1", "MD", md.port, mappings=("192.0.2.20",))]
            return LiveCollector(devices, self.pool.credentials, self.pool.known_hosts,
                                 command_runner=self.pool.for_owner(context.id))

        stage = 'servers'
        try:
            for role, mac in (('MM', MAC), ('MD', MAC), ('MM', OTHER_MAC), ('MD', OTHER_MAC)):
                server = FaultSSH(role, mac)
                self._cleanup.callback(server.close)
                self.servers.append(server)
            self.bad = self.servers[1]
            stage = 'history'
            self.store = HistoryStore(tmp_path / "loopback-recovery.db")
            self._cleanup.callback(self.store.close)
            stage = 'pool'
            self.pool = SharedSessionPool(Credentials("synthetic", "synthetic-secret"),
                                          tmp_path / "known_hosts", max_connections=4, cooldown=0.25)
            self._cleanup.callback(self.pool.close)
            stage = 'coordinator'
            # Scheduling is manual; SSH timeout/cooldown uses real monotonic time.
            self.manager = MonitoringCoordinator(self.store, collector, clock=lambda: 0)
            self._cleanup.callback(self._close_manager)
            self.failing = self.manager.add(MAC)
            self.healthy = self.manager.add(OTHER_MAC)
            stage = 'start'
            self.manager.start_all()
            stage = 'initial_polls'
            wait_until(lambda: all(c.view for c in self.manager.contexts.values()), manager=self.manager)
            stage = 'initial_ok'
            assert all(c.last_result.outcome == Outcome.OK for c in self.manager.contexts.values())
        except BaseException as exc:
            # A fixture has not yielded yet: register each acquired resource
            # immediately and release all of them even if another close fails.
            cleanup_code = 'ok'
            try:
                self._cleanup.close()
            except Exception as cleanup_error:
                cleanup_code = type(cleanup_error).__name__
            if not isinstance(exc, Exception):
                raise
            diagnostics = self._setup_diagnostics()
            raise AssertionError(f'RECOVERY_SETUP_FAILED stage={stage} code={type(exc).__name__} '
                                 f'diagnostics={diagnostics} cleanup_code={cleanup_code}') from None

    def _setup_diagnostics(self):
        codes = set()
        if self.manager is not None:
            for context in self.manager.contexts.values():
                if context.last_result is None:
                    continue
                for diagnostic in context.last_result.diagnostics:
                    if (isinstance(diagnostic.stage, str) and isinstance(diagnostic.code, str)
                            and re.fullmatch(r'[a-z_]{1,32}', diagnostic.stage)
                            and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}', diagnostic.code)):
                        codes.add(f'{diagnostic.stage}:{diagnostic.code}')
        return ','.join(sorted(codes)[:16]) or 'none'

    def _close_manager(self):
        assert self.manager.close(wait=True), 'RECOVERY_CLEANUP_FAILED stage=coordinator'

    def batch(self):
        before = {identity: len(context.samples) for identity, context in self.manager.contexts.items()}
        self.manager.refresh_all()
        wait_until(lambda: all(len(c.samples) == before[i] + 1 for i, c in self.manager.contexts.items()),
                   manager=self.manager)
        assert self.manager.contexts[self.healthy].last_result.outcome == Outcome.OK
        assert self.manager.contexts[self.healthy].status == "running"
        return self.manager.contexts[self.failing].last_result

    def assert_resources(self):
        wait_until(lambda: all(sum(worker.is_alive() for worker in server.workers) <= 1
                               for server in self.servers))
        assert all(sum(transport.is_active() for transport in server.transports) <= 1
                   for server in self.servers)
        assert len(self.pool._entries) <= 4
        assert len(self.pool._runners) == 2
        assert sum(entry.session is not None for entry in self.pool._entries.values()) <= 4
        assert all(not entry.queue and entry.active is None and not entry.closing
                   for entry in self.pool._entries.values())
        assert len(self.manager._executor._threads) <= 2
        assert not self.manager.busy

    def close(self):
        try:
            started = time.monotonic()
            self._close_manager()
            self.pool.close()
            elapsed = time.monotonic() - started
            assert elapsed < 2, f"loopback shutdown took {elapsed:.3f}s"
            assert all(row["ended_at"] for row in self.store.sessions())
            assert not self.pool._runners
            assert all(entry.session is None and not entry.queue and entry.active is None
                       for entry in self.pool._entries.values())
            assert all(not thread.is_alive() for thread in self.manager._executor._threads)
        finally:
            self._cleanup.close()


@pytest.fixture
def rig(tmp_path, monkeypatch):
    # Bound a deliberately silent reused channel without changing initial
    # connection budget, parser behavior, collection cadence or production code.
    monkeypatch.setattr("aruba_client_live_tracker.ssh.COMMAND_TIMEOUT", 0.5)
    getaddrinfo = socket.getaddrinfo

    def loopback_only(host, port, *args, **kwargs):
        assert host == "127.0.0.1"
        return getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", loopback_only)
    value = RecoveryRig(tmp_path)
    try:
        yield value
    finally:
        value.close()


@pytest.fixture
def tracked_setup_resources(monkeypatch):
    """Keep independent handles so a RED cleanup test cannot itself leak resources."""
    resources = {name: [] for name in ('servers', 'history', 'pool', 'coordinator')}
    failure_stage = [None]
    module = sys.modules[__name__]
    for name, stage in (('FaultSSH', 'servers'), ('HistoryStore', 'history'),
                        ('SharedSessionPool', 'pool'), ('MonitoringCoordinator', 'coordinator')):
        constructor = getattr(module, name)

        def tracked(*args, _constructor=constructor, _stage=stage, **kwargs):
            if failure_stage[0] == _stage and (_stage != 'servers' or len(resources[_stage]) == 2):
                raise OSError('synthetic-private-path synthetic-secret')
            resource = _constructor(*args, **kwargs)
            resources[_stage].append(resource)
            return resource

        monkeypatch.setattr(module, name, tracked)
    try:
        yield resources, failure_stage
    finally:
        for manager in resources['coordinator']:
            manager.close(wait=True)
        for pool in resources['pool']:
            pool.close()
        for store in resources['history']:
            store.close()
        for server in resources['servers']:
            server.close()


def assert_setup_resources_released(resources):
    for server in resources['servers']:
        assert server.closed.is_set() and server.listener.fileno() == -1
        assert not server.thread.is_alive()
        assert all(not worker.is_alive() for worker in server.workers)
    assert all(store._closed for store in resources['history'])
    assert all(pool._closed for pool in resources['pool'])
    for manager in resources['coordinator']:
        assert manager._closed
        assert all(not thread.is_alive() for thread in manager._executor._threads)


@pytest.mark.parametrize('stage', ['servers', 'history', 'pool', 'coordinator', 'initial_ok'])
def test_failed_recovery_setup_releases_every_created_resource_and_reports_safe_stage(
    tmp_path, monkeypatch, tracked_setup_resources, stage,
):
    from aruba_client_live_tracker.models import Diagnostic, PollResult
    resources, failure_stage = tracked_setup_resources
    failure_stage[0] = stage

    def invalid_known_hosts(*args, **kwargs):
        return PollResult(Outcome.ERROR, error='synthetic-private-path synthetic-secret', diagnostics=[
            Diagnostic('host_key', 'KNOWN_HOSTS_INVALID', 'synthetic-private-path synthetic-secret'),
        ])

    monkeypatch.setattr(LiveCollector, 'poll', invalid_known_hosts)
    with pytest.raises(Exception) as failed:
        RecoveryRig(tmp_path)
    assert_setup_resources_released(resources)
    assert f'RECOVERY_SETUP_FAILED stage={stage}' in str(failed.value)
    assert 'synthetic-private-path' not in str(failed.value)
    assert 'synthetic-secret' not in str(failed.value)
    if stage == 'initial_ok':
        assert 'host_key:KNOWN_HOSTS_INVALID' in str(failed.value)
        with closing(sqlite3.connect((tmp_path / 'loopback-recovery.db').as_uri() + '?mode=ro', uri=True)) as db:
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 2
            assert db.execute('SELECT count(*) FROM sessions WHERE ended_at IS NULL').fetchone()[0] == 0


def test_recovery_teardown_assertion_still_closes_database_and_servers(
    tmp_path, monkeypatch, tracked_setup_resources,
):
    from aruba_client_live_tracker.models import Observation, PollResult
    resources, _ = tracked_setup_resources

    def successful_poll(self, target, **kwargs):
        return PollResult(Outcome.OK, Observation(mac=target.value, simulated=True))

    monkeypatch.setattr(LiveCollector, 'poll', successful_poll)
    value = RecoveryRig(tmp_path)
    monkeypatch.setattr(value.store, 'sessions', lambda: [{'ended_at': None}])
    with pytest.raises(AssertionError):
        value.close()
    assert_setup_resources_released(resources)


@pytest.mark.parametrize("fault", ["disconnect", "silent", "server_restart"])
def test_twenty_fault_recovery_rounds_preserve_healthy_client_and_bounded_resources(rig, fault):
    context = rig.manager.contexts[rig.failing]
    session = context.session_id
    healthy_auths = [server.auth_attempts for server in rig.servers[2:]]
    for _ in range(ROUNDS):
        if fault == "server_restart":
            rig.bad.halt_listener()
        else:
            rig.bad.arm(fault)
        result = rig.batch()
        assert result.outcome == Outcome.ERROR
        assert any(d.code in {"NETWORK", "CONNECTION_CLOSED", "TIMEOUT"} for d in result.diagnostics)
        if fault != "server_restart":
            assert rig.bad.fault_seen.is_set()
        if fault == "server_restart":
            rig.bad.restart_listener()
        # This immediate request observes the real shared cooldown, and the
        # other row must still finish normally in the same scheduler batch.
        result = rig.batch()
        # A healthy poll itself can consume the 250 ms cooldown. Assert either
        # explicit cooldown or completed recovery, never a fabricated absence.
        assert result.outcome == Outcome.OK or any(d.code == "COOLDOWN" for d in result.diagnostics)
        time.sleep(rig.pool.cooldown)
        assert rig.batch().outcome == Outcome.OK
        assert context.session_id == session
        assert not (FALSE_CLIENT_EVENTS & {event.kind for event in context.events})
        rig.assert_resources()
    assert rig.bad.auth_attempts >= ROUNDS + 1
    assert [server.auth_attempts for server in rig.servers[2:]] == healthy_auths
    events = rig.store.events(session)
    assert sum(event["kind"] == "collection_failed" for event in events) == ROUNDS
    assert sum(event["kind"] == "collection_recovered" for event in events) == ROUNDS
    assert not (FALSE_CLIENT_EVENTS & {event["kind"] for event in events})
    assert len(rig.store.observations(session)) == 1 + 3 * ROUNDS
    assert len(rig.store.observations(rig.manager.contexts[rig.healthy].session_id)) == 1 + 3 * ROUNDS


def test_twenty_inflight_stop_restart_rounds_discard_cancelled_result_and_end_sessions(rig):
    context = rig.manager.contexts[rig.failing]
    retired = []
    for _ in range(ROUNDS):
        old_collector, old_session = context.collector, context.session_id
        old_count = len(rig.store.observations(old_session))
        healthy_before = len(rig.manager.contexts[rig.healthy].samples)
        rig.bad.arm("silent")
        rig.manager.refresh_all()
        wait_until(lambda: rig.bad.fault_seen.is_set(), manager=rig.manager)
        assert context.in_flight
        rig.manager.stop(rig.failing)
        rig.manager.start(rig.failing)
        # Race an actual delayed server response with cancellation. Even if it
        # reaches the client before transport close, the retired generation
        # must never persist it or replace the new session's view.
        rig.bad.release_response.set()
        wait_until(lambda: context.collector is not old_collector and context.view is not None,
                   manager=rig.manager)
        assert context.last_result.outcome == Outcome.OK
        assert context.session_id != old_session
        assert len(rig.store.observations(old_session)) == old_count
        assert len(rig.store.observations(context.session_id)) == 1
        wait_until(lambda: len(rig.manager.contexts[rig.healthy].samples) == healthy_before + 1,
                   manager=rig.manager)
        retired.append((old_session, old_count))
        rig.assert_resources()
    assert len(rig.store.sessions()) == ROUNDS + 2
    assert all(len(rig.store.observations(session)) == count for session, count in retired)
    assert all(row["ended_at"] for row in rig.store.sessions() if row["id"] in {s for s, _ in retired})


def test_normal_shutdown_cancels_silent_real_channel_without_late_write(rig):
    context = rig.manager.contexts[rig.failing]
    session = context.session_id
    records = len(rig.store.observations(session))
    rig.bad.arm("silent")
    rig.manager.refresh(rig.failing)
    wait_until(lambda: rig.bad.fault_seen.is_set(), manager=rig.manager)
    started = time.monotonic()
    assert rig.manager.close(wait=True)
    assert time.monotonic() - started < 2
    assert len(rig.store.observations(session)) == records
    assert all(row["ended_at"] for row in rig.store.sessions())


def test_shared_real_cooldown_prevents_reconnect_until_elapsed_without_stopping_healthy_row(rig):
    rig.pool.cooldown = 2
    rig.bad.arm("disconnect")
    assert rig.batch().outcome == Outcome.ERROR
    authentication_count = rig.bad.auth_attempts
    result = rig.batch()
    assert result.outcome == Outcome.ERROR
    assert any(item.code == "COOLDOWN" for item in result.diagnostics)
    assert rig.bad.auth_attempts == authentication_count
    time.sleep(rig.pool.cooldown)
    assert rig.batch().outcome == Outcome.OK
    assert rig.bad.auth_attempts == authentication_count + 1
    rig.assert_resources()


def test_resolver_cancellation_remains_pending_until_deterministic_release(rig, monkeypatch):
    """Characterize an OS resolver boundary; this does NOT prove bounded DNS.

    A held getaddrinfo cannot be interrupted by closing Paramiko's not-yet
    connected client. The test supplies its release and checks cleanup after it.
    """
    entered, release = threading.Event(), threading.Event()
    getaddrinfo = socket.getaddrinfo
    mm_port = rig.servers[0].port

    def delayed_loopback_resolver(host, port, *args, **kwargs):
        if port == mm_port:
            entered.set()
            assert release.wait(5), "deterministic resolver was not released"
        return getaddrinfo(host, port, *args, **kwargs)

    rig.manager.stop(rig.failing)
    rig.manager.start(rig.failing)
    monkeypatch.setattr(socket, "getaddrinfo", delayed_loopback_resolver)
    try:
        wait_until(entered.is_set, manager=rig.manager)
        assert not rig.manager.close(wait=False)
        time.sleep(0.15)
        assert rig.manager.busy
        assert not rig.manager.close(wait=False)
    finally:
        release.set()
    assert rig.manager.close(wait=True)
    assert all(row["ended_at"] for row in rig.store.sessions())
