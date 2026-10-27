"""Deterministic known-host reader/writer races; no network connection is made."""
from __future__ import annotations

import errno
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import paramiko
import pytest

from aruba_client_live_tracker import ssh
from aruba_client_live_tracker.models import Credentials, Device


class _BeforeNetwork(RuntimeError):
    """The preflight succeeded; stop before any DNS, TCP or authentication."""


class _NoNetworkClient:
    def __init__(self):
        self.connect_called = threading.Event()
        self.closed = False

    def set_missing_host_key_policy(self, _policy):
        pass

    def connect(self, **_kwargs):
        self.connect_called.set()
        raise _BeforeNetwork()

    def close(self):
        self.closed = True


@pytest.fixture
def preflight(tmp_path, monkeypatch):
    path = tmp_path / "known_hosts"
    key = paramiko.RSAKey.generate(1024)
    keys = paramiko.HostKeys()
    keys.add("192.0.2.1", key.get_name(), key)
    keys.save(str(path))
    client = _NoNetworkClient()
    reader_started = threading.Event()

    def client_factory():
        reader_started.set()
        return client

    monkeypatch.setattr(ssh.paramiko, "SSHClient", client_factory)
    session = ssh.SSHSession(Device("synthetic", "192.0.2.2", "MM_PRIMARY"),
                             Credentials("synthetic", "synthetic-secret"), path)
    yield session, client, key, reader_started
    session.close()


def _exclusive_windows_reader(path):
    """Use an actual Win32 share-denying handle, released before replacement."""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                     wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    handle = kernel32.CreateFileW(str(path), 0x80000000, 0, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())

    def close():
        if not kernel32.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    return close


def _hold_atomic_writer(monkeypatch, path, *, native_sharing_conflict=False):
    """Keep the real writer/lock active at the atomic replacement boundary."""
    entered, release = threading.Event(), threading.Event()
    replace = ssh.os.replace

    def held_replace(source, destination):
        if Path(destination) == path:
            close_handle = _exclusive_windows_reader(path) if native_sharing_conflict else lambda: None
            try:
                entered.set()
                assert release.wait(5), "synthetic atomic writer was not released"
            finally:
                close_handle()
        return replace(source, destination)

    monkeypatch.setattr(ssh.os, "replace", held_replace)
    return entered, release


@pytest.mark.parametrize("native_sharing_conflict", [False, True])
def test_preflight_waits_for_atomic_writer_instead_of_reporting_invalid_keys(preflight, monkeypatch,
                                                                          native_sharing_conflict):
    if native_sharing_conflict and os.name != "nt":
        pytest.skip("native Win32 sharing handle requires Windows")
    session, client, key, reader_started = preflight
    entered, release = _hold_atomic_writer(monkeypatch, session.known_hosts,
                                           native_sharing_conflict=native_sharing_conflict)
    with ThreadPoolExecutor(max_workers=2) as workers:
        writer = workers.submit(ssh._save_key, session.known_hosts, "192.0.2.3", key)
        try:
            assert entered.wait(2)
            reader = workers.submit(session.run, "show switches", deadline=time.monotonic() + 4)
            assert reader_started.wait(2)
            time.sleep(0.1)
            if reader.done():
                error = reader.exception()
                cause = getattr(error, "__cause__", None)
                pytest.fail(f"preflight completed inside atomic writer: "
                            f"{getattr(error, 'code', type(error).__name__)}; "
                            f"cause={type(cause).__name__}, errno={getattr(cause, 'errno', None)}")
            assert not client.connect_called.is_set()
        finally:
            release.set()
        writer.result(timeout=2)
        with pytest.raises(_BeforeNetwork):
            reader.result(timeout=2)
    assert client.connect_called.is_set()
    assert len(ssh._known_keys(session.known_hosts)) == 2


@pytest.mark.parametrize("interruption,expected", [("cancel", "CANCELLED"),
                                                   ("deadline", "HOST_KEY_TIMEOUT")])
def test_preflight_writer_wait_honors_cancellation_and_deadline(preflight, monkeypatch,
                                                              interruption, expected):
    session, client, key, reader_started = preflight
    entered, release = _hold_atomic_writer(monkeypatch, session.known_hosts)
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as workers:
        writer = workers.submit(ssh._save_key, session.known_hosts, "192.0.2.3", key)
        try:
            assert entered.wait(2)
            deadline = time.monotonic() + (0.3 if interruption == "deadline" else 4)
            reader = workers.submit(session.run, "show switches", cancel, deadline)
            assert reader_started.wait(2)
            if interruption == "cancel":
                cancel.set()
            with pytest.raises(ssh.SSHError) as caught:
                reader.result(timeout=2)
            assert caught.value.code == expected
            assert not client.connect_called.is_set()
            assert not release.is_set()  # Cancellation did not require writer release.
        finally:
            release.set()
        writer.result(timeout=2)
    assert len(ssh._known_keys(session.known_hosts)) == 2


@pytest.mark.parametrize("failure", ["corrupt", "permission"])
def test_preflight_real_file_errors_still_fail_closed_without_retry(preflight, monkeypatch, failure):
    session, client, _, _ = preflight
    if failure == "corrupt":
        session.known_hosts.write_bytes(b"synthetic malformed key record\n")
    read_bytes = Path.read_bytes
    preserved = read_bytes(session.known_hosts)
    reads = []

    def controlled_read(path):
        if path == session.known_hosts:
            reads.append(path)
            if failure == "permission":
                raise PermissionError(errno.EACCES, "synthetic denied file")
        return read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", controlled_read)
    with pytest.raises(ssh.SSHError) as caught:
        session.run("show switches", deadline=time.monotonic() + 3)
    assert caught.value.code == "KNOWN_HOSTS_INVALID"
    assert not caught.value.retryable
    assert not client.connect_called.is_set()
    assert reads == [session.known_hosts]
    assert read_bytes(session.known_hosts) == preserved


def test_readonly_sidecar_requirement_matches_existing_pinned_handshake(preflight, monkeypatch):
    session, client, key, _ = preflight
    preserved = session.known_hosts.read_bytes()
    lock_path = session.known_hosts.with_name("known_hosts.lock")
    open_file = ssh.os.open

    def readonly_sidecar(path, *args, **kwargs):
        if Path(path) == lock_path:
            raise PermissionError(errno.EACCES, "synthetic read-only sidecar")
        return open_file(path, *args, **kwargs)

    monkeypatch.setattr(ssh.os, "open", readonly_sidecar)
    # Even a matching pinned key already required this lock on every
    # handshake. Preflight now rejects the same unsupported path earlier.
    with pytest.raises(ssh.SSHError) as prior:
        ssh._save_key(session.known_hosts, "192.0.2.1", key)
    assert prior.value.code == "KNOWN_HOSTS_LOCK"
    with pytest.raises(ssh.SSHError) as current:
        session.run("show switches", deadline=time.monotonic() + 3)
    assert current.value.code == prior.value.code
    assert not client.connect_called.is_set()
    assert session.known_hosts.read_bytes() == preserved
