"""Local SQLite history and escaped, explicit Korean reports.

Raw SSH output and credentials are deliberately not written by this module.
Observation timestamps are preserved separately from collection-attempt timestamps.
"""
from __future__ import annotations

import csv
import html
import json
import sqlite3
import threading
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import Event, PollResult, utc_now

UNKNOWN = "확인 불가"
_FIELDS = (
    ("ip", "IP"), ("mac", "MAC"), ("connected", "연결 여부"), ("ssid", "SSID"),
    ("ap_name", "AP"), ("bssid", "BSSID"), ("md", "MD"), ("role", "Role"),
    ("vlan", "VLAN"), ("auth_method", "인증 방식"), ("auth_result", "인증 결과"),
    ("snr", "SNR (dB)"), ("rssi", "RSSI (dBm)"), ("tx_rate", "Tx PHY Rate (Mbps)"),
    ("rx_rate", "Rx PHY Rate (Mbps)"), ("retries", "재전송 횟수"),
    ("retry_pct", "재전송률 (%)"), ("tx_packets", "송신 패킷"),
    ("rx_packets", "수신 패킷"), ("channel", "채널"), ("band", "대역"),
    ("source", "수집 출처"),
)
_OUTCOMES = {"ok": "정상 조회", "absent": "미접속 관측", "error": "조회 실패", "ambiguous": "선택 필요"}


