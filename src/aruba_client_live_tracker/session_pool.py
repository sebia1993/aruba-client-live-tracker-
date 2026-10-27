"""Owner-scoped, FIFO SSH sharing. All network I/O runs outside the pool lock."""
from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .models import Credentials, Device
from .ssh import INITIAL_CONNECTION_TIMEOUT, SSHError, SSHSession


class _Cancellation(threading.Event):
    """An operation's cancellation, linked to the caller and owner lifetime."""

    def __init__(self, external: threading.Event | None):
        super().__init__()
        self.external = external

    def is_set(self) -> bool:
        return super().is_set() or (self.external is not None and self.external.is_set())

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            super().wait(0.025 if remaining is None else min(0.025, remaining))
        return True


@dataclass(eq=False)
class _Request:
    owner: OwnerCommandRunner
    device: Device
    cancel: _Cancellation
    deadline: float


@dataclass
class _Entry:
    owners: set[OwnerCommandRunner] = field(default_factory=set)
    queue: deque[_Request] = field(default_factory=deque)
    active: _Request | None = None
    session: SSHSession | None = None
    closing: bool = False
    retry_at: float = 0
    last_used: float = 0


class OwnerCommandRunner:
    """Pass to ``LiveCollector(command_runner=...)``; close releases only this owner."""

    def __init__(self, pool: SharedSessionPool, owner_id: str):
        self._pool = pool
        self.owner_id = owner_id
        self._closed = False
        self._slots: dict[str, tuple[str, int]] = {}

    def run(self, device: Device, command: str, cancel: threading.Event | None = None,
            deadline: float | None = None) -> str:
        return self._pool._run(self, device, command, cancel, deadline)

    def drop(self, device: Device) -> None:
        """Release failed endpoint interest, without closing another owner's work."""
        closing = []
        with self._pool._condition:
            slot = self._pool._slot(device)
            if self._slots.get(slot) == (device.host, device.port):
                self._pool._release(self, slot, closing)
        self._pool._close_sessions(closing)

    def close(self) -> None:
        closing = []
        with self._pool._condition:
            self._pool._release_owner(self, closing)
            self._pool._condition.notify_all()
        self._pool._close_sessions(closing)


