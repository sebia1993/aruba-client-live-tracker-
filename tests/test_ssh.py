"""Synthetic SSH transport tests; no network equipment or secrets."""
from __future__ import annotations

import base64
import hashlib
import threading
import time
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
        self.before_auth = None

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
        if self.before_auth is not None:
            self.before_auth()
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


def test_first_use_auto_pins_before_authentication_without_callback(make):
    session, client, calls = make(approval=False)

    def before_auth():
        assert not client.authenticated
        keys = paramiko.HostKeys(str(session.known_hosts))
        assert keys.lookup("192.0.2.10")[client.key.get_name()] == client.key

    client.before_auth = before_auth
    assert "Total entries = 0" in session.run('show global-user-table list ip "192.0.2.100"')
    assert client.authenticated
    assert calls == []
    session.close()


def test_auto_pinned_key_persisted_and_reused(make, tmp_path):
    session, client, calls = make()
    assert "Total entries = 0" in session.run('show global-user-table list ip "192.0.2.100"')
    original = session.known_hosts.read_bytes()
    assert session.run('show global-user-table list ip "192.0.2.100"')
    assert calls == []
    assert Path(tmp_path / "known_hosts").exists()
    assert session.known_hosts.read_bytes() == original
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
    assert first_calls == []
    assert second_client.authenticated
    assert second_calls == []
    second.close()


def test_deadline_stops_unresponsive_session(make, monkeypatch):
    session, client, _ = make()
    command = 'show global-user-table list ip "192.0.2.100"'
    session.run(command)  # Complete TOFU, authentication and initial prompt first.
    assert client.authenticated
    client.channel.response = "Waiting for a CLI response without a prompt"

    class Clock:
        now = 100.0

        def monotonic(self):
            return self.now

        def sleep(self, duration):
            self.now += duration

    # Advance only the SSH read loop's clock; disk speed and thread scheduling
    # cannot consume this command's budget during an earlier connection stage.
    monkeypatch.setattr("aruba_client_live_tracker.ssh.time", Clock())
    monkeypatch.setattr("aruba_client_live_tracker.ssh.COMMAND_TIMEOUT", 1.0)
    with pytest.raises(SSHError) as caught:
        session.run(command)
    assert client.channel.sent == [command + "\n", command + "\n"]
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


@pytest.mark.parametrize("cancelled, expected", [(False, "HOST_KEY_TIMEOUT"), (True, "CANCELLED")])
def test_host_key_cancel_and_expiry_never_authenticate_or_call_approval(make, key, cancelled, expected):
    from aruba_client_live_tracker.ssh import _TOFUPolicy

    session, client, calls = make()
    cancel = threading.Event()
    if cancelled:
        cancel.set()
    with pytest.raises(SSHError) as caught:
        _TOFUPolicy(session, cancel, time.monotonic() - 1).missing_host_key(client, "192.0.2.10", key)
    assert caught.value.code == expected
    assert not caught.value.retryable
    assert not session.known_hosts.exists()
    assert not client.authenticated
    assert calls == []


def test_constructor_without_approval_callback(tmp_path):
    session = SSHSession(Device("MM", "192.0.2.10"), Credentials("user", "secret"), tmp_path / "known_hosts")
    assert session.approve_host_key is None


@pytest.mark.parametrize("contents", ["malformed", "192.0.2.10 ssh-rsa not-base64!", "bad-hash"])
def test_invalid_store_blocks_authentication(make, contents):
    session, client, calls = make()
    if contents == "bad-hash":
        contents = "|1|invalid|invalid " + client.key.get_name() + " " + client.key.get_base64()
    session.known_hosts.write_text(contents)
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "KNOWN_HOSTS_INVALID"
    assert not caught.value.retryable
    assert not client.authenticated
    assert not calls


def test_storage_failure_blocks_authentication_and_preserves_store(make, key, monkeypatch):
    session, client, calls = make()
    old = paramiko.HostKeys()
    old.add("192.0.2.20", key.get_name(), key)
    old.save(str(session.known_hosts))
    contents = session.known_hosts.read_bytes()
    def fail_replace(*args):
        raise OSError("secret path must not leak")
    monkeypatch.setattr("aruba_client_live_tracker.ssh.os.replace", fail_replace)
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "KNOWN_HOSTS_WRITE"
    assert not caught.value.retryable
    assert not client.authenticated
    assert not calls
    assert "secret" not in str(caught.value)
    assert session.known_hosts.read_bytes() == contents
    assert not list(session.known_hosts.parent.glob(".hostkeys-*"))


def test_algorithm_change_blocks_authentication(make, key):
    # Different algorithm for the same endpoint cannot become a new first use.
    session, client, calls = make(server_key=paramiko.ECDSAKey.generate())
    keys = paramiko.HostKeys()
    keys.add("192.0.2.10", key.get_name(), key)
    keys.save(str(session.known_hosts))
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == "HOST_KEY_CHANGED"
    assert not caught.value.retryable
    assert not client.authenticated
    assert not calls


def test_lock_file_error_blocks_authentication(make):
    session, client, calls = make()
    session.known_hosts.with_name('known_hosts.lock').mkdir()
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == 'KNOWN_HOSTS_LOCK'
    assert not caught.value.retryable
    assert not client.authenticated
    assert calls == []


def test_handshake_rechecks_latest_disk_key_instead_of_snapshot(make, key, monkeypatch):
    session, client, calls = make()
    known = paramiko.HostKeys()
    known.add('192.0.2.10', key.get_name(), key)
    known.save(str(session.known_hosts))
    original = client.connect

    def connect(**kwargs):
        replacement = paramiko.HostKeys()
        replacement.add('192.0.2.10', key.get_name(), paramiko.RSAKey.generate(1024))
        replacement.save(str(session.known_hosts))
        original(**kwargs)

    monkeypatch.setattr(client, 'connect', connect)
    with pytest.raises(SSHError) as caught:
        session.run('show global-user-table list ip "192.0.2.100"')
    assert caught.value.code == 'HOST_KEY_CHANGED'
    assert not client.authenticated
    assert calls == []


def test_existing_rsa_pin_preserves_negotiation_preference_without_key_cache(make, key, monkeypatch):
    session, client, _ = make()
    known = paramiko.HostKeys()
    known.add('192.0.2.10', key.get_name(), key)
    known.save(str(session.known_hosts))
    original = client.connect
    options = type('Options', (), {'key_types': ('ssh-ed25519', 'rsa-sha2-256', 'rsa-sha2-512', 'ssh-rsa')})()
    transport = type('Transport', (), {'get_security_options': lambda self: options})()
    monkeypatch.setattr(paramiko, 'Transport', lambda *args, **kwargs: transport)

    def connect(**kwargs):
        assert client.get_host_keys().lookup('192.0.2.10') is None
        assert kwargs['transport_factory'](object()) is transport
        assert options.key_types[0] == 'rsa-sha2-512'
        assert set(options.key_types) == {'ssh-ed25519', 'rsa-sha2-256', 'rsa-sha2-512', 'ssh-rsa'}
        original(**kwargs)

    monkeypatch.setattr(client, 'connect', connect)
    session.run('show global-user-table list ip "192.0.2.100"')
    assert client.authenticated
    session.close()
