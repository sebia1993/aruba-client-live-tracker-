"""Bounded, read-only Aruba interactive SSH with explicit first-use trust.

The server key is checked by Paramiko before password authentication. No device
configuration commands, automatic key acceptance, or session logging are used.
"""
from __future__ import annotations

import base64
import hashlib
import inspect
import os
import re
import socket
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import paramiko

from .commands import validate_command
from .models import Credentials, Device

MAX_OUTPUT_BYTES = 1024 * 1024
COMMAND_TIMEOUT = 20.0
INITIAL_CONNECTION_TIMEOUT = 60.0
CONNECT_TIMEOUT = 10.0
MAX_KNOWN_HOSTS_BYTES = 1024 * 1024
_MAX_PAGES = 200
_KEYS_LOCK = threading.RLock()
_ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PROMPT = re.compile(r"^(?:\([^\r\n]{1,80}\)\s*)?[\^*]{0,2}\s*(?:\[[^\r\n]{1,80}\]\s*)?[A-Za-z0-9._:*^ -]{0,80}[#>]$")
_PAGING = re.compile(r"--\s*More\s*--|Press (?:any key|<space>|space) to continue", re.I)


class SSHError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def fingerprint_sha256(key: paramiko.PKey) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def _known_keys(path: Path) -> paramiko.HostKeys:
    keys = paramiko.HostKeys()
    if path.is_symlink():
        raise SSHError("KNOWN_HOSTS_INVALID", "SSH 키 파일의 심볼릭 링크는 사용할 수 없습니다.")
    if path.exists():
        if not path.is_file() or path.stat().st_size > MAX_KNOWN_HOSTS_BYTES:
            raise SSHError("KNOWN_HOSTS_INVALID", "SSH 키 파일의 형식 또는 크기를 확인하십시오.")
        try:
            keys.load(str(path))
        except (OSError, ValueError, paramiko.SSHException) as exc:
            raise SSHError("KNOWN_HOSTS_INVALID", "저장된 SSH 키 파일을 읽을 수 없습니다.") from exc
    return keys


def _same_key(keys: paramiko.HostKeys, host: str, key: paramiko.PKey) -> bool:
    known = keys.lookup(host)
    if not known:
        return False
    # A new algorithm must not bypass trust established for this endpoint.
    if key.get_name() not in known or known[key.get_name()] != key:
        raise SSHError("HOST_KEY_CHANGED", "SSH 서버 키가 변경되어 접속을 차단했습니다. 관리자에게 확인하십시오.")
    return True


def _save_key(path: Path, host: str, key: paramiko.PKey) -> None:
    with _KEYS_LOCK:
        keys = _known_keys(path)
        if _same_key(keys, host, key):
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        keys.add(host, key.get_name(), key)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".hostkeys-", dir=path.parent, delete=False) as file:
                temporary = file.name
            keys.save(temporary)
            os.chmod(temporary, 0o600)
            os.replace(temporary, path)
        except OSError as exc:
            raise SSHError("KNOWN_HOSTS_WRITE", "승인한 SSH 키를 로컬에 저장하지 못했습니다.") from exc
        finally:
            if temporary and os.path.exists(temporary):
                os.unlink(temporary)


