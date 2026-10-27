"""Isolated HistoryStore writer used only by storage fault subprocess tests.

The parent owns and kills this exact child. Marker files synchronize real
SQLite transaction boundaries; no storage API or SQLite write is replaced.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from aruba_client_live_tracker.models import Event, Outcome, PollResult
from aruba_client_live_tracker.storage import HistoryStore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("phase", choices=("before_events", "before_commit", "commit_window"))
    args = parser.parse_args()
    directory = args.directory
    directory.mkdir(parents=True, exist_ok=True)
    marker = directory / "boundary.json"
    with HistoryStore(directory / "history.sqlite3") as store:
        session = store.start_session("192.0.2.100", simulated=True)
        with (directory / "acknowledged.jsonl").open("w", encoding="utf-8") as acknowledged:
            for index in range(105):
                token = f"synthetic-{index:04d}"
                if index == 5:
                    def boundary(statement: str) -> None:
                        matches = (
                            statement.startswith("INSERT INTO events")
                            if args.phase == "before_events" else statement == "COMMIT"
                        )
                        if matches and not marker.exists():
                            # This callback observes the actual connection, after
                            # the poll insert or immediately before real COMMIT.
                            marker.write_text(json.dumps({"phase": args.phase, "token": token}),
                                              encoding="utf-8")
                            if args.phase != "commit_window":
                                sys.stdin.read(1)
                    store._db.set_trace_callback(boundary)
                payload = "x" * (256 * 1024) if index >= 5 else "seed"
                store.save_poll(session, PollResult(Outcome.ERROR, error=token), [
                    Event("synthetic", token, facts={"payload": payload}),
                ])
                # An acknowledgement is emitted only after save_poll committed.
                acknowledged.write(json.dumps({"token": token}) + "\n")
                acknowledged.flush()
                os.fsync(acknowledged.fileno())
            # Bound disk usage even if the parent is heavily delayed.
            sys.stdin.read(1)


if __name__ == "__main__":
    main()
