"""Loopback SSH integration. All identities and Aruba replies are synthetic."""
from __future__ import annotations

import socket
import threading
import time
from dataclasses import replace

import paramiko
import pytest
from test_commands_parsers import MAC, global_output, table

from aruba_client_live_tracker.collector import LiveCollector
from aruba_client_live_tracker.commands import parse_target
from aruba_client_live_tracker.models import Credentials, Device, Outcome


class _ServerInterface(paramiko.ServerInterface):
    def __init__(self, server):
        self.server = server
        self.shell = threading.Event()

    def check_auth_password(self, username, password):
        self.server.auth_attempts += 1
        return paramiko.AUTH_SUCCESSFUL if self.server.allow_auth else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED if kind == "session" else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(self, *args):
        return True

    def check_channel_shell_request(self, channel):
        self.shell.set()
        return True


class _LabSSH:
    def __init__(self, role):
        self.role = role
        self.split_switches = False
        self.switches_output = None
        self.identity_ip = None
        self.key = paramiko.RSAKey.generate(2048)
        self.allow_auth = True
        self.auth_attempts = 0
        self.commands = []
        self.closed = threading.Event()
        self.transports = []
        self.workers = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(0.1)
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._accept, daemon=True)
        self.thread.start()

    def _accept(self):
        while not self.closed.is_set():
            try:
                connection, _ = self.listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            worker = threading.Thread(target=self._serve, args=(connection,), daemon=True)
            self.workers.append(worker)
            worker.start()

    def _serve(self, connection):
        transport = paramiko.Transport(connection)
        self.transports.append(transport)
        interface = _ServerInterface(self)
        try:
            transport.add_server_key(self.key)
            transport.start_server(server=interface)
            channel = None
            deadline = time.monotonic() + 5
            while not self.closed.is_set() and transport.is_active() and time.monotonic() < deadline:
                channel = transport.accept(0.1)
                if channel is not None:
                    break
            if channel is None:
                return
            deadline = time.monotonic() + 5
            while not interface.shell.wait(0.05):
                if self.closed.is_set() or not transport.is_active() or time.monotonic() >= deadline:
                    return
            channel.settimeout(0.1)
            prompt = f"(LAB-{self.role}) [mynode] #"
            channel.sendall(prompt)
            pending = b""
            while not self.closed.is_set() and transport.is_active():
                try:
                    chunk = channel.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                pending += chunk
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    command = line.decode().strip()
                    self.commands.append(command)
                    channel.sendall(command + "\r\n" + self.reply(command).replace("\n", "\r\n") + "\r\n" + prompt)
        except (EOFError, OSError, paramiko.SSHException):
            # Key/auth rejection deliberately closes the connection mid-handshake.
            pass
        finally:
            transport.close()

    def reply(self, command):
        switch_ip = self.identity_ip or ("192.0.2.10" if self.role == "MM" else "192.0.2.20")
        role = "conductor" if self.role == "MM" else "MD"
        model = "ArubaMM-HW-10K" if self.role == "MM" else "Aruba7240XM"
        if command == "show switches":
            if self.switches_output is not None:
                return self.switches_output
            if self.split_switches:
                identity = table(["IP Address", "Name", "Type", "Model", "Version"], [
                    ["192.0.2.10", "LAB-MM", "conductor", "ArubaMM-HW-10K", "8.10.0.0"],
                    ["192.0.2.20", "LAB-MD", "MD", "Aruba7240XM", "8.10.0.0"],
                ], "")
                status = table(["Status", "Configuration State", "Config Sync Time (sec)", "Config ID"], [
                    ["up", "UPDATE SUCCESSFUL", "0", "7"],
                    ["up", "UPDATE SUCCESSFUL", "0", "7"],
                ], "Total Switches:{count}")
                return identity + "\n" + status
            return table(["IP Address", "Name", "Type", "Model", "Version", "Status"], [
                ["192.0.2.10", "LAB-MM", "conductor", "ArubaMM-HW-10K", "8.10.0.0", "up"],
                ["192.0.2.20", "LAB-MD", "MD", "Aruba7240XM", "8.10.0.0", "up"],
            ], "Total Switches:{count}")
        if command == "show switchinfo":
            mask = "" if ":" in switch_ip else " 255.255.255.0"
            return f"Hostname is LAB-{self.role}\nInternet address is {switch_ip}{mask}\nswitchrole:{role}"
        if command == "show version":
            return f"ArubaOS (MODEL: {model}), Version 8.10.0.0"
        if command.startswith("show global-user-table"):
            return global_output()
        if command.startswith("show user-table mac"):
            return f"IP: 192.0.2.100, MAC: {MAC}, Role: lab-role\nEssid: LAB-WIFI, Bssid: 02:00:00:00:10:01 AP name/group: LAB-AP-A/lab"
        if command.startswith("show ap association"):
            return table(["Name", "bssid", "mac", "auth", "assoc", "Flags"],
                         [["LAB-AP-A", "02:00:00:00:10:01", MAC, "y", "y", "WA"]], "Num Clients:{count}")
        if command.startswith("show ap debug client-stats"):
            return "Last SNR 30\nFrames Transmitted 100\nFrames Received 80"
        return "% Invalid input"

    def close(self):
        self.closed.set()
        self.listener.close()
        self.thread.join(2)
        for transport in self.transports:
            transport.close()
        for worker in self.workers:
            worker.join(2)
        assert not self.thread.is_alive()
        assert all(not worker.is_alive() for worker in self.workers)


