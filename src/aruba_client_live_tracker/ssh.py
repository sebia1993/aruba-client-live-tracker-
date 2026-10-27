"""Bounded read-only SSH with automatic, persistent trust on first use.

Every handshake verifies or pins its key before password authentication. Changed
keys and storage failures are terminal; trust is never delegated to a UI callback.
"""
from __future__ import annotations

import base64
import binascii
import errno
import hashlib
import os
import re
import socket
import stat
import struct
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

import paramiko

if os.name == "nt":
    import msvcrt
else:
    import fcntl

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
    try:
        if path.is_symlink():
            raise ValueError("symlink")
        if not path.exists():
            return keys
        if not path.is_file() or path.stat().st_size > MAX_KNOWN_HOSTS_BYTES:
            raise ValueError("invalid file")
        contents = path.read_bytes()
        if len(contents) > MAX_KNOWN_HOSTS_BYTES:
            raise ValueError("oversized file")
        for number, line in enumerate(contents.decode("utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # Paramiko silently ignores some malformed lines. Fail closed so a
            # broken record cannot turn a previously trusted endpoint into TOFU.
            fields = line.split()
            if len(fields) < 3:
                raise ValueError("invalid record")
            entry = paramiko.hostkeys.HostKeyEntry.from_line(" ".join(fields[:3]), number)
            if entry is None or entry.key is None or not all(entry.hostnames):
                raise ValueError("invalid key")
            for host in entry.hostnames:
                if host.startswith("|"):
                    hashed = host.split("|")
                    if (len(hashed) != 4 or hashed[1] != "1"
                            or any(len(base64.b64decode(value, validate=True)) != 20 for value in hashed[2:])):
                        raise ValueError("invalid hashed hostname")
                known = keys.lookup(host)
                if known and entry.key.get_name() in known and known[entry.key.get_name()] != entry.key:
                    raise ValueError("conflicting records")
                keys.add(host, entry.key.get_name(), entry.key)
    except (OSError, ValueError, UnicodeError, TypeError, IndexError, struct.error, binascii.Error,
            paramiko.SSHException, paramiko.hostkeys.InvalidHostKey) as exc:
        raise SSHError("KNOWN_HOSTS_INVALID", "저장된 SSH 키 파일의 형식 또는 접근 권한을 확인하십시오.") from exc
    return keys


def _trust_check(cancel: threading.Event | None, deadline: float) -> None:
    if cancel is not None and cancel.is_set():
        raise SSHError("CANCELLED", "SSH 키 확인이 취소되었습니다.")
    if time.monotonic() >= deadline:
        raise SSHError("HOST_KEY_TIMEOUT", "SSH 서버 키 저장 또는 잠금 대기 시간이 초과되었습니다.")


@contextmanager
def _trust_lock(path: Path, cancel: threading.Event | None, deadline: float):
    """Lock a persistent sidecar, never the atomically replaced known_hosts inode."""
    _trust_check(cancel, deadline)
    while not _KEYS_LOCK.acquire(blocking=False):
        _trust_check(cancel, deadline)
        time.sleep(0.025)
    descriptor = None
    locked = False
    try:
        _trust_check(cancel, deadline)
        lock_path = path.with_name(path.name + ".lock")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if lock_path.is_symlink():
                raise OSError("symlink")
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise OSError("not a regular lock file")
            if os.name == "nt" and os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
            while True:
                _trust_check(cancel, deadline)
                try:
                    if os.name == "nt":
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    locked = True
                    break
                except OSError as exc:
                    if exc.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK, errno.EINTR):
                        raise
                    time.sleep(0.025)
        except OSError as exc:
            raise SSHError("KNOWN_HOSTS_LOCK", "SSH 키 저장 잠금을 사용할 수 없습니다. 저장 경로와 권한을 확인하십시오.") from exc
        _trust_check(cancel, deadline)
        yield
    finally:
        try:
            if descriptor is not None:
                try:
                    if locked:
                        if os.name == "nt":
                            os.lseek(descriptor, 0, os.SEEK_SET)
                            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                        else:
                            fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError as exc:
                    raise SSHError("KNOWN_HOSTS_LOCK", "SSH 키 저장 잠금을 해제하지 못했습니다.") from exc
                finally:
                    try:
                        os.close(descriptor)
                    except OSError as exc:
                        raise SSHError("KNOWN_HOSTS_LOCK", "SSH 키 저장 잠금을 닫지 못했습니다.") from exc
        finally:
            _KEYS_LOCK.release()


def _same_key(keys: paramiko.HostKeys, host: str, key: paramiko.PKey) -> bool:
    known = keys.lookup(host)
    if not known:
        return False
    # A new algorithm must not bypass trust established for this endpoint.
    if key.get_name() not in known or known[key.get_name()] != key:
        raise SSHError("HOST_KEY_CHANGED", "SSH 서버 키가 변경되어 접속을 차단했습니다. 관리자에게 확인하십시오.")
    return True


def _save_key(path: Path, host: str, key: paramiko.PKey,
              cancel: threading.Event | None = None, deadline: float | None = None) -> None:
    expires = time.monotonic() + INITIAL_CONNECTION_TIMEOUT if deadline is None else deadline
    with _trust_lock(path, cancel, expires):
        keys = _known_keys(path)
        _trust_check(cancel, expires)
        if _same_key(keys, host, key):
            return
        temporary: str | None = None
        try:
            # Append to the latest bytes under the lock, preserving comments,
            # hashed records and every unrelated endpoint exactly as written.
            original = path.read_bytes() if path.exists() else b""
            suffix = ("" if not original or original.endswith(b"\n") else "\n")
            addition = (suffix + host + " " + key.get_name() + " " + key.get_base64() + "\n").encode("utf-8")
            if len(original) + len(addition) > MAX_KNOWN_HOSTS_BYTES:
                raise OSError("known hosts size limit")
            with tempfile.NamedTemporaryFile(prefix=".hostkeys-", dir=path.parent, delete=False) as file:
                temporary = file.name
                file.write(original + addition)
                file.flush()
                os.fsync(file.fileno())
            os.chmod(temporary, 0o600)
            _trust_check(cancel, expires)
            os.replace(temporary, path)
        except OSError as exc:
            raise SSHError("KNOWN_HOSTS_WRITE", "SSH 서버 키를 로컬에 저장하지 못했습니다.") from exc
        finally:
            if temporary:
                try:
                    os.unlink(temporary)
                except FileNotFoundError:
                    pass
                except OSError:
                    # Cleanup must not replace a trust error or allow auth.
                    pass
        _trust_check(cancel, expires)


class _TOFUPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, session: SSHSession, cancel: threading.Event | None, deadline: float):
        self.session = session
        self.cancel = cancel
        self.deadline = deadline

    def missing_host_key(self, client, hostname, key):
        _save_key(self.session.known_hosts, hostname, key, self.cancel, self.deadline)
        _trust_check(self.cancel, self.deadline)
        client.get_host_keys().add(hostname, key.get_name(), key)


