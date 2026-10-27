"""Real SQLite faults in disposable stores, never the operator's history."""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from aruba_client_live_tracker.models import Event, Outcome, PollResult
from aruba_client_live_tracker.storage import HistoryStore

ROOT = Path(__file__).resolve().parents[1]
WRITER = Path(__file__).parent / "helpers" / "storage_fault_writer.py"


def _subprocess_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(ROOT / "src")
    environment["QT_QPA_PLATFORM"] = "offscreen"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def _assert_integrity(path: Path) -> None:
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("operation", ["session", "poll", "events"])
def test_actual_sqlite_full_preserves_acknowledged_history_and_recovers(tmp_path, operation):
    # Catches missing rollback, swallowed FULL, and an unusable post-error connection.
    path = tmp_path / "history.sqlite3"
    with HistoryStore(path) as store:
        session = store.start_session("192.0.2.100", simulated=True)
        store.save_poll(session, PollResult(Outcome.ERROR, error="acknowledged"), [
            Event("synthetic", "acknowledged"),
        ])
        store._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        pages = store._db.execute("PRAGMA page_count").fetchone()[0]
        assert store._db.execute(f"PRAGMA max_page_count = {pages}").fetchone()[0] == pages
        large = "synthetic-growth-" * 32768
        with pytest.raises(sqlite3.OperationalError) as failed:
            if operation == "session":
                store.start_session(large, simulated=True)
            else:
                store.save_poll(session, PollResult(
                    Outcome.ERROR, error=large if operation == "poll" else "uncommitted",
                ), [Event("synthetic", large if operation == "events" else "uncommitted")])
        assert failed.value.sqlite_errorcode == sqlite3.SQLITE_FULL
        assert not store._db.in_transaction
        assert len(store.sessions()) == 1
        assert [row["error"] for row in store.observations(session)] == ["acknowledged"]
        assert [row["message"] for row in store.events(session)] == ["acknowledged"]
        store._db.execute("PRAGMA max_page_count = 1000000")
        store.save_poll(session, PollResult(Outcome.ERROR, error="recovered"), [
            Event("synthetic", "recovered"),
        ])
        next_session = store.start_session("192.0.2.101", simulated=True)
        store.end_session(next_session)
    _assert_integrity(path)
    with HistoryStore(path) as reopened:
        assert [row["error"] for row in reopened.observations(session)] == ["acknowledged", "recovered"]
        assert [row["message"] for row in reopened.events(session)] == ["acknowledged", "recovered"]
        assert reopened.sessions()[0]["ended_at"] is not None


@pytest.mark.parametrize("phase,attempt", [
    ("before_events", 0), ("before_commit", 0),
    ("commit_window", 0), ("commit_window", 1), ("commit_window", 2),
])
def test_killed_real_writer_reopens_without_half_transactions_or_lost_acknowledgements(
    tmp_path, phase, attempt,
):
    # Catches separate poll/event commits, reset-on-open, and lost acknowledged rows.
    directory = tmp_path / f"{phase}-{attempt}"
    process = subprocess.Popen(
        [sys.executable, str(WRITER), str(directory), phase], cwd=ROOT,
        env=_subprocess_environment(), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    marker = directory / "boundary.json"
    try:
        deadline = time.monotonic() + 15
        while not marker.exists():
            if process.poll() is not None:
                output, errors = process.communicate(timeout=2)
                pytest.fail(f"writer exited before fault boundary: {process.returncode}, {output!r}, {errors!r}")
            assert time.monotonic() < deadline, "writer did not reach the isolated transaction boundary"
            time.sleep(0.005)
        # The first two phases hold an actual uncommitted transaction. In the
        # active window SQLite continues committing; the exact I/O instant varies.
        process.kill()
        _, errors = process.communicate(timeout=10)
        assert process.returncode != 0
        assert not errors, errors.decode("utf-8", errors="replace")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
    path = directory / "history.sqlite3"
    # Read whole acknowledged lines only: a killed process may leave a final
    # incomplete acknowledgement, which never promises a committed record.
    acknowledged = (directory / "acknowledged.jsonl").read_text(encoding="utf-8")
    tokens = [json.loads(line)["token"] for line in acknowledged.splitlines(keepends=True)
              if line.endswith("\n")]
    assert tokens[:5] == [f"synthetic-{index:04d}" for index in range(5)]
    _assert_integrity(path)
    with HistoryStore(path) as reopened:
        assert len(reopened.sessions()) == 1
        session = reopened.sessions()[0]["id"]
        polls = [row["error"] for row in reopened.observations(session)]
        events = [row["message"] for row in reopened.events(session)]
        assert polls == events
        assert len(polls) == len(set(polls))
        assert polls[:len(tokens)] == tokens
        if phase != "commit_window":
            assert polls == [f"synthetic-{index:04d}" for index in range(5)]
        reopened.save_poll(session, PollResult(Outcome.ERROR, error="after-reopen"), [
            Event("synthetic", "after-reopen"),
        ])
        reopened.end_session(session)
        assert reopened.observations(session)[-1]["error"] == "after-reopen"
        assert reopened.events(session)[-1]["message"] == "after-reopen"
        assert reopened.sessions()[0]["ended_at"] is not None
    _assert_integrity(path)


def test_corrupt_database_startup_returns_bounded_error_and_preserves_original(tmp_path):
    # Catches silent database recreation and a blocking startup error dialog.
    data = tmp_path / "isolated-data"
    path = data / "history.sqlite3"
    with HistoryStore(path) as store:
        session = store.start_session("192.0.2.100", simulated=True)
        store.save_poll(session, PollResult(Outcome.ERROR, error="synthetic-only"), [])
    original = path.read_bytes()
    damaged = b"not-a-sqlite-db!" + original[16:]
    assert damaged != original
    path.write_bytes(damaged)
    report = tmp_path / "startup-result.json"
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-m", "aruba_client_live_tracker.main", "--smoke-test",
         "--data-dir", str(data), "--smoke-result", str(report)],
        cwd=ROOT, env=_subprocess_environment(), capture_output=True,
        encoding="utf-8", timeout=15, check=False,
    )
    assert time.monotonic() - started < 15
    assert result.returncode == 6
    summary = json.loads(report.read_text(encoding="utf-8"))
    assert not summary["success"]
    assert "보존" in summary["reason"]
    assert "다른 데이터 폴더" in summary["reason"]
    assert "저장 공간" in summary["reason"]
    assert "synthetic-only" not in summary["reason"]
    assert "Traceback" not in result.stdout + result.stderr
    assert path.read_bytes() == damaged
