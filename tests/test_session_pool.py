"""Exercise the real pool with deterministic synthetic SSH transports."""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko
import pytest

from aruba_client_live_tracker.models import Credentials, Device
from aruba_client_live_tracker.ssh import SSHError

DEVICE = Device('MM', '192.0.2.10', 'MM_PRIMARY')
COMMAND = 'show global-user-table list ip "192.0.2.100"'


class Transport:
    instances = []
    entered = []
    gate = None
    failure = None
    approve = False

    def __init__(self, device, credentials, known_hosts, approval):
        self.device = device
        self.approve_host_key = approval
        self.closed = False
        self.instances.append(self)

    def run(self, command, cancel=None, deadline=None):
        self.entered.append(command)
        if self.approve:
            self.approve_host_key(self.device, 'ssh-ed25519', 'SHA256:synthetic', deadline, cancel)
        if self.gate is not None and command == 'first':
            while not self.gate.wait(0.005):
                if cancel.is_set():
                    raise SSHError('CANCELLED', 'cancelled')
        if self.failure:
            raise self.failure
        return command

    def close(self):
        self.closed = True


@pytest.fixture
def pool(monkeypatch, tmp_path):
    from aruba_client_live_tracker.session_pool import SharedSessionPool

    Transport.instances = []
    Transport.entered = []
    Transport.gate = None
    Transport.failure = None
    Transport.approve = False
    monkeypatch.setattr('aruba_client_live_tracker.session_pool.SSHSession', Transport)
    value = SharedSessionPool(Credentials('synthetic', 'secret'), tmp_path / 'known_hosts', None)
    yield value
    value.close()


def until(predicate):
    deadline = time.monotonic() + 2
    while not predicate():
        assert time.monotonic() < deadline, 'worker did not reach expected state'
        time.sleep(0.005)


def test_shared_reuse_and_last_owner_close(pool):
    one, two = pool.for_owner('one'), pool.for_owner('two')
    assert one.run(DEVICE, COMMAND) == COMMAND
    two.run(DEVICE, COMMAND)
    assert len(Transport.instances) == 1
    one.close()
    assert not Transport.instances[0].closed
    two.close()
    assert Transport.instances[0].closed


def test_fifo_per_device_and_cancel_queued_does_not_close_active(pool):
    runners = [pool.for_owner(str(i)) for i in range(4)]
    Transport.gate = threading.Event()
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=4) as workers:
        first = workers.submit(runners[0].run, DEVICE, 'first')
        until(lambda: Transport.entered == ['first'])
        second = workers.submit(runners[1].run, DEVICE, 'second', cancel)
        until(lambda: len(pool._entries[(DEVICE.host, DEVICE.port)].queue) == 1)
        third = workers.submit(runners[2].run, DEVICE, 'third')
        until(lambda: len(pool._entries[(DEVICE.host, DEVICE.port)].queue) == 2)
        fourth = workers.submit(runners[3].run, DEVICE, 'fourth')
        cancel.set()
        with pytest.raises(SSHError, match='취소'):
            second.result(timeout=2)
        assert not Transport.instances[0].closed
        Transport.gate.set()
        assert first.result(timeout=2) == 'first'
        assert third.result(timeout=2) == 'third'
        assert fourth.result(timeout=2) == 'fourth'
    assert Transport.entered == ['first', 'third', 'fourth']


def test_active_owner_close_cancels_only_it_and_next_reconnects(pool):
    one, two = pool.for_owner('one'), pool.for_owner('two')
    Transport.gate = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(one.run, DEVICE, 'first')
        until(lambda: bool(Transport.entered))
        second = workers.submit(two.run, DEVICE, 'second')
        one.close()
        with pytest.raises(SSHError) as caught:
            first.result(timeout=2)
        assert caught.value.code == 'CANCELLED'
        assert second.result(timeout=2) == 'second'
    assert Transport.instances[0].closed
    assert len(Transport.instances) == 2


def test_md_change_preserves_other_owner_interest(pool):
    old, new = Device('old', '192.0.2.20'), Device('new', '192.0.2.21')
    one, two = pool.for_owner('one'), pool.for_owner('two')
    one.run(old, COMMAND)
    two.run(old, COMMAND)
    one.run(new, COMMAND)
    assert not Transport.instances[0].closed
    two.close()
    assert Transport.instances[0].closed
    assert not Transport.instances[1].closed