@pytest.fixture
def lab():
    servers = []
    def start(role):
        server = _LabSSH(role)
        servers.append(server)
        return server
    yield start
    for server in servers:
        server.close()


def test_real_ssh_auto_trust_monitoring_and_changed_key_diagnostics(lab, tmp_path):
    mm, md = lab("MM"), lab("MD")
    devices = [Device("LAB-MM", "127.0.0.1", "MM_PRIMARY", mm.port),
               Device("LAB-MD", "127.0.0.1", "MD", md.port, mappings=("192.0.2.20",))]
    keys = tmp_path / "known_hosts"
    def forbidden_prompt(*_):
        pytest.fail("First connection must never ask for server key approval")
    collector = LiveCollector(devices, Credentials("synthetic", "synthetic-secret"), keys, forbidden_prompt)
    try:
        result = collector.poll(parse_target(MAC))
        assert result.outcome == Outcome.OK, result.error
        assert result.observation.mac == MAC and result.observation.snr == 30
        assert mm.auth_attempts == md.auth_attempts == 1
        registered = paramiko.HostKeys(str(keys))
        assert len(registered) == 2  # Same IP, independently pinned nondefault ports.
        collector.close()
        preserved = keys.read_bytes()
        md.key = paramiko.RSAKey.generate(2048)
        result = collector.poll(parse_target(MAC))
        assert result.outcome == Outcome.ERROR
        assert any(item.stage == "host_key" and item.code == "HOST_KEY_CHANGED" for item in result.diagnostics)
        assert md.auth_attempts == 1  # Changed key blocked before password authentication.
        assert keys.read_bytes() == preserved
    finally:
        collector.close()


@pytest.mark.parametrize("split", [False, True])
def test_real_ssh_mm_discovery_and_selected_management_address_probe(lab, tmp_path, split):
    from aruba_client_live_tracker.discovery import DiscoveryService
    mm, md = lab("MM"), lab("MD")
    mm.split_switches = split
    service = DiscoveryService(Credentials("synthetic", "synthetic-secret"), tmp_path / "known_hosts")
    try:
        found = service.discover(Device("입력한 MM", "127.0.0.1", "AUTO", mm.port))
        assert len(found.devices) == 2, found.diagnostics
        primary = next(device for device in found.devices if device.kind == "MM_PRIMARY")
        assert primary.host == "127.0.0.1" and primary.port == mm.port
        assert primary.identity.switch_ip == "192.0.2.10"
        candidate = next(device for device in found.devices if device.kind == "MD")
        # Simulate the user's explicit override of a distinct SSH management endpoint.
        candidate = replace(candidate, host="127.0.0.1", port=md.port)
        checked = service.probe([candidate])
        assert len(checked.devices) == 1
        resolved = checked.devices[0]
        assert resolved.kind == "MD" and resolved.identity.model == "Aruba7240XM"
        assert "192.0.2.20" in resolved.mappings
        assert not any(command.startswith("show user-table") for command in md.commands)
        assert "show switches" not in md.commands  # Selection probe does not recursively scan topology.
    finally:
        service.close()