class _ApprovalPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, session: SSHSession, cancel: threading.Event | None, deadline: float):
        self.session = session
        self.cancel = cancel
        self.deadline = deadline

    def missing_host_key(self, client, hostname, key):
        session = self.session
        with _KEYS_LOCK:
            if _same_key(_known_keys(session.known_hosts), hostname, key):
                client.get_host_keys().add(hostname, key.get_name(), key)
                return
        def check_approval_deadline():
            if self.cancel is not None and self.cancel.is_set():
                raise SSHError("CANCELLED", "SSH 키 확인이 취소되었습니다.")
            if time.monotonic() >= self.deadline:
                raise SSHError("HOST_KEY_APPROVAL_TIMEOUT", "SSH 서버 키 확인 시간이 만료되었습니다. 다시 조회하여 지문을 확인하십시오.")

        check_approval_deadline()
        if session.approve_host_key is None:
            approved = False
        else:
            callback = session.approve_host_key
            arguments = (session.device, key.get_name(), fingerprint_sha256(key))
            try:
                inspect.signature(callback).bind(*arguments, self.deadline)
            except (TypeError, ValueError):
                approved = callback(*arguments)
            else:
                approved = callback(*arguments, self.deadline)
        # A trust decision must never become a retryable network timeout.
        if approved is not True:
            raise SSHError("HOST_KEY_REJECTED", "SSH 서버 키가 승인되지 않아 접속하지 않았습니다.")
        check_approval_deadline()
        _save_key(session.known_hosts, hostname, key)
        client.get_host_keys().add(hostname, key.get_name(), key)


