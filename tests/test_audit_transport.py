"""Transport lifecycle regressions using synthetic loopback endpoints only."""
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import paramiko
import pytest
from test_live_ssh_integration import _LabSSH

from aruba_client_live_tracker.models import Credentials, Device
from aruba_client_live_tracker.ssh import SSHError, SSHSession


@pytest.mark.parametrize('interruption', ['cancel', 'deadline'])
def test_interrupted_connect_does_not_leave_late_transport_alive(tmp_path, monkeypatch,
                                                               interruption):
    """Closing before Paramiko publishes its transport must still clean it up."""
    server = _LabSSH('MM')
    entered, release, interrupted = threading.Event(), threading.Event(), threading.Event()
    resolver = socket.getaddrinfo
    cancel = threading.Event()

    class ObservedClient(paramiko.SSHClient):
        def close(self):
            super().close()
            interrupted.set()

    client = ObservedClient()
    session = SSHSession(Device('synthetic', '127.0.0.1', 'MM_PRIMARY', server.port),
                         Credentials('synthetic', 'secret'), tmp_path / 'known_hosts')

    def delayed_resolution(host, port, *args, **kwargs):
        assert (host, port) == ('127.0.0.1', server.port)
        entered.set()
        assert release.wait(3), 'synthetic resolver was not released'
        return resolver(host, port, *args, **kwargs)

    monkeypatch.setattr(socket, 'getaddrinfo', delayed_resolution)
    monkeypatch.setattr(paramiko, 'SSHClient', lambda: client)
    try:
        with ThreadPoolExecutor(max_workers=1) as workers:
            deadline = time.monotonic() + (0.2 if interruption == 'deadline' else 3)
            result = workers.submit(session.run, 'show switches', cancel, deadline)
            try:
                assert entered.wait(1), 'resolver was not reached'
                if interruption == 'cancel':
                    cancel.set()
                assert interrupted.wait(1), 'watcher did not interrupt the client'
            finally:
                release.set()
            with pytest.raises(SSHError) as caught:
                result.result(timeout=2)
            expected = ('CANCELLED',) if interruption == 'cancel' else ('TIMEOUT', 'HOST_KEY_TIMEOUT')
            assert caught.value.code in expected
            transport = client.get_transport()
            assert transport is None or not transport.is_active(), 'cancelled SSH transport remains active'
            assert server.auth_attempts == 0
    finally:
        release.set()
        session.close()
        client.close()
        server.close()
