"""Synthetic SSH transport tests; no network equipment or secrets."""
from __future__ import annotations

import base64
import hashlib
import socket
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
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


# Official AOS 8.10 CLI Reference, physical pp. 1629 and 3361. Transport
# fragmentation/erase sequences below are synthetic, not captured device bytes.
ARUBA_PAGER = '--More-- (q) quit (u) pageup (/) search (n) repeat'


class PagedChannel(Channel):
    def __init__(self, pager=ARUBA_PAGER, *, split=0, erase='', newline=True, pages=1):
        super().__init__()
        self.pager = pager
        self.split = split
        self.erase = erase
        self.newline = newline
        self.pages = pages
        self.page = 0

    def _page(self, prefix):
        if self.page < self.pages:
            self.pending.append((prefix + self.pager[:self.split]).encode())
            self.pending.append(self.pager[self.split:].encode())
        else:
            self.pending.append((prefix + '\r\n(lab) #').encode())

    def sendall(self, value):
        self.sent.append(value)
        if value == ' ':
            self.page += 1
            separator = '\r\n' if self.newline else ''
            self._page(self.erase + separator + f'    row {self.page + 1}' +
                       ('\r\n' if self.page < self.pages else ''))
        else:
            self._page(value + 'row 1\r\n')


@pytest.mark.parametrize('split,erase,newline', [
    (0, '', True), (3, '', True), (8, '', True), (25, '', True),
    (8, '\x08' * len(ARUBA_PAGER), False),
    (8, '\x08' * len(ARUBA_PAGER) + ' ' * len(ARUBA_PAGER) + '\x08' * len(ARUBA_PAGER), True),
    (8, '\x08' * len(ARUBA_PAGER) + ' ' * len(ARUBA_PAGER) + '\x08' * len(ARUBA_PAGER), False),
    (8, '\r' + ' ' * len(ARUBA_PAGER) + '\r', False),
    (8, '\r\x1b[2K', False),
])
def test_full_aruba_pager_never_leaks_help_or_erase_padding_into_rows(make, split, erase, newline):
    channel = PagedChannel(split=split, erase=erase, newline=newline)
    session, _, _ = make(channel=channel)
    try:
        output = session.run('show switches')
        assert [line for line in output.splitlines() if line.strip()] == ['row 1', '    row 2']
        assert channel.sent == ['show switches\n', ' ']
    finally:
        session.close()


def test_full_aruba_pager_advances_once_per_page_even_with_ansi_and_fragmentation(make):
    channel = PagedChannel(pager='\x1b[7m' + ARUBA_PAGER + '\x1b[0m', split=12, pages=2)
    session, _, _ = make(channel=channel)
    try:
        output = session.run('show switches')
        assert [line for line in output.splitlines() if line.strip()] == ['row 1', '    row 2', '    row 3']
        assert channel.sent == ['show switches\n', ' ', ' ']
    finally:
        session.close()


def test_help_like_data_without_pager_marker_is_not_removed(make):
    data = 'row 1\r\n(q) quit (u) pageup (/) search (n) repeat\r\nrow 2'
    session, _, _ = make(channel=Channel(data + '\r\n(lab) #'))
    try:
        assert session.run('show switches') == data.replace('\r', '')
    finally:
        session.close()


@pytest.mark.parametrize('pager', ['--More--', 'Press <space> to continue'])
def test_short_pagers_preserve_the_next_row(make, pager):
    channel = PagedChannel(pager=pager, split=3)
    session, _, _ = make(channel=channel)
    try:
        output = session.run('show switches')
        assert [line for line in output.splitlines() if line.strip()] == ['row 1', '    row 2']
        assert channel.sent == ['show switches\n', ' ']
    finally:
        session.close()


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


def test_close_aborts_real_transport_before_channel_rekey_wait(tmp_path):
    """A channel close must not wait for rekey or strand the live transport."""
    local, peer = socket.socketpair()
    transport = paramiko.Transport(local)
    channel = paramiko.Channel(1)
    channel._set_transport(transport)
    channel._set_remote_channel(1, 32768, 32768)
    transport._channels.put(1, channel)
    transport.active = True
    transport.clear_to_send.clear()
    # Preserve Paramiko's real rekey wait/error path without a 30-second test.
    transport.clear_to_send_timeout = -1
    client = paramiko.SSHClient()
    client._transport = transport
    session = SSHSession(Device('synthetic', '192.0.2.10'), Credentials('synthetic', 'secret'),
                         tmp_path / 'known_hosts')
    session._client, session._channel = client, channel
    try:
        session.close()
        assert not transport.is_active()
        assert local.fileno() == -1
        assert channel.closed
        session.close()
    finally:
        transport.close()
        peer.close()