def test_retryable_failure_enters_fast_cooldown(pool):
    owner = pool.for_owner('one')
    Transport.failure = SSHError('NETWORK', 'network', retryable=True)
    with pytest.raises(SSHError):
        owner.run(DEVICE, COMMAND)
    Transport.failure = None
    started = time.monotonic()
    with pytest.raises(SSHError) as caught:
        pool.for_owner('two').run(DEVICE, COMMAND)
    assert caught.value.code == 'COOLDOWN' and caught.value.retryable
    assert time.monotonic() - started < 0.1
    assert len(Transport.instances) == 1


@pytest.mark.parametrize('code', ['HOST_KEY_CHANGED', 'HOST_KEY_REJECTED', 'AUTH_FAILED'])
def test_security_failures_are_not_cooldown_or_retryable(pool, code):
    owner = pool.for_owner('one')
    Transport.failure = SSHError(code, 'security failure')
    with pytest.raises(SSHError) as caught:
        owner.run(DEVICE, COMMAND)
    assert not caught.value.retryable
    Transport.failure = None
    assert owner.run(DEVICE, COMMAND) == COMMAND


def test_pool_never_passes_approval_callback_to_transport(pool):
    calls = []
    pool.approve_host_key = lambda *args: calls.append(args) or True
    pool.for_owner('one').run(DEVICE, COMMAND)
    assert Transport.instances[0].approve_host_key is None
    assert calls == []


def test_auto_device_never_mutates_tracing_slots(pool):
    runner = pool.for_owner('one')
    runner.run(DEVICE, COMMAND)
    entries, slots = dict(pool._entries), dict(runner._slots)
    with pytest.raises(SSHError) as caught:
        runner.run(Device('Unknown', '192.0.2.99', 'AUTO'), COMMAND)
    assert caught.value.code == 'DEVICE_TYPE_UNKNOWN'
    assert pool._entries == entries
    assert runner._slots == slots
    assert len(Transport.instances) == 1
    assert not Transport.instances[0].closed


def test_connection_cap_evicts_idle_connections_and_is_bounded(pool):
    owners = [pool.for_owner(str(i)) for i in range(13)]
    for index, owner in enumerate(owners):
        owner.run(Device(str(index), f'192.0.2.{index + 1}'), COMMAND)
        assert sum(not item.closed for item in Transport.instances) <= 12
    assert len(Transport.instances) == 13


def test_queue_deadline_and_closed_owner_never_execute(pool):
    one, two = pool.for_owner('one'), pool.for_owner('two')
    Transport.gate = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(one.run, DEVICE, 'first')
        until(lambda: bool(Transport.entered))
        with pytest.raises(SSHError) as caught:
            two.run(DEVICE, 'second', deadline=time.monotonic() + 0.03)
        assert caught.value.code == 'TIMEOUT'
        Transport.gate.set()
        first.result(timeout=2)
    two.close()
    with pytest.raises(SSHError):
        two.run(DEVICE, COMMAND)
    assert Transport.entered == ['first']


def test_capacity_wait_is_cancellable_without_closing_other_endpoint(pool):
    pool.max_connections = 1
    one, two = pool.for_owner('one'), pool.for_owner('two')
    Transport.gate = threading.Event()
    cancel = threading.Event()
    other_device = Device('other', '192.0.2.30')
    with ThreadPoolExecutor(max_workers=2) as workers:
        first = workers.submit(one.run, DEVICE, 'first')
        until(lambda: bool(Transport.entered))
        second = workers.submit(two.run, other_device, 'second', cancel)
        until(lambda: (other_device.host, other_device.port) in pool._entries)
        cancel.set()
        with pytest.raises(SSHError) as caught:
            second.result(timeout=2)
        assert caught.value.code == 'CANCELLED'
        assert len(Transport.instances) == 1 and not Transport.instances[0].closed
        Transport.gate.set()
        assert first.result(timeout=2) == 'first'


def test_drop_race_with_other_active_owner_keeps_transport_alive(pool):
    one, two = pool.for_owner('one'), pool.for_owner('two')
    one.run(DEVICE, COMMAND)
    Transport.gate = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as workers:
        running = workers.submit(two.run, DEVICE, 'first')
        until(lambda: Transport.entered[-1] == 'first')
        one.drop(DEVICE)
        one.close()
        assert not Transport.instances[0].closed
        Transport.gate.set()
        assert running.result(timeout=2) == 'first'
    two.close()
    assert Transport.instances[0].closed