class SSHSession:
    """A reusable serialized session; caller owns endpoint pooling and lifetime.

    The optional approval callback is retained for source compatibility and is
    never invoked. ``deadline`` is an absolute ``time.monotonic()`` value.
    """

    def __init__(self, device: Device, credentials: Credentials, known_hosts: Path,
                 approve_host_key: Callable[[Device, str, str], bool] | None = None):
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
        keys = _known_keys(self.known_hosts)  # Validate before opening a network connection.
        endpoint = self.device.host if self.device.port == 22 else f"[{self.device.host}]:{self.device.port}"
        known = keys.lookup(endpoint)

        def transport_factory(*args, **kwargs):
            transport = paramiko.Transport(*args, **kwargs)
            if known:
                # Preserve the existing pin's negotiation preference without
                # letting Paramiko's cached keys bypass the locked disk check.
                options = transport.get_security_options()
                pinned = list(known)
                if "ssh-rsa" in pinned:
                    pinned = ["rsa-sha2-512", "rsa-sha2-256", *pinned]
                preferred = [name for name in pinned if name in options.key_types]
                options.key_types = preferred + [name for name in options.key_types if name not in preferred]
            return transport

        # Keep Paramiko's cache empty: each handshake must compare the latest
        # disk state under the cross-process lock, including known endpoints.
        client.set_missing_host_key_policy(_TOFUPolicy(self, cancel, deadline))
        remaining = min(CONNECT_TIMEOUT, max(0.01, deadline - time.monotonic()))
        client.connect(
            hostname=self.device.host, port=self.device.port,
            username=self.credentials.username, password=self.credentials.password,
            timeout=remaining, banner_timeout=remaining, auth_timeout=remaining,
            look_for_keys=False, allow_agent=False, transport_factory=transport_factory,
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