def _instant(value: str) -> str:
    """Normalize caller-selected ISO8601 instants for inclusive SQL filters."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, AttributeError) as exc:
        raise ValueError("기간은 ISO 8601 시각으로 입력하십시오.") from exc
    if parsed.tzinfo is None:
        # A local date/time chooser naturally supplies local time.
        parsed = parsed.astimezone()
    return parsed.astimezone(UTC).isoformat(timespec="microseconds")


def _display(value: Any) -> str:
    if value is None or value == "":
        return UNKNOWN
    if isinstance(value, bool):
        return "예" if value else "아니요"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _field_value(row: dict, key: str) -> Any:
    """An observed row may contain cached fields whose provenance differs."""
    value = row.get(key)
    status = row.get("field_status", {}).get(key, "정상")
    if key == "connected" and status != "정상":
        return UNKNOWN
    if status.startswith("이전 조회값"):
        return f"{_display(value)} ({status})"
    if status != "정상":
        return UNKNOWN if status == UNKNOWN else f"{UNKNOWN} ({status})"
    return value


def _csv_safe(value: Any) -> str:
    text = _display(value)
    # Spreadsheet programs may evaluate formulas after ignoring whitespace.
    if text.lstrip().startswith(("=", "+", "-", "@")) or text.startswith(("\t", "\r")):
        return "'" + text
    return text


class HistoryStore:
    """One serialized connection, usable from Qt's worker and GUI threads."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._closed = False
        self._db = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._db:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._db.execute("PRAGMA journal_mode = WAL")
            self._db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY, query TEXT NOT NULL,
                    simulated INTEGER NOT NULL, started_at TEXT NOT NULL, ended_at TEXT
                );
                CREATE TABLE IF NOT EXISTS polls (
                    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                    collected_at TEXT NOT NULL, outcome TEXT NOT NULL,
                    error TEXT NOT NULL, mm_status TEXT NOT NULL, md_status TEXT NOT NULL,
                    observation TEXT
                );
                CREATE INDEX IF NOT EXISTS polls_session_time ON polls(session_id, collected_at);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                    at TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session_time ON events(session_id, at);
            """)

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("이력 저장소가 닫혀 있습니다.")

    def start_session(self, query: str, simulated: bool = False) -> int:
        with self._lock, self._db:
            self._ensure_open()
            cursor = self._db.execute(
                "INSERT INTO sessions(query, simulated, started_at) VALUES (?, ?, ?)",
                (query, int(simulated), _instant(utc_now())),
            )
            return int(cursor.lastrowid)

    def end_session(self, session_id: int) -> None:
        with self._lock, self._db:
            self._ensure_open()
            self._db.execute("UPDATE sessions SET ended_at = COALESCE(ended_at, ?) WHERE id = ?",
                             (_instant(utc_now()), session_id))

    def save_poll(self, session_id: int, result: PollResult, events: list[Event]) -> None:
        observation = None
        if result.observation is not None:
            observation = json.dumps(asdict(result.observation), ensure_ascii=False, allow_nan=False)
        with self._lock, self._db:
            self._ensure_open()
            self._db.execute(
                "INSERT INTO polls(session_id, collected_at, outcome, error, mm_status, md_status, observation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, _instant(result.collected_at), str(result.outcome), result.error,
                 result.mm_status, result.md_status, observation),
            )
            self._db.executemany("INSERT INTO events(session_id, at, data) VALUES (?, ?, ?)", [
                (session_id, _instant(event.at), json.dumps(asdict(event), ensure_ascii=False, allow_nan=False))
                for event in events
            ])

    def sessions(self) -> list[dict]:
        with self._lock:
            self._ensure_open()
            rows = [dict(row) for row in self._db.execute("SELECT * FROM sessions ORDER BY id DESC")]
        for row in rows:
            row["simulated"] = bool(row["simulated"])
        return rows

    @staticmethod
    def _period(start: str | None, end: str | None) -> tuple[str | None, str | None]:
        first, last = _instant(start) if start else None, _instant(end) if end else None
        if first and last and first > last:
            raise ValueError("시작 시각은 종료 시각보다 늦을 수 없습니다.")
        return first, last

    def observations(self, session_id: int, start: str | None = None,
                     end: str | None = None) -> list[dict]:
        first, last = self._period(start, end)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT * FROM polls WHERE session_id = ? AND (? IS NULL OR collected_at >= ?) "
                "AND (? IS NULL OR collected_at <= ?) ORDER BY id",
                (session_id, first, first, last, last),
            ).fetchall()
        output = []
        for row in rows:
            item = dict(row)
            encoded = item.pop("observation")
            parsed = json.loads(encoded) if encoded else {}
            # Distinguish a successful field's timestamp from the poll-attempt time.
            parsed["observed_at"] = parsed.get("collected_at")
            parsed.update(item)
            output.append(parsed)
        return output

    def events(self, session_id: int, start: str | None = None,
               end: str | None = None) -> list[dict]:
        first, last = self._period(start, end)
        with self._lock:
            self._ensure_open()
            rows = self._db.execute(
                "SELECT * FROM events WHERE session_id = ? AND (? IS NULL OR at >= ?) "
                "AND (? IS NULL OR at <= ?) ORDER BY id",
                (session_id, first, first, last, last),
            ).fetchall()
        return [dict(json.loads(row["data"]), id=row["id"], session_id=row["session_id"]) for row in rows]

    def _session(self, session_id: int) -> dict:
        with self._lock:
            self._ensure_open()
            row = self._db.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if row is None:
            raise ValueError("선택한 추적 이력을 찾을 수 없습니다.")
        return dict(row)

    def export_csv(self, session_id: int, path: Path, start: str | None = None,
                   end: str | None = None) -> Path:
        session = self._session(session_id)
        destination = Path(path)
        with destination.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["기록 유형", "수집 시각", "유효 관측 시각", "상태", "가상 데이터", "오류",
                             *[label for _, label in _FIELDS], "항목별 상태", "수집 근거/항목별 관측 시각",
                             "이벤트", "관측 사실", "추정 원인", "추가 확인 사항"])
            for row in self.observations(session_id, start, end):
                writer.writerow([_csv_safe(value) for value in [
                    "관측", row["collected_at"], row.get("observed_at"),
                    _OUTCOMES.get(row["outcome"], row["outcome"]), bool(session["simulated"]), row["error"],
                    *[_field_value(row, key) for key, _ in _FIELDS], row.get("field_status"),
                    row.get("evidence"), None, None, "원인 미확인", None,
                ]])
            for event in self.events(session_id, start, end):
                writer.writerow([_csv_safe(value) for value in [
                    "이벤트", event["at"], None, event["severity"], bool(session["simulated"]), None,
                    *[None for _ in _FIELDS], None, None, event["message"], event["facts"], event["hypothesis"],
                    event["recommendation"],
                ]])
        return destination

    def export_html(self, session_id: int, path: Path, start: str | None = None,
                    end: str | None = None) -> Path:
        session = self._session(session_id)
        observations = self.observations(session_id, start, end)
        events = self.events(session_id, start, end)

        def escape(value: Any) -> str:
            return html.escape(_display(value), quote=True)

        pieces = ["<!doctype html><html lang='ko'><meta charset='utf-8'>",
                  "<meta name='viewport' content='width=device-width,initial-scale=1'>",
                  "<title>Aruba 클라이언트 추적 보고서</title><style>",
                  "body{font-family:'Malgun Gothic',sans-serif;background:#101823;color:#e7eef7;"
                  "margin:24px;line-height:1.6}table{border-collapse:collapse;width:100%;margin:16px 0}"
                  "th,td{border:1px solid #425169;padding:8px;text-align:left;vertical-align:top}"
                  "th{background:#203047}section{overflow:auto}.notice{color:#ffd175}"
                  "dt{font-weight:bold}dd{margin-bottom:8px}h1,h2{color:#7cdaeb}</style>",
                  "<h1>Aruba Client Live Tracker 보고서</h1>",
                  f"<p class='notice'>{'가상 데이터 · 실제 장비 관측이 아닙니다.' if session['simulated'] else '로컬 장비 조회 기록'}</p>",
                  f"<p>검색 조건: {escape(session['query'])}<br>추적 시작: {escape(session['started_at'])}",
                  f"<br>추적 종료: {escape(session['ended_at'])}<br>내보내기 기간: {escape(start)} ~ {escape(end)}</p>",
                  "<p>시간은 UTC 오프셋이 포함된 ISO 8601 형식입니다. PHY Rate는 실제 처리량이 아닙니다. "
                  "조회 실패는 연결 해제의 증거가 아닙니다. 확인 불가 항목에는 값을 추정하여 넣지 않습니다. "
                  "이전 조회값은 현재 측정값이 아니며, 항목별 상태와 수집 근거에 기록된 관측 시각을 확인하십시오.</p>",
                  "<h2>관측 사실</h2><section><table><thead><tr><th>수집 시각</th><th>유효 관측 시각</th><th>상태</th>"]
        pieces.extend(f"<th>{escape(label)}</th>" for _, label in _FIELDS)
        pieces.append("<th>수집 오류</th><th>항목별 상태</th><th>수집 근거/항목별 관측 시각</th></tr></thead><tbody>")
        for row in observations:
            values = [row["collected_at"], row.get("observed_at"), _OUTCOMES.get(row["outcome"], row["outcome"]),
                      *[_field_value(row, key) for key, _ in _FIELDS], row["error"],
                      row.get("field_status"), row.get("evidence")]
            pieces.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in values) + "</tr>")
        pieces.append("</tbody></table></section><h2>이벤트 및 추가 확인</h2>")
        for event in events:
            pieces.append(f"<article><h3>{escape(event['at'])} · {escape(event['severity'])} · {escape(event['message'])}</h3><dl>"
                          f"<dt>관측 사실</dt><dd>{escape(event['facts'])}</dd>"
                          f"<dt>추정 원인</dt><dd>{escape(event['hypothesis'])}</dd>"
                          f"<dt>추가 확인 사항</dt><dd>{escape(event['recommendation'])}</dd></dl></article>")
        pieces.append("<p>이 보고서는 로컬에서 생성되었습니다. 외부 전송 기능은 없습니다.</p></html>")
        destination = Path(path)
        destination.write_text("".join(pieces), encoding="utf-8")
        return destination

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True