def test_pool_close_cancels_active_and_queued_requests_without_reconnect(pool):
    one, two = pool.for_owner('one'), pool.for_owner('two')
    Transport.gate = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        active = workers.submit(one.run, DEVICE, 'first')
        until(lambda: bool(Transport.entered))
        queued = workers.submit(two.run, DEVICE, 'second')
        until(lambda: bool(pool._entries[(DEVICE.host, DEVICE.port)].queue))
        pool.close()
        pool.close()
        for future in (active, queued):
            with pytest.raises(SSHError) as caught:
                future.result(timeout=2)
            assert caught.value.code == 'CANCELLED'
    assert Transport.entered == ['first']
    assert Transport.instances[0].closed


def test_closed_owner_can_restart_with_new_scoped_runner(pool):
    first = pool.for_owner('one')
    first.run(DEVICE, COMMAND)
    first.close()
    second = pool.for_owner('one')
    assert second is not first
    assert second.run(DEVICE, COMMAND) == COMMAND
    first.close()
    assert not Transport.instances[-1].closed


def test_cooldown_is_shared_after_failed_owner_drops_and_can_expire(pool):
    first = pool.for_owner('one')
    Transport.failure = SSHError('NETWORK', 'network', retryable=True)
    with pytest.raises(SSHError):
        first.run(DEVICE, COMMAND)
    first.drop(DEVICE)
    first.close()
    assert pool._entries[(DEVICE.host, DEVICE.port)].retry_at > time.monotonic() + 14
    second = pool.for_owner('two')
    with pytest.raises(SSHError) as caught:
        second.run(DEVICE, COMMAND)
    assert caught.value.code == 'COOLDOWN'
    Transport.failure = None
    pool._entries[(DEVICE.host, DEVICE.port)].retry_at = time.monotonic() - 1
    assert second.run(DEVICE, COMMAND) == COMMAND


def test_real_pool_auto_pins_without_callback(pool, monkeypatch):
    import paramiko
    from test_ssh import Client

    from aruba_client_live_tracker.ssh import SSHSession

    monkeypatch.setattr('aruba_client_live_tracker.session_pool.SSHSession', SSHSession)
    client = Client(paramiko.RSAKey.generate(1024))
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    calls = []
    pool.approve_host_key = lambda *args: calls.append(args) or False
    result = pool.for_owner('one').run(DEVICE, COMMAND)
    assert 'Total entries = 0' in result
    assert client.authenticated
    assert pool.known_hosts.exists()
    assert calls == []


def test_closed_owner_registry_stays_bounded_over_1000_lifetimes(pool):
    constant = pool.for_owner('constant')
    constant.run(DEVICE, COMMAND)
    for index in range(1000):
        temporary = pool.for_owner(f'temporary-{index}')
        temporary.run(DEVICE, COMMAND)
        temporary.close()
    assert pool._runners == {'constant': constant}
    assert len(Transport.instances) == 1
    assert not Transport.instances[0].closed
    assert constant.run(DEVICE, COMMAND) == COMMAND


def test_old_runner_close_does_not_unregister_new_lifetime(pool):
    old = pool.for_owner('restart')
    old.close()
    new = pool.for_owner('restart')
    old.close()
    assert pool.for_owner('restart') is new
    assert new.run(DEVICE, COMMAND) == COMMAND


def test_ten_collectors_1000_rounds_keep_shared_sessions_and_metadata_bounded(pool, monkeypatch):
    from test_commands_parsers import global_output

    from aruba_client_live_tracker.collector import LiveCollector
    from aruba_client_live_tracker.commands import global_user_command, parse_target, validate_command
    from aruba_client_live_tracker.models import Outcome

    targets = [parse_target(f'02:00:00:00:00:{index + 1:02x}') for index in range(10)]
    mds = [Device(f'MD-{index}', f'198.51.100.{index + 1}') for index in range(10)]
    responses = {
        global_user_command(target): global_output([
            [f'192.0.2.{100 + index}', target.value, '', md.host, 'synthetic', '', '']
        ]) for index, (target, md) in enumerate(zip(targets, mds, strict=True))
    }
    transports = []

    class PipelineSSH:
        def __init__(self, device, *_):
            self.device = device
            self.closed = False
            self.calls = 0
            transports.append(self)

        def run(self, command, **kwargs):
            validate_command(command)
            self.calls += 1
            if command in responses:
                return responses[command]
            if command.startswith('show user-table mac '):
                return f'IP: 192.0.2.100, MAC: {command[-17:]}, Role: synthetic'
            return '% Invalid input'

        def close(self):
            self.closed = True

    monkeypatch.setattr('aruba_client_live_tracker.session_pool.SSHSession', PipelineSSH)
    collectors = [LiveCollector([DEVICE, *mds], pool.credentials, pool.known_hosts,
                                command_runner=pool.for_owner(f'target-{index}')) for index in range(10)]
    try:
        for _ in range(1000):
            for collector, target in zip(collectors, targets, strict=True):
                result = collector.poll(target)
                assert result.outcome == Outcome.OK
                assert result.observation.mac == target.value
            assert len(pool._runners) == 10
            assert len(pool._entries) == 11
        assert len(transports) == 11
        assert not any(session.closed for session in transports)
        assert sum(session.calls for session in transports) >= 40000
        for collector in collectors:
            assert len(collector._history_at) == 1
            assert len(collector._history_raw) <= 3
        for collector in collectors[:-1]:
            collector.close()
        assert len(pool._runners) == 1
        assert not transports[0].closed
    finally:
        for collector in collectors:
            collector.close()
    assert not pool._runners
    assert all(session.closed for session in transports)


