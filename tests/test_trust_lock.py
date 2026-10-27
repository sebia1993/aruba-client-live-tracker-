"""Cross-process TOFU races use synthetic keys, never network connections."""
from __future__ import annotations

import base64
import multiprocessing
import threading
import time
from pathlib import Path

import paramiko
import pytest

from aruba_client_live_tracker.ssh import SSHError, _save_key


def _save_worker(path, host, encoded, ready, start, results):
    key = paramiko.RSAKey(data=base64.b64decode(encoded))
    ready.put(True)
    start.wait(10)
    try:
        _save_key(Path(path), host, key, deadline=time.monotonic() + 10)
    except SSHError as exc:
        results.put(exc.code)
    else:
        results.put('saved')


def _hold_lock(path, entered, release):
    from aruba_client_live_tracker.ssh import _trust_lock
    with _trust_lock(Path(path), None, time.monotonic() + 10):
        entered.set()
        release.wait(10)


@pytest.mark.parametrize('conflict', [False, True])
def test_concurrent_processes_preserve_both_keys_or_block_conflict(tmp_path, conflict):
    context = multiprocessing.get_context('spawn')
    ready, results, start = context.Queue(), context.Queue(), context.Event()
    path = tmp_path / 'known_hosts'
    keys = [paramiko.RSAKey.generate(1024) for _ in range(2)]
    hosts = ['192.0.2.10', '192.0.2.10' if conflict else '192.0.2.20']
    processes = [context.Process(target=_save_worker, args=(str(path), host, key.get_base64(), ready, start, results))
                 for host, key in zip(hosts, keys, strict=True)]
    try:
        for process in processes:
            process.start()
        for _ in processes:
            ready.get(timeout=10)
        start.set()
        outcomes = [results.get(timeout=10) for _ in processes]
        assert sorted(outcomes) == (['HOST_KEY_CHANGED', 'saved'] if conflict else ['saved', 'saved'])
        stored = paramiko.HostKeys(str(path))
        assert len(stored) == (1 if conflict else 2)
        for host, key in zip(hosts, keys, strict=True):
            if not conflict:
                assert stored.lookup(host)[key.get_name()] == key
        if conflict:
            assert stored.lookup(hosts[0])[keys[0].get_name()] in keys
    finally:
        start.set()
        for process in processes:
            process.join(timeout=10)
            if process.is_alive():
                process.terminate()
                process.join()
        ready.close()
        results.close()
    assert all(process.exitcode == 0 for process in processes)


@pytest.mark.parametrize('cancelled, code', [(False, 'HOST_KEY_TIMEOUT'), (True, 'CANCELLED')])
def test_process_lock_wait_is_bounded_and_cancellable(tmp_path, cancelled, code):
    from test_ssh import Client

    from aruba_client_live_tracker.models import Credentials, Device
    from aruba_client_live_tracker.ssh import SSHSession, _TOFUPolicy

    context = multiprocessing.get_context('spawn')
    entered, release = context.Event(), context.Event()
    path = tmp_path / 'known_hosts'
    holder = context.Process(target=_hold_lock, args=(str(path), entered, release))
    holder.start()
    timer = None
    try:
        assert entered.wait(10)
        cancel = threading.Event()
        if cancelled:
            timer = threading.Timer(0.05, cancel.set)
            timer.start()
        key = paramiko.RSAKey.generate(1024)
        client = Client(key)
        session = SSHSession(Device('MM', '192.0.2.10'), Credentials('user', 'secret'), path)
        started = time.monotonic()
        with pytest.raises(SSHError) as caught:
            _TOFUPolicy(session, cancel, started + (3 if cancelled else 0.1)).missing_host_key(client, '192.0.2.10', key)
        assert caught.value.code == code
        assert not caught.value.retryable
        assert time.monotonic() - started < 1
        assert not path.exists()
        assert not client.authenticated
    finally:
        if timer:
            timer.cancel()
        release.set()
        holder.join(timeout=10)
        if holder.is_alive():
            holder.terminate()
            holder.join()
    assert holder.exitcode == 0


def test_pin_is_idempotent_and_preserves_existing_bytes_and_ports(tmp_path):
    path = tmp_path / 'known_hosts'
    key = paramiko.RSAKey.generate(1024)
    first = '# Preserve comments and existing keys\n192.0.2.10 ' + key.get_name() + ' ' + key.get_base64() + '\n'
    path.write_text(first)
    _save_key(path, '192.0.2.10', key)
    assert path.read_text() == first
    other = paramiko.RSAKey.generate(1024)
    _save_key(path, '[192.0.2.10]:2222', other)
    assert path.read_text().startswith(first)
    keys = paramiko.HostKeys(str(path))
    assert keys.lookup('192.0.2.10')[key.get_name()] == key
    assert keys.lookup('[192.0.2.10]:2222')[other.get_name()] == other


def test_invalid_lock_storage_errors_are_nonretryable(tmp_path):
    from aruba_client_live_tracker.ssh import _trust_lock
    path = tmp_path / 'known_hosts'
    path.with_name('known_hosts.lock').mkdir()
    with pytest.raises(SSHError) as caught:
        with _trust_lock(path, None, time.monotonic() + 1):
            pytest.fail('invalid lock was accepted')
    assert caught.value.code == 'KNOWN_HOSTS_LOCK'
    assert not caught.value.retryable


def test_hashed_existing_key_is_reused_and_preserved(tmp_path):
    path = tmp_path / 'known_hosts'
    key = paramiko.RSAKey.generate(1024)
    known = paramiko.HostKeys()
    known.add(paramiko.HostKeys.hash_host('192.0.2.10'), key.get_name(), key)
    known.save(str(path))
    original = path.read_bytes()
    _save_key(path, '192.0.2.10', key)
    assert path.read_bytes() == original
    _save_key(path, '192.0.2.20', paramiko.RSAKey.generate(1024))
    assert path.read_bytes().startswith(original)
