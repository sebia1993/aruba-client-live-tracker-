"""Fair, bounded multi-client scheduling; only tick's caller mutates UI/history state."""

from __future__ import annotations

import queue
import threading
import time
import uuid
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from typing import Callable

from .commands import normalize_mac, parse_target
from .models import Event, Outcome, PollResult, Target, TrackerView
from .tracker import Tracker


@dataclass
class ClientContext:
    id: str
    target: Target
    tracker: Tracker = field(default_factory=Tracker)
    collector: object | None = None
    session_id: int | None = None
    generation: int = 0
    cancel: threading.Event = field(default_factory=threading.Event)
    in_flight: bool = False
    status: str = "stopped"
    selected_mac: str | None = None
    identity_mac: str | None = None
    view: TrackerView | None = None
    last_result: PollResult | None = None
    next_due: float | None = None
    note: str = ""
    pending_start: bool = False
    refresh_pending: bool = False
    samples: deque = field(default_factory=lambda: deque(maxlen=240))
    events: deque = field(default_factory=lambda: deque(maxlen=500))


@dataclass
class _Work:
    identity: str
    generation: int
    collector: object
    future: Future


class MonitoringCoordinator:
    """Call control methods and tick from one owner thread, typically Qt's GUI thread.

    Workers only call collector.poll. At most two jobs are ever submitted; all
    remaining due rows stay in the bounded contexts map, not an executor queue.
    """

    def __init__(
        self,
        store,
        collector_factory: Callable,
        interval: int = 15,
        max_targets: int = 10,
        clock: Callable = time.monotonic,
    ):
        if not 1 <= max_targets <= 10:
            raise ValueError("추적 대상은 최대 10대입니다.")
        self.store = store
        self.collector_factory = collector_factory
        self.contexts: dict[str, ClientContext] = {}
        self.max_targets = max_targets
        self.clock = clock
        self.interval = 15
        self.set_interval(interval)
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="aruba-client")
        self._completed: queue.SimpleQueue = queue.SimpleQueue()
        self._inflight: dict[str, _Work] = {}
        self._order: deque[str] = deque()
        self._closing = False
        self._closed = False

    @property
    def busy(self) -> bool:
        return bool(self._inflight)

    @property
    def active(self) -> bool:
        return any(c.status != "stopped" for c in self.contexts.values())

    def add(self, text: str) -> str:
        if self._closing:
            raise ValueError("프로그램 종료 중에는 대상을 추가할 수 없습니다.")
        target = parse_target(text)
        if any(c.target == target for c in self.contexts.values()):
            raise ValueError("이미 등록된 IP 또는 MAC입니다.")
        if len(self.contexts) >= self.max_targets:
            raise ValueError(f"추적 대상은 최대 {self.max_targets}대까지 등록할 수 있습니다.")
        identity = uuid.uuid4().hex
        self.contexts[identity] = ClientContext(identity, target)
        self._order.append(identity)
        return identity

    def add_many(self, text: str) -> tuple[list[str], list[tuple[int, str]]]:
        added, errors = [], []
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip():
                continue
            try:
                added.append(self.add(line))
            except ValueError as exc:
                errors.append((number, str(exc)))
        return added, errors

    def start(self, identity: str) -> None:
        context = self.contexts[identity]
        if self._closing or context.status == "running":
            return
        if context.status == "paused":
            self.resume(identity)
            return
        if context.in_flight:
            self.stop(identity)
            context.pending_start = True
            return
        self.stop(identity)
        if context.session_id is not None:
            # Keep the previous session available for an explicit save retry.
            return
        try:
            collector = self.collector_factory(context)
        except Exception:
            context.note = "수집기를 시작하지 못했습니다. 장비 설정과 연결 정보를 확인하세요."
            return
        try:
            session = self.store.start_session(
                context.target.value, simulated=bool(getattr(collector, "simulated", False))
            )
        except Exception:
            collector.close()
            context.note = "이력 저장을 시작하지 못했습니다. 저장 공간과 권한을 확인하세요."
            return
        context.collector, context.session_id = collector, session
        context.generation += 1
        context.cancel = threading.Event()
        context.status = "running"
        context.next_due = self.clock()
        context.selected_mac = context.identity_mac = None
        context.view = context.last_result = None
        context.note = ""
        context.tracker.reset()
        context.samples.clear()
        context.events.clear()

    def stop(self, identity: str) -> None:
        context = self.contexts[identity]
        context.generation += 1
        context.cancel.set()
        context.status = "stopped"
        context.next_due = None
        context.pending_start = context.refresh_pending = False
        if context.session_id is not None:
            try:
                self.store.end_session(context.session_id)
            except Exception:
                context.note = "HISTORY_END_FAILED: 추적 종료 시각을 저장하지 못했습니다. 저장 공간과 권한을 확인한 뒤 중지 또는 창 닫기를 다시 시도하세요."
            else:
                context.session_id = None
                if context.note.startswith('HISTORY_END_FAILED:'):
                    context.note = ''
        if not context.in_flight and context.collector is not None:
            context.collector.close()
            context.collector = None

    def pause(self, identity: str) -> None:
        context = self.contexts[identity]
        if context.status == "running":
            context.status = "paused"
            context.next_due = None
            context.refresh_pending = False

    def resume(self, identity: str) -> None:
        context = self.contexts[identity]
        if context.status == "paused":
            context.status = "running"
            context.next_due = self.clock()
        elif context.status == "duplicate":
            self.start(identity)

    def refresh(self, identity: str) -> None:
        context = self.contexts[identity]
        if context.status not in ("running", "paused"):
            return
        context.refresh_pending = True
        if not context.in_flight:
            context.next_due = self.clock()

    def remove(self, identity: str) -> None:
        self.stop(identity)
        if self.contexts[identity].session_id is not None:
            return
        self.contexts.pop(identity)
        self._order.remove(identity)

    def select_candidate(self, identity: str, mac: str) -> None:
        context = self.contexts[identity]
        value = normalize_mac(mac)
        if context.status != "selection_required" or context.last_result is None:
            raise ValueError("선택을 기다리는 대상이 아닙니다.")
        if value not in {c.mac for c in context.last_result.candidates}:
            raise ValueError("조회된 후보에서 클라이언트를 선택하세요.")
        context.selected_mac = value
        context.status = "running"
        context.next_due = self.clock()
        context.note = ""

    def set_interval(self, seconds: int) -> None:
        if seconds not in (10, 15, 30, 60):
            raise ValueError("조회 주기는 10·15·30·60초 중 선택하세요.")
        self.interval = seconds
        for context in getattr(self, "contexts", {}).values():
            if context.status == "running" and not context.in_flight:
                context.next_due = self.clock() + seconds

    def start_all(self):
        for identity in list(self.contexts):
            self.start(identity)

    def stop_all(self):
        for identity in list(self.contexts):
            self.stop(identity)

    def pause_all(self):
        for identity in list(self.contexts):
            self.pause(identity)

    def resume_all(self):
        for identity in list(self.contexts):
            self.resume(identity)

    def refresh_all(self):
        for identity in list(self.contexts):
            self.refresh(identity)

    def _apply(self, context: ClientContext, result: PollResult) -> list[str]:
        changed = [context.id]
        if result.outcome == Outcome.OK and result.observation is not None:
            context.identity_mac = result.observation.mac
            matching = [
                c
                for c in self.contexts.values()
                if c.status not in {"stopped", "duplicate"}
                and c.identity_mac and c.identity_mac == context.identity_mac
            ]
            if len(matching) > 1:
                winner = matching[0]
                for duplicate in matching[1:]:
                    duplicate.status = "duplicate"
                    duplicate.next_due = None
                    duplicate.refresh_pending = False
                    duplicate.note = (
                        f"동일 MAC을 이미 추적 중입니다: {winner.target.value}. 기존 대상을 확인하세요."
                    )
                    if duplicate is not context:
                        duplicate.generation += 1
                        duplicate.cancel.set()
                        changed.append(duplicate.id)
                    if not duplicate.in_flight and duplicate.collector is not None:
                        duplicate.collector.close()
                        duplicate.collector = None
                if winner is not context:
                    result = replace(result, outcome=Outcome.AMBIGUOUS, observation=None, error=context.note)
        if result.outcome == Outcome.AMBIGUOUS and context.status != "duplicate":
            context.status = "selection_required"
            context.next_due = None
            context.note = result.error or "조회된 여러 후보 중 단말을 선택하세요."
        view = context.tracker.apply(result)
        result = view.result
        context.last_result, context.view = result, view
        context.samples.append(
            (result.observation if result.outcome == Outcome.OK else None, result.collected_at)
        )
        context.events.extend(view.events)
        if context.session_id is not None:
            stored = replace(result, observation=view.observation) if result.outcome == Outcome.OK else result
            try:
                self.store.save_poll(context.session_id, stored, view.events)
                if context.note.startswith("이력 저장 실패"):
                    context.note = ""
            except Exception:
                context.note = "이력 저장 실패: 저장 공간과 권한을 확인하세요. 화면 관측은 계속됩니다."
                context.events.append(Event("storage_failed", context.note, severity="경고"))
        return changed

    def tick(self) -> list[str]:
        changed = []
        while True:
            try:
                work = self._completed.get_nowait()
            except queue.Empty:
                break
            if self._inflight.get(work.identity) is not work:
                continue
            self._inflight.pop(work.identity)
            context = self.contexts.get(work.identity)
            if context is not None:
                context.in_flight = False
            if context is None or context.generation != work.generation:
                work.collector.close()
                if context is not None:
                    if context.collector is work.collector:
                        context.collector = None
                    if context.pending_start and not self._closing:
                        context.pending_start = False
                        self.start(context.id)
                    changed.append(context.id)
                continue
            try:
                result = work.future.result()
                if not isinstance(result, PollResult):
                    raise TypeError("Invalid collection result")
            except Exception:
                result = PollResult(
                    Outcome.ERROR, error="수집 작업에서 오류가 발생했습니다. 장비 연결과 진단을 확인하세요."
                )
            changed.extend(self._apply(context, result))
            if context.status == "running":
                context.next_due = self.clock() if context.refresh_pending else self.clock() + self.interval
            elif context.status == "paused" and context.refresh_pending:
                context.next_due = self.clock()
            else:
                context.next_due = None
        if not self._closing:
            for _ in range(len(self._order)):
                if len(self._inflight) >= 2:
                    break
                identity = self._order.popleft()
                self._order.append(identity)
                context = self.contexts[identity]
                due = context.next_due is not None and context.next_due <= self.clock()
                runnable = context.status == "running" or (
                    context.status == "paused" and context.refresh_pending
                )
                if not due or not runnable or context.in_flight or context.collector is None:
                    continue
                context.cancel = threading.Event()
                context.in_flight = True
                context.refresh_pending = False
                context.next_due = None
                future = self._executor.submit(
                    context.collector.poll,
                    context.target,
                    selected_mac=context.selected_mac,
                    cancel=context.cancel,
                )
                work = _Work(identity, context.generation, context.collector, future)
                self._inflight[identity] = work
                future.add_done_callback(lambda _, item=work: self._completed.put(item))
                changed.append(identity)
        return list(dict.fromkeys(changed))

    def close(self, wait: bool = False) -> bool:
        if self._closed:
            return True
        if not self._closing:
            self._closing = True
            self.stop_all()
        else:
            for identity, context in self.contexts.items():
                if context.session_id is not None:
                    self.stop(identity)
        if wait:
            self._executor.shutdown(wait=True)
        self.tick()
        if not self.busy and all(context.session_id is None for context in self.contexts.values()):
            self._executor.shutdown(wait=False)
            self._closed = True
        return self._closed
