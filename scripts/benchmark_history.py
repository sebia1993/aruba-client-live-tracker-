"""Synthetic-only large-history timings; never opens the user's application DB."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
if "--directory" in sys.argv:
    directory = Path(sys.argv[sys.argv.index("--directory") + 1])
    baseline_source = Path(__file__).resolve().parents[1] / "artifacts/history-baseline-src"
    if directory.name.startswith("history-baseline-") and baseline_source.exists():
        sys.path.insert(0, str(baseline_source))

from aruba_client_live_tracker.models import Outcome, PollResult  # noqa: E402
from aruba_client_live_tracker.storage import HistoryStore  # noqa: E402


def private_bytes():
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    *[(name, ctypes.c_size_t) for name in (
                        "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
                        "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                        "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    ctypes.windll.kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    ctypes.windll.psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    handle = ctypes.windll.kernel32.GetCurrentProcess()
    ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb)
    return counters.PrivateUsage


def seed(path, count):
    with HistoryStore(path) as store:
        stamp = "2026-10-27T00:00:00.000000+00:00"
        with store._db:
            store._db.executemany(
                "INSERT INTO sessions(id,query,simulated,started_at) VALUES (?,?,1,?)",
                ((i, f"192.0.2.{i % 10 + 1}", stamp) for i in range(1, 10001)))
            for begin in range(0, count, 10000):
                rows = []
                for i in range(begin, min(begin + 10000, count)):
                    at = f"2026-10-27T{i // 3600 % 24:02}:{i // 60 % 60:02}:{i % 60:02}.{i // 86400:06}+00:00"
                    observation = json.dumps({"collected_at": at, "ip": f"192.0.2.{i % 10 + 1}",
                                              "mac": f"02:00:00:00:00:{i % 10:02x}",
                                              "ap_name": "SYNTHETIC-AP", "snr": 25,
                                              "field_status": {}, "evidence": {}})
                    rows.append((i % 10 + 1, at, "ok", "", "ok", "ok", observation, "[]"))
                store._db.executemany(
                    "INSERT INTO polls(session_id,collected_at,outcome,error,mm_status,md_status,observation,diagnostics) "
                    "VALUES (?,?,?,?,?,?,?,?)", rows)
        store._db.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def measure(path, output, operation):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from aruba_client_live_tracker.ui import HistoryDialog

    app = QApplication.instance() or QApplication([])
    store = HistoryStore(path)
    samples = []
    write_latencies = []
    stopped = threading.Event()
    def sample():
        while not stopped.wait(.02):
            samples.append(private_bytes())
    def monitor():
        while not stopped.wait(.02):
            before_write = time.perf_counter()
            store.save_poll(10000, PollResult(Outcome.ERROR, error="SYNTHETIC_ONLY"), [])
            write_latencies.append(time.perf_counter() - before_write)
    sampler = threading.Thread(target=sample, daemon=True)
    sampler.start()
    writer = None
    if operation in ("csv", "html"):
        writer = threading.Thread(target=monitor, daemon=True)
        writer.start()
    heartbeats = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: heartbeats.append(time.perf_counter()))
    timer.start()
    for _ in range(3):
        app.processEvents()
        time.sleep(.02)
    started = time.perf_counter()
    baseline = private_bytes()
    details = {}
    if operation == "dialog":
        dialog = HistoryDialog(store)
        details["sessions_visible"] = dialog.grid.rowCount()
        dialog.close()
    elif operation == "preview":
        dialog = HistoryDialog(store)
        dialog.selection = lambda: (list(range(1, 11)), None, None)
        app.processEvents()
        heartbeats.clear()
        started = time.perf_counter()
        heartbeats.append(started)
        dialog.show_history()
        details["preview_lines"] = len(dialog.preview.toPlainText().splitlines())
        dialog.close()
    else:
        dialog = HistoryDialog(store)
        dialog.selection = lambda: (list(range(1, 11)), None, None)
        QFileDialog.getSaveFileName = lambda *args: (str(output / ("report." + operation)), "")
        messages = []
        QMessageBox.information = lambda *args: messages.append("complete")
        QMessageBox.warning = lambda *args: messages.append("failed")
        app.processEvents()
        heartbeats.clear()
        started = time.perf_counter()
        heartbeats.append(started)
        dialog.export(operation)
        while getattr(dialog, "export_running", False):
            app.processEvents()
            time.sleep(.005)
        if hasattr(dialog, "_finish_export"):
            dialog._finish_export()
        details["result"] = messages
        details["report_bytes"] = (output / ("report." + operation)).stat().st_size
        dialog.close()
    elapsed = time.perf_counter() - started
    app.processEvents()
    stopped.set()
    sampler.join()
    if writer is not None:
        writer.join()
    store.close()
    result = dict(operation=operation, seconds=round(elapsed, 4), baseline_private_bytes=baseline,
                  peak_private_bytes=max([x for x in samples if x] or [0]),
                  gui_heartbeat_max_gap_seconds=round(max((b-a for a,b in zip(heartbeats, heartbeats[1:])), default=0), 4),
                  concurrent_writes=len(write_latencies),
                  max_write_seconds=round(max(write_latencies, default=0), 4),
                  **details)
    print(json.dumps(result), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--polls", type=int, default=100000)
    parser.add_argument("--operation", choices=("seed", "dialog", "preview", "csv", "html"), required=True)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    path = args.directory / "synthetic-history.sqlite3"
    if args.operation == "seed":
        if path.exists():
            parser.error("synthetic DB already exists; choose a new directory")
        seed(path, args.polls)
        print(json.dumps(dict(operation="seed", polls=args.polls, sessions=10000, database_bytes=path.stat().st_size)))
    else:
        measure(path, args.directory, args.operation)


if __name__ == "__main__":
    main()