class SSHSession:
    """A reusable serialized session; caller owns endpoint pooling and lifetime.

    The approval callback must itself return promptly on GUI cancellation. A
    connection has a finite wall-clock budget, and late approval is discarded.
    ``deadline`` is an absolute ``time.monotonic()`` value.
    """

    def __init__(self, device: Device, credentials: Credentials, known_hosts: Path,
                 approve_host_key: Callable[[Device, str, str], bool] | None):
        self.device = device
        self.credentials = credentials
        self.known_hosts = Path(known_hosts)
        self.approve_host_key = approve_host_key
        self._client: paramiko.SSHClient | None = None
        self._channel = None
        self._prompt: str | None = None
        self._operation_lock = threading.Lock()
        self._state_lock = threading.RLock()

    @staticmethod
    def _check(cancel: threading.Event | None, deadline: float) -> None:
        if cancel is not None and cancel.is_set():
            raise SSHError("CANCELLED", "조회가 취소되었습니다.")
        if time.monotonic() >= deadline:
            raise SSHError("TIMEOUT", "SSH 조회 제한 시간이 초과되었습니다.", retryable=True)

    def _watch(self, done: threading.Event, cancel: threading.Event | None, deadline: float) -> None:
        while not done.wait(0.05):
            if (cancel is not None and cancel.is_set()) or time.monotonic() >= deadline:
                self.close()
                return

    def _connect(self, cancel: threading.Event | None, deadline: float) -> None:
        self._check(cancel, deadline)
        if self._client is not None and self._channel is not None:
            transport = self._client.get_transport()
            if transport is not None and transport.is_active() and not self._channel.closed:
                return
        self.close()
        client = paramiko.SSHClient()
        with self._state_lock:
            self._client = client
        with _KEYS_LOCK:
            _known_keys(self.known_hosts)  # Validate before Paramiko's loader.
            if self.known_hosts.exists():
                client.load_host_keys(str(self.known_hosts))
        client.set_missing_host_key_policy(_ApprovalPolicy(self, cancel, deadline))
        remaining = min(CONNECT_TIMEOUT, max(0.01, deadline - time.monotonic()))
        client.connect(
            hostname=self.device.host, port=self.device.port,
            username=self.credentials.username, password=self.credentials.password,
            timeout=remaining, banner_timeout=remaining, auth_timeout=remaining,
            look_for_keys=False, allow_agent=False,
        )
        self._check(cancel, deadline)
        self._channel = client.invoke_shell(term="vt100", width=4096, height=1000)
        self._channel.settimeout(0.2)
        self._read(cancel, deadline, initial=True)

    def _read(self, cancel: threading.Event | None, deadline: float, *, initial: bool = False) -> str:
        data = bytearray()
        pages = 0
        paging_at = -1
        stable_since: float | None = None
        while True:
            self._check(cancel, deadline)
            channel = self._channel
            if channel is None or channel.closed:
                raise SSHError("CONNECTION_CLOSED", "SSH 연결이 종료되었습니다.", retryable=True)
            if channel.recv_ready():
                chunk = channel.recv(65536)
                if not chunk:
                    raise SSHError("CONNECTION_CLOSED", "SSH 응답이 중단되었습니다.", retryable=True)
                data.extend(chunk)
                if len(data) > MAX_OUTPUT_BYTES:
                    raise SSHError("OUTPUT_LIMIT", "SSH 출력량 제한을 초과했습니다. 필터와 CLI 형식을 확인하십시오.")
                stable_since = None
            text = _ANSI.sub("", data.decode("utf-8", errors="replace")).replace("\r", "")
            # CLI pagination may erase its marker with backspaces. Do not erase
            # raw observation bytes; only clean these terminal controls locally.
            text = text.replace("\x08", "")
            matches = list(_PAGING.finditer(text[-200:]))
            if matches:
                offset = max(0, len(text) - 200) + matches[-1].start()
                if offset > paging_at:
                    paging_at = offset
                    pages += 1
                    if pages > _MAX_PAGES:
                        raise SSHError("OUTPUT_LIMIT", "SSH 페이지 수 제한을 초과했습니다.")
                    channel.sendall(" ")
            last = text.rstrip().split("\n")[-1].strip() if text.strip() else ""
            prompt_seen = bool(_PROMPT.fullmatch(last)) if initial else last == self._prompt
            if prompt_seen:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= 0.08:
                    if initial:
                        self._prompt = last
                    body = text.rstrip().rsplit("\n", 1)[0] if "\n" in text.rstrip() else ""
                    return _PAGING.sub("", body)
            time.sleep(0.01)

    def run(self, command: str, cancel: threading.Event | None = None,
            deadline: float | None = None) -> str:
        validate_command(command)
        budget = INITIAL_CONNECTION_TIMEOUT if self._client is None else COMMAND_TIMEOUT
        expires = min(time.monotonic() + budget, deadline) if deadline else time.monotonic() + budget
        self._check(cancel, expires)
        if not self._operation_lock.acquire(blocking=False):
            raise SSHError("BUSY", "동일 장비에서 이미 조회 중입니다.")
        done = threading.Event()
        watcher = threading.Thread(target=self._watch, args=(done, cancel, expires), daemon=True)
        watcher.start()
        try:
            self._connect(cancel, expires)
            self._check(cancel, expires)
            channel = self._channel
            if channel is None:
                self._check(cancel, expires)
                raise SSHError("CONNECTION_CLOSED", "SSH 연결이 종료되었습니다.", retryable=True)
            channel.sendall(command + "\n")
            output = self._read(cancel, expires)
            lines = output.splitlines()
            if lines and lines[0].strip() == command:
                lines.pop(0)
            return "\n".join(lines).strip()
        except SSHError:
            self.close()
            raise
        except paramiko.BadHostKeyException as exc:
            self.close()
            raise SSHError("HOST_KEY_CHANGED", "SSH 서버 키가 변경되어 접속을 차단했습니다. 관리자에게 확인하십시오.") from exc
        except paramiko.AuthenticationException as exc:
            self.close()
            raise SSHError("AUTH_FAILED", "SSH 인증에 실패했습니다. 계정과 조회 권한을 확인하십시오.") from exc
        except (OSError, EOFError, socket.timeout, paramiko.SSHException) as exc:
            self.close()
            self._check(cancel, expires)
            raise SSHError("NETWORK", "SSH 연결 또는 응답을 확인할 수 없습니다.", retryable=True) from exc
        finally:
            done.set()
            watcher.join(timeout=0.2)
            self._operation_lock.release()

    def close(self) -> None:
        with self._state_lock:
            channel, client = self._channel, self._client
            self._channel = None
            self._client = None
            self._prompt = None
        if channel is not None:
            try:
                channel.close()
            except (OSError, EOFError):
                pass
        if client is not None:
            try:
                client.close()
            except (OSError, EOFError):
                pass
