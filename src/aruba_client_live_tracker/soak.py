"""Opt-in timed synthetic diagnostics; no credentials or live devices."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from .models import Outcome
from .runtime_info import runtime_identity


def validate_soak_args(parser, args) -> None:
    if args.soak_seconds is None:
        return
    if not 1 <= args.soak_seconds <= 86400:
        parser.error('SOAK_DURATION_INVALID: use 1..86400 seconds')
    if not args.multi_demo or args.smoke_test or args.screenshot or not args.data_dir or not args.smoke_result:
        parser.error('SOAK_ARGUMENTS_INVALID: requires --multi-demo, --data-dir and --smoke-result only')
    try:
        if args.data_dir.exists() and (not args.data_dir.is_dir() or any(args.data_dir.iterdir())):
            parser.error('SOAK_DATA_NOT_EMPTY: use a new empty diagnostic directory')
        if args.smoke_result.exists() or args.smoke_result.with_suffix('.progress.json').exists():
            parser.error('SOAK_RESULT_EXISTS: use a new result path')
    except OSError:
        parser.error('SOAK_PATH_UNAVAILABLE: diagnostic path is not accessible')


def verify_soak_database(path: Path, metrics: dict) -> None:
    """Check persisted records after the app has closed its database connection."""
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
        integrity = [row[0] for row in db.execute('PRAGMA integrity_check')]
        if integrity != ['ok'] or db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('SOAK_DB_INTEGRITY_FAILED')
        sessions = db.execute('SELECT id, ended_at FROM sessions ORDER BY id').fetchall()
        counts = [db.execute('SELECT count(*) FROM polls WHERE session_id=?', (sid,)).fetchone()[0]
                  for sid, _ in sessions]
        unclosed = sum(ended is None for _, ended in sessions)
        required = max(1, int(metrics['requested_seconds'] / metrics['interval_seconds'] * 0.8))
        if len(sessions) != 10 or unclosed or min(counts, default=0) < required:
            raise ValueError('SOAK_PERSISTENCE_FAILED')
        started = datetime.fromisoformat(metrics['started_at']).timestamp()
        ended = started + metrics['elapsed_seconds']
        gaps, starts, ends = [], [], []
        for sid, _ in sessions:
            first, last = db.execute('SELECT min(collected_at),max(collected_at) FROM polls WHERE session_id=?',
                                     (sid,)).fetchone()
            first, last = datetime.fromisoformat(first).timestamp(), datetime.fromisoformat(last).timestamp()
            if first < started - 1 or last > ended + 1:
                raise ValueError('SOAK_PERSISTENCE_STALLED')
            starts.append(max(0, first - started))
            ends.append(max(0, ended - last))
            gap = db.execute('''SELECT max(gap) FROM (
                SELECT (julianday(collected_at)-lag(julianday(collected_at)) OVER (
                    ORDER BY collected_at,id))*86400 AS gap FROM polls WHERE session_id=?)''', (sid,)).fetchone()[0]
            gaps.append(max(0, gap or 0))
        metrics.update(persisted_max_gap_seconds=max(gaps), persisted_start_gap_seconds=max(starts),
                       persisted_end_gap_seconds=max(ends))
        if max(*gaps, *starts, *ends) > max(30, 3 * metrics['interval_seconds']):
            raise ValueError('SOAK_PERSISTENCE_STALLED')
        metrics.update(db_integrity='ok', unclosed_sessions=unclosed,
                       target_observations={str(index + 1): count for index, count in enumerate(counts)},
                       observation_count=sum(counts), required_observations_per_target=required)


class SoakMonitor:
    """Measure real GUI time and fail closed if collection or heartbeat stalls."""

    def __init__(self, window, seconds: int, report: Path, finish, *, clock=time.monotonic):
        self.window = window
        self.seconds = seconds
        self.report = report.with_suffix('.progress.json')
        self.finish = finish
        self.clock = clock
        self.started = self.last_heartbeat = clock()
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.run_id = uuid.uuid4().hex
        self.identity = runtime_identity()
        self.heartbeat_count = 0
        self.max_gap = 0.0
        self.max_collection_gap = 0.0
        self.last_results = {}
        self.last_progress = {}
        self._progress_failure_started = None
        self.done = False
        self.timer = QTimer(window)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)

    def start(self):
        self.timer.start()

    def snapshot(self) -> dict:
        contexts = list(self.window.coordinator.contexts.values())
        macs = {c.last_result.observation.mac for c in contexts
                if c.last_result is not None and c.last_result.observation is not None}
        return {'diagnostic': 'timed-demo-soak', 'run_id': self.run_id,
                'started_at': self.started_at, 'updated_at': datetime.now(timezone.utc).isoformat(),
                'requested_seconds': self.seconds, 'elapsed_seconds': self.clock() - self.started,
                'interval_seconds': self.window.coordinator.interval,
                'scenario': self.window.scenario.currentData(),
                'qt_platform': QApplication.instance().platformName(),
                'heartbeat_count': self.heartbeat_count, 'max_heartbeat_gap_seconds': self.max_gap,
                'max_collection_gap_seconds': self.max_collection_gap,
                'target_count': len(contexts), 'independent_macs': len(macs),
                'sample_buffer_max': max((len(c.samples) for c in contexts), default=0),
                'event_buffer_max': max((len(c.events) for c in contexts), default=0)}

    def complete(self, code: int, reason: str):
        if self.done:
            return
        self.done = True
        self.timer.stop()
        self.finish(code, reason, self.snapshot())

    def tick(self):
        if self.done:
            return
        now = self.clock()
        self.max_gap = max(self.max_gap, now - self.last_heartbeat)
        self.last_heartbeat = now
        self.heartbeat_count += 1
        if self.max_gap > 15:
            self.complete(9, 'SOAK_HEARTBEAT_STALLED')
            return
        contexts = list(self.window.coordinator.contexts.values())
        if any(c.note or (c.last_result is not None and (
                c.last_result.outcome != Outcome.OK or c.last_result.observation is None
                or not c.last_result.observation.simulated)) for c in contexts):
            self.complete(9, 'SOAK_COLLECTION_FAILED')
            return
        if len(contexts) != 10 or any(c.status != 'running' for c in contexts):
            self.complete(9, 'SOAK_TARGETS_CHANGED')
            return
        for context in contexts:
            gap = now - self.last_progress.get(context.id, self.started)
            self.max_collection_gap = max(self.max_collection_gap, gap)
            if gap > max(30, 3 * self.window.coordinator.interval):
                self.complete(9, 'SOAK_COLLECTION_STALLED')
                return
            if context.last_result is not None and context.last_result is not self.last_results.get(context.id):
                self.last_results[context.id] = context.last_result
                self.last_progress[context.id] = now
        metrics = self.snapshot()
        if self._progress_failure_started is not None and now - self._progress_failure_started >= 5:
            self.complete(9, 'SOAK_PROGRESS_WRITE_FAILED')
            return
        try:
            self.report.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.report.with_suffix('.tmp')
            temporary.write_text(json.dumps({'runtime': self.identity, **metrics}, allow_nan=False), encoding='utf-8')
            temporary.replace(self.report)
        except PermissionError:
            # A Windows reader can briefly prevent atomic replacement. Return
            # to Qt after one attempt; never extend this first-failure deadline.
            if self._progress_failure_started is None:
                self._progress_failure_started = now
            return
        except (OSError, ValueError, TypeError):
            self.complete(9, 'SOAK_PROGRESS_WRITE_FAILED')
            return
        self._progress_failure_started = None
        if now - self.started >= self.seconds:
            if metrics['independent_macs'] != 10:
                self.complete(9, 'SOAK_TARGETS_INCOMPLETE')
            else:
                self.complete(0, '10-target timed demo completed; checking persisted data and shutdown')