def test_slow_owner_close_does_not_block_other_endpoint(pool, monkeypatch):
    one, two = pool.for_owner('one'), pool.for_owner('two')
    other = Device('other', '192.0.2.30')
    one.run(DEVICE, COMMAND)
    two.run(other, COMMAND)
    closing, finish_close = threading.Event(), threading.Event()
    original_close = Transport.instances[0].close

    def slow_close():
        closing.set()
        assert finish_close.wait(2), 'test did not release transport shutdown'
        original_close()

    monkeypatch.setattr(Transport.instances[0], 'close', slow_close)
    with ThreadPoolExecutor(max_workers=2) as workers:
        shutdown = workers.submit(one.close)
        assert closing.wait(1)
        try:
            independent = workers.submit(two.run, other, COMMAND)
            assert independent.result(timeout=0.5) == COMMAND
        finally:
            finish_close.set()
            shutdown.result(timeout=1)


def test_eviction_counts_closing_connection_without_blocking_other_endpoint(pool, monkeypatch):
    pool.max_connections = 2
    one, two, three = [pool.for_owner(name) for name in ('one', 'two', 'three')]
    other, new = Device('other', '192.0.2.30'), Device('new', '192.0.2.31')
    one.run(DEVICE, COMMAND)
    two.run(other, COMMAND)
    closing, finish_close = threading.Event(), threading.Event()
    original_close = Transport.instances[0].close

    def slow_close():
        closing.set()
        assert finish_close.wait(2), 'test did not release transport shutdown'
        original_close()

    monkeypatch.setattr(Transport.instances[0], 'close', slow_close)
    with ThreadPoolExecutor(max_workers=2) as workers:
        waiting = workers.submit(three.run, new, COMMAND)
        assert closing.wait(1)
        try:
            independent = workers.submit(two.run, other, COMMAND)
            assert independent.result(timeout=0.5) == COMMAND
            assert not waiting.done()
            assert sum(not transport.closed for transport in Transport.instances) == 2
        finally:
            finish_close.set()
        assert waiting.result(timeout=1) == COMMAND
    assert sum(not transport.closed for transport in Transport.instances) == 2


def test_close_failure_preserves_primary_command_error(pool, monkeypatch):
    owner = pool.for_owner('one')
    owner.run(DEVICE, COMMAND)
    failure = SSHError('NETWORK', 'primary command error', retryable=True)
    Transport.failure = failure

    def failing_close():
        raise paramiko.SSHException('synthetic shutdown failure')

    with monkeypatch.context() as patch:
        patch.setattr(Transport.instances[0], 'close', failing_close)
        with pytest.raises(SSHError) as caught:
            owner.run(DEVICE, COMMAND)
        assert caught.value is failure


def test_close_failure_does_not_leave_endpoint_busy(pool, monkeypatch):
    pool.cooldown = 0
    owner = pool.for_owner('one')
    owner.run(DEVICE, COMMAND)

    def failing_close():
        raise paramiko.SSHException('synthetic shutdown failure')

    with monkeypatch.context() as patch:
        patch.setattr(Transport.instances[0], 'close', failing_close)
        Transport.failure = SSHError('NETWORK', 'primary command error', retryable=True)
        try:
            owner.run(DEVICE, COMMAND)
        except (SSHError, paramiko.SSHException):
            pass
    Transport.failure = None
    assert owner.run(DEVICE, COMMAND, deadline=time.monotonic() + 0.2) == COMMAND