def test_close_still_releases_client_when_channel_cleanup_raises(make, monkeypatch):
    session, client, _ = make()
    session._client, session._channel = client, client.channel

    def channel_failure():
        raise paramiko.SSHException('synthetic cleanup error')

    monkeypatch.setattr(client.channel, 'close', channel_failure)
    session.close()
    assert client.closed
    assert session._client is None and session._channel is None


@pytest.mark.parametrize('interruption,expected', [('cancel', 'CANCELLED'), ('deadline', 'TIMEOUT')])
def test_real_password_auth_interruption_keeps_cancellation_reason(tmp_path, monkeypatch,
                                                                  interruption, expected):
    from test_live_ssh_integration import _LabSSH, _ServerInterface

    entered, release = threading.Event(), threading.Event()
    original_auth = _ServerInterface.check_auth_password

    def delayed_auth(server, username, password):
        entered.set()
        assert release.wait(3), 'synthetic authentication was not released'
        return original_auth(server, username, password)

    monkeypatch.setattr(_ServerInterface, 'check_auth_password', delayed_auth)
    server = _LabSSH('MM')
    cancel = threading.Event()
    session = SSHSession(Device('synthetic', '127.0.0.1', 'MM_PRIMARY', server.port),
                         Credentials('synthetic', 'secret'), tmp_path / 'known_hosts')
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            deadline = time.monotonic() + (0.8 if interruption == 'deadline' else 3)
            pending = workers.submit(session.run, 'show switches', cancel, deadline)
            try:
                assert entered.wait(2), 'password authentication was not reached'
                if interruption == 'cancel':
                    cancel.set()
                with pytest.raises(SSHError) as caught:
                    pending.result(timeout=2)
                assert caught.value.code == expected
                assert caught.value.retryable == (interruption == 'deadline')
            finally:
                release.set()
    finally:
        session.close()
        server.close()


def test_real_bad_password_still_reports_auth_failed(tmp_path):
    from test_live_ssh_integration import _LabSSH

    server = _LabSSH('MM')
    server.allow_auth = False
    session = SSHSession(Device('synthetic', '127.0.0.1', 'MM_PRIMARY', server.port),
                         Credentials('synthetic', 'secret'), tmp_path / 'known_hosts')
    try:
        with pytest.raises(SSHError) as caught:
            session.run('show switches', deadline=time.monotonic() + 3)
        assert caught.value.code == 'AUTH_FAILED'
        assert not caught.value.retryable
    finally:
        session.close()
        server.close()


# HPE ArubaOS 8.10 CLI Reference, physical p. 9: ^ means unsaved
# configuration and * means available crash information. The byte streams are
# synthetic; another device hostname/context must not complete this command.
@pytest.mark.parametrize('initial,final', [
    ('(LAB) [mynode] #', '(LAB) ^[mynode] #'),
    ('(LAB) ^[mynode] #', '(LAB) *[mynode] #'),
    ('(LAB) *[mynode] #', '(LAB) ^*[mynode] #'),
    ('(LAB) ^*[mynode] #', '(LAB) [mynode] #'),
])
def test_prompt_status_change_preserves_same_device_identity(make, initial, final):
    channel = Channel('Total entries = 0\r\n' + final)
    channel.pending = deque([('Synthetic CLI\r\n' + initial).encode()])
    session, _, _ = make(channel=channel)
    try:
        assert session.run('show switches', deadline=time.monotonic() + 0.5) == 'Total entries = 0'
    finally:
        session.close()


@pytest.mark.parametrize('final', [
    '(OTHER) ^[mynode] #', '(LAB) ^[othernode] #', '(LAB) ^[mynode] >',
    '(LAB) ^^[mynode] #', '(LAB) %[mynode] #',
])
def test_changed_prompt_identity_does_not_complete_command(make, final):
    channel = Channel('Total entries = 0\r\n' + final)
    channel.pending = deque([b'Synthetic CLI\r\n(LAB) [mynode] #'])
    session, _, _ = make(channel=channel)
    try:
        with pytest.raises(SSHError) as caught:
            session.run('show switches', deadline=time.monotonic() + 0.2)
        assert caught.value.code == 'TIMEOUT'
    finally:
        session.close()


def test_concurrent_close_during_session_reuse_is_a_controlled_error(make, monkeypatch):
    session, client, _ = make()
    session.run('show switches')

    def close_after_transport_snapshot():
        active = not client.closed
        closer = threading.Thread(target=session.close)
        closer.start()
        closer.join(1)
        assert not closer.is_alive()
        return active

    monkeypatch.setattr(client, 'is_active', close_after_transport_snapshot)
    with pytest.raises(SSHError) as caught:
        session.run('show switches')
    assert caught.value.code == 'CONNECTION_CLOSED'
    assert client.channel.sent == ['show switches\n']
