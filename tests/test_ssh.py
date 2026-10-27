"""Synthetic SSH transport tests; no network equipment or secrets."""
from __future__ import annotations

import base64
import hashlib
import threading
from collections import deque
from pathlib import Path

import paramiko
import pytest

from aruba_client_live_tracker.models import Credentials, Device
from aruba_client_live_tracker.ssh import SSHError, SSHSession, fingerprint_sha256


@pytest.fixture
def key():
    return paramiko.RSAKey.generate(1024)


class Channel:
    def __init__(self, response="Total entries = 0\r\n(lab) #"):
        self.pending = deque([b"Synthetic test CLI\r\n(lab) #"])
        self.sent = []
        self.closed = False
        self.response = response

    def settimeout(self, timeout):
        pass

    def recv_ready(self):
        return bool(self.pending)

    def recv(self, size):
        return self.pending.popleft()

    def sendall(self, value):
        self.sent.append(value)
        if value == " ":
            self.pending.append(b"\r\n(lab) #")
        else:
            self.pending.append((value + self.response).encode())

    def close(self):
        self.closed = True


class Client:
    def __init__(self, key, channel=None):
        self.host_keys = paramiko.HostKeys()
        self.key = key
        self.channel = channel or Channel()
        self.authenticated = False
        self.closed = False

    def load_host_keys(self, filename):
        self.host_keys.load(filename)

    def set_missing_host_key_policy(self, policy):
        self.policy = policy

    def connect(self, hostname, port, **kwargs):
        host = hostname if port == 22 else f"[{hostname}]:{port}"
        known = self.host_keys.lookup(host)
        if known:
            expected = next(iter(known.values()))
            if expected != self.key:
                raise paramiko.BadHostKeyException(hostname, self.key, expected)
        else:
            self.policy.missing_host_key(self, host, self.key)
        self.authenticated = True

    def get_host_keys(self):
        return self.host_keys

    def get_transport(self):
        return self

    def is_active(self):
        return not self.closed

    def invoke_shell(self, **kwargs):
        return self.channel

    def close(self):
        self.closed = True
        self.channel.close()


@pytest.fixture
def make(monkeypatch, tmp_path, key):
    clients = []

    def factory(*, approval=True, channel=None, server_key=None):
        client = Client(server_key or key, channel)
        clients.append(client)
        monkeypatch.setattr(paramiko, "SSHClient", lambda: client)
        calls = []

        def approve(device, algorithm, fingerprint):
            calls.append((device, algorithm, fingerprint))
            return approval

        session = SSHSession(Device("MM example", "192.0.2.10", "MM_PRIMARY"),
                             Credentials("synthetic", "synthetic-secret"),
                             tmp_path / "known_hosts", approve)
        return session, client, calls

    return factory