class SharedSessionPool:
    """Share at most ``max_connections`` SSH sessions within one credentials scope.

    The optional approval callback is accepted for source compatibility and is
    never invoked. Queue and capacity waits use the command's absolute deadline.
    """

    def __init__(self, credentials: Credentials, known_hosts: Path,
                 approve_host_key: Callable | None = None, max_connections: int = 12, cooldown: float = 15):
        if not 1 <= max_connections <= 12:
            raise ValueError('SSH 연결 수는 1~12 범위여야 합니다.')
        if cooldown < 0:
            raise ValueError('재시도 대기 시간은 음수일 수 없습니다.')
        self.credentials = credentials
        self.known_hosts = Path(known_hosts)
        self.approve_host_key = approve_host_key
        self.max_connections = max_connections
        self.cooldown = cooldown
        self._condition = threading.Condition(threading.RLock())
        self._entries: dict[tuple[str, int], _Entry] = {}
        self._runners: dict[str, OwnerCommandRunner] = {}
        self._closed = False

    def for_owner(self, owner_id: str) -> OwnerCommandRunner:
        with self._condition:
            if self._closed:
                raise SSHError('CANCELLED', 'SSH 풀이 종료되었습니다.')
            runner = self._runners.get(owner_id)
            if runner is None or runner._closed:
                runner = OwnerCommandRunner(self, owner_id)
                self._runners[owner_id] = runner
            return runner

    @staticmethod
    def _slot(device: Device) -> str:
        if device.kind not in {'MD', 'MM_PRIMARY', 'MM_STANDBY'}:
            raise SSHError('DEVICE_TYPE_UNKNOWN', '역할이 확인되지 않은 장비는 추적 연결을 공유할 수 없습니다.')
        return 'md' if device.kind == 'MD' else 'mm'

    @staticmethod
    def _detach_session(entry: _Entry, closing: list[tuple[_Entry, SSHSession]]) -> None:
        session, entry.session = entry.session, None
        if session is not None:
            entry.closing = True
            closing.append((entry, session))

    def _close_sessions(self, closing: list[tuple[_Entry, SSHSession]]) -> None:
        """Finish detached transports outside the condition, retaining capacity meanwhile."""
        while closing:
            entry, session = closing.pop()
            try:
                session.close()
            except Exception:
                # Cleanup must not mask a command failure or strand its waiters.
                pass
            finally:
                with self._condition:
                    entry.closing = False
                    self._condition.notify_all()

    def _release(self, owner: OwnerCommandRunner, slot: str,
                 closing: list[tuple[_Entry, SSHSession]]) -> None:
        endpoint = owner._slots.pop(slot, None)
        if endpoint is None or endpoint in owner._slots.values():
            return
        entry = self._entries[endpoint]
        entry.owners.discard(owner)
        if not entry.owners and entry.active is None:
            self._detach_session(entry, closing)
        self._condition.notify_all()

    def _release_owner(self, owner: OwnerCommandRunner,
                       closing: list[tuple[_Entry, SSHSession]]) -> None:
        owner._closed = True
        if self._runners.get(owner.owner_id) is owner:
            del self._runners[owner.owner_id]
        for entry in self._entries.values():
            if entry.active is not None and entry.active.owner is owner:
                entry.active.cancel.set()
            for request in entry.queue:
                if request.owner is owner:
                    request.cancel.set()
        for slot in list(owner._slots):
            self._release(owner, slot, closing)

    def _check(self, request: _Request) -> None:
        if self._closed or request.owner._closed or request.cancel.is_set():
            raise SSHError('CANCELLED', '조회가 취소되었습니다.')
        if time.monotonic() >= request.deadline:
            raise SSHError('TIMEOUT', 'SSH 조회 대기 제한 시간이 초과되었습니다.', retryable=True)

    def _capacity(self, closing: list[tuple[_Entry, SSHSession]]) -> bool:
        sessions = [entry for entry in self._entries.values() if entry.session is not None or entry.closing]
        if len(sessions) < self.max_connections:
            return True
        idle = [entry for entry in sessions if entry.active is None and not entry.closing]
        if idle:
            self._detach_session(min(idle, key=lambda entry: entry.last_used), closing)
        return False

    def _run(self, owner: OwnerCommandRunner, device: Device, command: str,
             cancel: threading.Event | None, deadline: float | None) -> str:
        self._slot(device)  # Reject AUTO before touching any owner's tracing slots.
        expires = time.monotonic() + INITIAL_CONNECTION_TIMEOUT if deadline is None else deadline
        request = _Request(owner, device, _Cancellation(cancel), expires)
        endpoint = (device.host, device.port)
        closing = []
        with self._condition:
            self._check(request)
            # Discard retired metadata only after the shared cooldown expires.
            for key, old in list(self._entries.items()):
                if (not old.owners and not old.queue and old.active is None
                        and not old.closing and old.retry_at <= time.monotonic()):
                    self._detach_session(old, closing)
                    if not old.closing:
                        del self._entries[key]
            slot = self._slot(device)
            if owner._slots.get(slot) != endpoint:
                self._release(owner, slot, closing)
                owner._slots[slot] = endpoint
            entry = self._entries.setdefault(endpoint, _Entry())
            entry.owners.add(owner)
            entry.queue.append(request)
        try:
            while True:
                self._close_sessions(closing)
                with self._condition:
                    self._check(request)
                    if entry.retry_at > time.monotonic():
                        raise SSHError('COOLDOWN', 'SSH 통신 실패 후 재시도 대기 중입니다.', retryable=True)
                    if entry.queue[0] is request and entry.active is None and not entry.closing:
                        if entry.session is not None or self._capacity(closing):
                            if entry.session is None:
                                entry.session = SSHSession(device, self.credentials, self.known_hosts, None)
                            entry.queue.popleft()
                            entry.active = request
                            session = entry.session
                            break
                    if not closing:
                        self._condition.wait(min(0.05, max(0, expires - time.monotonic())))
        except BaseException:
            with self._condition:
                entry.queue.remove(request)
                self._condition.notify_all()
            raise
        finally:
            self._close_sessions(closing)

        failed = False
        try:
            self._check(request)
            result = session.run(command, cancel=request.cancel, deadline=expires)
            self._check(request)
            return result
        except BaseException as exc:
            failed = True
            with self._condition:
                if isinstance(exc, SSHError) and exc.retryable and not request.cancel.is_set():
                    entry.retry_at = time.monotonic() + self.cooldown
            raise
        finally:
            with self._condition:
                if failed or not entry.owners or self._closed:
                    self._detach_session(entry, closing)
                entry.active = None
                entry.last_used = time.monotonic()
                self._condition.notify_all()
            self._close_sessions(closing)

    def close(self) -> None:
        closing = []
        with self._condition:
            self._closed = True
            for runner in list(self._runners.values()):
                self._release_owner(runner, closing)
            for entry in self._entries.values():
                if entry.active is None:
                    self._detach_session(entry, closing)
                else:
                    entry.active.cancel.set()
            self._condition.notify_all()
        self._close_sessions(closing)