@pytest.mark.parametrize("split", [False, True])
def test_real_ssh_mixed_ipv4_ipv6_discovery_preserves_selected_md_mapping(lab, tmp_path, monkeypatch, split):
    from aruba_client_live_tracker.discovery import DiscoveryService

    # Only the documented None/IPv6 column behavior is reproduced, with RFC
    # 5737/3849 values. These rows are synthetic, not copied operational output.
    mm, md = lab("MM"), lab("MD")
    headers = ["IP Address", "IPv6 Address", "Name", "Location", "Type", "Model", "Version"]
    rows = [
        ["192.0.2.10", "None", "LAB-MM", "Building1.floor1", "conductor", "ArubaMM-HW-10K", "8.10.0.0"],
        ["None", "2001:0db8:0:0:0:0:0:11", "LAB-STANDBY", "Building1.floor1", "standby", "ArubaMM-HW-10K", "8.10.0.0"],
        ["None", "2001:0db8:0:0:0:0:0:20", "LAB-MD", "Building1.floor1", "MD", "Aruba7240XM", "8.10.0.0"],
    ]
    status_headers = ["Status", "Configuration State", "Config Sync Time (sec)", "Config ID"]
    status_rows = [["up", "UPDATE SUCCESSFUL", "0", "7"] for _ in rows]
    if split:
        mm.switches_output = (table(headers, rows, "") + "\n" +
                              table(status_headers, status_rows, "Total Switches:{count}"))
    else:
        mm.switches_output = table(headers + status_headers,
                                   [row + status for row, status in zip(rows, status_rows)],
                                   "Total Switches:{count}")
    md.identity_ip = "2001:db8::20"

    # Keep the genuine SSH stack while prohibiting any automatic connection to
    # discovered addresses, including IPv6. Only explicitly chosen loopback
    # management endpoints may be resolved or contacted by this test.
    getaddrinfo = socket.getaddrinfo
    endpoints = []
    def loopback_only(host, port, *args, **kwargs):
        endpoints.append((host, port))
        assert host == "127.0.0.1" and port in (mm.port, md.port)
        return getaddrinfo(host, port, *args, **kwargs)
    monkeypatch.setattr(socket, "getaddrinfo", loopback_only)

    service = DiscoveryService(Credentials("synthetic", "synthetic-secret"), tmp_path / "known_hosts")
    try:
        found = service.discover(Device("입력한 MM", "127.0.0.1", "AUTO", mm.port))
        assert not found.diagnostics
        assert len(found.devices) == 3
        primary = next(device for device in found.devices if device.kind == "MM_PRIMARY")
        standby = next(device for device in found.devices if device.kind == "MM_STANDBY")
        candidate = next(device for device in found.devices if device.kind == "MD")
        assert (primary.host, primary.port, primary.identity.switch_ip) == ("127.0.0.1", mm.port, "192.0.2.10")
        assert (standby.host, standby.identity.switch_ip) == ("2001:db8::11", "2001:db8::11")
        assert (candidate.host, candidate.identity.switch_ip) == ("2001:db8::20", "2001:db8::20")
        assert candidate.mappings == ("2001:db8::20", "LAB-MD")
        assert endpoints == [("127.0.0.1", mm.port)]
        assert mm.auth_attempts == 1 and md.auth_attempts == 0
        assert mm.commands == ["show switches", "show switchinfo", "show version"]

        # A user can explicitly use an IPv4 management endpoint for an MD whose
        # switch identity is IPv6; probing must retain its canonical mapping.
        candidate = replace(candidate, host="127.0.0.1", port=md.port)
        checked = service.probe([candidate])
        assert not checked.diagnostics
        assert len(checked.devices) == 1
        resolved = checked.devices[0]
        assert (resolved.host, resolved.port, resolved.kind) == ("127.0.0.1", md.port, "MD")
        assert resolved.identity.switch_ip == "2001:db8::20"
        assert resolved.mappings == ("2001:db8::20", "LAB-MD")
        assert endpoints == [("127.0.0.1", mm.port), ("127.0.0.1", md.port)]
        assert md.commands == ["show switchinfo", "show version"]
        assert mm.commands == ["show switches", "show switchinfo", "show version"]
    finally:
        service.close()