def test_sha256_fingerprint(key):
    assert fingerprint_sha256(key) == "SHA256:" + base64.b64encode(
        hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def test_first_use_requires_approval_before_authentication(make):
    session, client, calls = make(approval=False)
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "HOST_KEY_REJECTED"
    assert not caught.value.retryable
    assert not client.authenticated
    assert len(calls) == 1


def test_approved_key_persisted_and_reused(make, tmp_path):
    session, client, calls = make()
    assert "Total entries = 0" in session.run('show global-user-table list ip "192.0.2.100"')
    assert session.run('show global-user-table list ip "192.0.2.100"')
    assert len(calls) == 1
    assert Path(tmp_path / "known_hosts").exists()
    session.close()
    assert client.closed


def test_changed_key_cannot_be_reapproved(make, tmp_path, key):
    keys = paramiko.HostKeys()
    keys.add("192.0.2.10", key.get_name(), key)
    keys.save(str(tmp_path / "known_hosts"))
    session, client, calls = make(server_key=paramiko.RSAKey.generate(1024))
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "HOST_KEY_CHANGED"
    assert not caught.value.retryable
    assert not client.authenticated
    assert calls == []


def test_command_injection_denied_before_connect(make):
    session, client, calls = make()
    with pytest.raises((ValueError, SSHError)):
        session.run("show user-table mac aa:bb:cc:dd:ee:ff\nreload")
    assert not client.authenticated
    assert not calls


def test_output_limit_closes_connection(make, monkeypatch):
    monkeypatch.setattr("aruba_client_live_tracker.ssh.MAX_OUTPUT_BYTES", 100)
    session, client, _ = make(channel=Channel("x" * 200 + "\r\n(lab) #"))
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "OUTPUT_LIMIT"
    assert client.closed


def test_cancelled_run_does_not_connect(make):
    session, client, calls = make()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"', cancel=cancel)
    assert caught.value.code == "CANCELLED"
    assert not client.authenticated


def test_pagination_sends_only_space(make):
    session, client, _ = make(channel=Channel("row 1\r\n--More--"))
    output = session.run('show global-user-table list ip "192.0.2.100"')
    assert "row 1" in output
    assert client.channel.sent == ['show global-user-table list ip "192.0.2.100"\n', " "]


def test_known_key_reconnect_skips_approval(make):
    first, _, first_calls = make()
    first.run('show global-user-table list ip "192.0.2.100"')
    first.close()
    second, second_client, second_calls = make(approval=False)
    second.run('show global-user-table list ip "192.0.2.100"')
    assert len(first_calls) == 1
    assert second_client.authenticated
    assert second_calls == []
    second.close()


def test_deadline_stops_unresponsive_session(make, monkeypatch):
    monkeypatch.setattr("aruba_client_live_tracker.ssh.INITIAL_CONNECTION_TIMEOUT", 0.04)
    session, client, _ = make()
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "TIMEOUT"
    assert caught.value.retryable
    assert client.closed


def test_authentication_error_is_not_failover_eligible(make, monkeypatch):
    session, client, _ = make()

    def authentication_failure(**kwargs):
        raise paramiko.AuthenticationException("do not expose username or password")

    monkeypatch.setattr(client, "connect", authentication_failure)
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "AUTH_FAILED"
    assert not caught.value.retryable
    assert "username" not in str(caught.value)
    assert client.closed


@pytest.mark.parametrize("prompt", ["(LAB-MM) *[mynode] #", "(LAB-MM) ^*[mynode] #", "(LAB-MM) [mynode] #"])
def test_hierarchy_prompt_markers(make, monkeypatch, prompt):
    monkeypatch.setattr("aruba_client_live_tracker.ssh.COMMAND_TIMEOUT", 0.2)
    channel = Channel("Total entries = 0\r\n" + prompt)
    channel.pending = deque([("Synthetic CLI\r\n" + prompt).encode()])
    session, _, _ = make(channel=channel)
    assert session.run('show global-user-table list ip "192.0.2.100"').strip() == "Total entries = 0"
    session.close()


@pytest.mark.parametrize("answer, expected", [(False, "HOST_KEY_REJECTED"), (True, "HOST_KEY_APPROVAL_TIMEOUT")])
def test_late_host_key_answer_is_never_network_failover(make, key, monkeypatch, answer, expected):
    from aruba_client_live_tracker.ssh import _ApprovalPolicy

    session, client, _ = make()
    clock = [0.0]
    monkeypatch.setattr("aruba_client_live_tracker.ssh.time.monotonic", lambda: clock[0])

    def late_answer(device, algorithm, fingerprint):
        clock[0] = 5.0
        return answer

    session.approve_host_key = late_answer
    with pytest.raises(SSHError) as caught:
        _ApprovalPolicy(session, None, 2.0).missing_host_key(client, "192.0.2.10", key)
    assert caught.value.code == expected
    assert caught.value.retryable is False
    assert not session.known_hosts.exists()


def test_host_key_dialog_receives_transport_deadline(make, key, monkeypatch):
    from aruba_client_live_tracker.ssh import _ApprovalPolicy

    session, client, _ = make()
    monkeypatch.setattr("aruba_client_live_tracker.ssh.time.monotonic", lambda: 0.0)
    deadlines = []

    def approval(device, algorithm, fingerprint, deadline):
        deadlines.append(deadline)
        return False

    session.approve_host_key = approval
    with pytest.raises(SSHError):
        _ApprovalPolicy(session, None, 12.0).missing_host_key(client, "192.0.2.10", key)
    assert deadlines == [12.0]


def test_host_key_callback_receives_exact_operation_cancel(make, key, monkeypatch):
    from aruba_client_live_tracker.ssh import _ApprovalPolicy

    session, client, _ = make()
    monkeypatch.setattr('aruba_client_live_tracker.ssh.time.monotonic', lambda: 0.0)
    cancel = threading.Event()
    calls = []

    def approval(device, algorithm, fingerprint, deadline, operation_cancel):
        calls.append((deadline, operation_cancel))
        return False

    session.approve_host_key = approval
    with pytest.raises(SSHError) as caught:
        _ApprovalPolicy(session, cancel, 12.0).missing_host_key(client, '192.0.2.10', key)
    assert caught.value.code == 'HOST_KEY_REJECTED'
    assert calls == [(12.0, cancel)]
