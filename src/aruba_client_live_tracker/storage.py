"""Local SQLite history and escaped, explicit Korean reports.

Raw SSH output and credentials are deliberately not written by this module.
Observation timestamps are preserved separately from collection-attempt timestamps.
"""
from __future__ import annotations

import csv
import heapq
import html
import json
import os
import re
import sqlite3
import tempfile
import threading
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path
from typing import Any

from .commands import parse_target
from .models import DIAGNOSTIC_STAGE_LABELS, Diagnostic, Event, PollResult, utc_now

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
_DIAGNOSTIC_FIELDS = (
    ("stage", "진단 단계"), ("label", "진단 단계명"), ("code", "진단 코드"),
    ("device_name", "진단 장비"), ("endpoint", "진단 접속 주소"),
    ("command", "진단 명령"), ("message", "진단 메시지"),
    ("at", "진단 시각"), ("severity", "진단 심각도"),
)
_MAX_DIAGNOSTICS = 128
_MAX_DIAGNOSTIC_TEXT = 2048
_MAX_DIAGNOSTIC_JSON = 512 * 1024
_CREDENTIAL = re.compile(
    r"(?i)(password|passwd|passphrase|secret|token|credential|authorization|username|api_key|private_key)"
    r"(\s*[:=]\s*)(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)


def _safe_diagnostic(item: dict) -> dict[str, str]:
    # The persisted schema is deliberately closed: never copy raw/credential keys.
    fields = ("stage", "code", "message", "device_name", "endpoint", "command", "at", "severity")
    if any(not isinstance(item.get(key, ""), str) for key in fields):
        raise ValueError("invalid diagnostic")
    if any(key not in item for key in ("stage", "code", "message")):
        raise ValueError("invalid diagnostic")
    return {key: _CREDENTIAL.sub(r"\1\2[삭제됨]", item.get(key, ""))[:_MAX_DIAGNOSTIC_TEXT]
            for key in fields}


def _unavailable_diagnostics() -> list[dict[str, str]]:
    return [asdict(Diagnostic("storage", "diagnostics_unavailable", "진단 기록 확인 불가", at=""))]


def _read_diagnostics(encoded: str) -> list[dict[str, str]]:
    try:
        if not isinstance(encoded, str) or len(encoded) > _MAX_DIAGNOSTIC_JSON:
            raise ValueError("diagnostics too large")
        data = json.loads(encoded)
        if not isinstance(data, list) or len(data) > _MAX_DIAGNOSTICS:
            raise ValueError("invalid diagnostic list")
        if any(not isinstance(item, dict) for item in data):
            raise ValueError("invalid diagnostic item")
        return [_safe_diagnostic(item) for item in data]
    except (ValueError, TypeError, RecursionError):
        return _unavailable_diagnostics()


def _diagnostic_values(row: dict) -> list[str | None]:
    diagnostics = row.get("diagnostics", [])
    values = []
    for key, _ in _DIAGNOSTIC_FIELDS:
        entries = [DIAGNOSTIC_STAGE_LABELS.get(item["stage"], UNKNOWN) if key == "label"
                   else item.get(key, "") for item in diagnostics]
        values.append("\n".join(entries) if entries else None)
    return values


_COMBINED_HEADERS = [
    "세션 ID", "검색 조건", "대상 IP", "대상 MAC", "대상 식별 관측 시각",
    "기록 유형", "수집 시각", "유효 관측 시각", "상태", "가상 데이터", "오류",
    *[label for _, label in _FIELDS], "항목별 상태", "수집 근거/항목별 관측 시각",
    "이벤트", "관측 사실", "추정 원인", "추가 확인 사항",
    *[label for _, label in _DIAGNOSTIC_FIELDS],
]


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


def _read_history_record(encoded: str, *, event: bool = False) -> dict:
    """Reject damaged persisted JSON without exposing its contents in errors."""
    try:
        data = json.loads(encoded)
        if not isinstance(data, dict):
            raise ValueError
        if event:
            if any(not isinstance(data.get(key), str) for key in
                   ('kind', 'message', 'severity', 'at', 'recommendation', 'hypothesis')):
                raise ValueError
            if not isinstance(data.get('facts'), dict):
                raise ValueError
        else:
            if not isinstance(data.get('collected_at'), str):
                raise ValueError
            for key in ('field_status', 'evidence'):
                mapping = data.get(key, {})
                if not isinstance(mapping, dict) or any(not isinstance(value, str) for value in mapping.values()):
                    raise ValueError
        return data
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError('HISTORY_DATA_INVALID: 이력 데이터가 손상되어 읽을 수 없습니다. '
                         '기존 DB를 보존하고 다른 이력을 선택하거나 백업을 확인하세요.') from exc


class ReportCancelled(RuntimeError):
    """The operator closed the report dialog before publication."""


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise ReportCancelled("보고서 저장을 취소했습니다. 기존 보고서는 보존했습니다.")


def _observation_record(row) -> dict:
    item = dict(row)
    item["diagnostics"] = _read_diagnostics(item.get("diagnostics", "[]"))
    encoded = item.pop("observation")
    parsed = _read_history_record(encoded) if encoded is not None else {}
    parsed["observed_at"] = parsed.get("collected_at")
    parsed.update(item)
    return parsed


@contextmanager
def _report_output(destination: Path, encoding: str, newline: str | None = None,
                   cancel_event: threading.Event | None = None):
    """Publish a complete report only after its temporary sibling is flushed."""
    fd, name = tempfile.mkstemp(prefix='.report-', suffix='.tmp', dir=destination.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with temporary.open('w', encoding=encoding, newline=newline) as handle:
            yield handle
            handle.flush()
            os.fsync(handle.fileno())
        _check_cancel(cancel_event)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


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
                    observation TEXT, diagnostics TEXT NOT NULL DEFAULT '[]'
                );
                CREATE INDEX IF NOT EXISTS polls_session_time ON polls(session_id, collected_at);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
                    at TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_session_time ON events(session_id, at);
            """)
        # Serialize schema inspection and ALTER across processes. SQLite DDL is
        # transactional only with an explicit transaction, not executescript().
        try:
            self._db.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in self._db.execute("PRAGMA table_info(polls)")}
            if "diagnostics" not in columns:
                self._db.execute("ALTER TABLE polls ADD COLUMN diagnostics TEXT NOT NULL DEFAULT '[]'")
            self._db.commit()
        except Exception:
            self._db.rollback()
            self._db.close()
            raise
        # Runtime writes are called by the GUI owner thread. A different app
        # instance holding a write lock must not freeze that thread for 15 s.
        self._db.execute("PRAGMA busy_timeout = 100")

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
        diagnostics = [_safe_diagnostic(asdict(item)) for item in result.diagnostics[:_MAX_DIAGNOSTICS]]
        diagnostics_json = json.dumps(diagnostics, ensure_ascii=False, allow_nan=False)
        if len(diagnostics_json) > _MAX_DIAGNOSTIC_JSON:
            diagnostics_json = json.dumps(_unavailable_diagnostics(), ensure_ascii=False)
        with self._lock, self._db:
            self._ensure_open()
            self._db.execute(
                "INSERT INTO polls(session_id, collected_at, outcome, error, mm_status, md_status, observation, diagnostics) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (session_id, _instant(result.collected_at), str(result.outcome), result.error,
                 result.mm_status, result.md_status, observation, diagnostics_json),
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
        return [_observation_record(row) for row in rows]

    @contextmanager
    def _reader(self, session_ids: Iterable[int], cancel_event: threading.Event | None = None):
        """A private WAL snapshot never holds the collection connection's lock."""
        ids = list(session_ids)
        if not ids or any(type(identifier) is not int for identifier in ids):
            raise ValueError("내보낼 추적 이력을 선택하십시오.")
        ids = list(dict.fromkeys(ids))
        with self._lock:
            self._ensure_open()
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True, timeout=.1)
        connection.row_factory = sqlite3.Row
        try:
            connection.set_progress_handler(lambda: int(cancel_event is not None and cancel_event.is_set()), 1000)
            connection.execute("CREATE TEMP TABLE selected_sessions(id INTEGER PRIMARY KEY)")
            connection.executemany("INSERT INTO selected_sessions VALUES (?)", ((identifier,) for identifier in ids))
            connection.commit()
            connection.execute("BEGIN")
            sessions = {row["id"]: dict(row) for row in connection.execute(
                "SELECT s.* FROM sessions s JOIN selected_sessions chosen ON chosen.id=s.id")}
            if len(sessions) != len(ids):
                raise ValueError("선택한 추적 이력을 찾을 수 없습니다.")
            _check_cancel(cancel_event)
            yield connection, {identifier: sessions[identifier] for identifier in ids}
        except sqlite3.OperationalError:
            _check_cancel(cancel_event)
            raise
        finally:
            connection.close()

    def history_preview(self, session_ids: Iterable[int], start: str | None = None,
                        end: str | None = None, limit: int = 200) -> tuple[list[dict], list[dict], int, int]:
        """Return exact counts but decode only the latest visible records."""
        if not 1 <= limit <= 200:
            raise ValueError("이력 미리보기 범위를 확인하세요.")
        first, last = self._period(start, end)
        with self._reader(session_ids) as (connection, sessions):
            ranks = {identifier: rank for rank, identifier in enumerate(sessions)}
            output, counts = [], []
            for table, stamp in (("polls", "collected_at"), ("events", "at")):
                where = f"FROM {table} WHERE session_id = ?"
                args = []
                if first:
                    where += f" AND {stamp} >= ?"
                    args.append(first)
                if last:
                    where += f" AND {stamp} <= ?"
                    args.append(last)
                counts.append(sum(connection.execute("SELECT COUNT(*) " + where, (identifier, *args)).fetchone()[0]
                                  for identifier in sessions))
                cursors = [connection.execute("SELECT * " + where + f" ORDER BY {stamp} DESC,id DESC LIMIT ?",
                                              (identifier, *args, limit)) for identifier in sessions]
                # Each index cursor starts at its newest row. Merge lazily so a
                # million old polls never become Python objects or a SQL sort.
                rows = list(islice(heapq.merge(*cursors,
                                              key=lambda row: (row[stamp], ranks[row["session_id"]], row["id"]),
                                              reverse=True), limit))
                if table == "polls":
                    output.append([_observation_record(row) for row in reversed(rows)])
                else:
                    output.append([dict(_read_history_record(row["data"], event=True),
                                        id=row["id"], session_id=row["session_id"]) for row in reversed(rows)])
        return output[0], output[1], counts[0], counts[1]

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
        return [dict(_read_history_record(row["data"], event=True), id=row["id"], session_id=row["session_id"])
                for row in rows]

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
        with _report_output(destination, encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["기록 유형", "수집 시각", "유효 관측 시각", "상태", "가상 데이터", "오류",
                             *[label for _, label in _FIELDS], "항목별 상태", "수집 근거/항목별 관측 시각",
                             "이벤트", "관측 사실", "추정 원인", "추가 확인 사항",
                             *[label for _, label in _DIAGNOSTIC_FIELDS]])
            for row in self.observations(session_id, start, end):
                writer.writerow([_csv_safe(value) for value in [
                    "관측", row["collected_at"], row.get("observed_at"),
                    _OUTCOMES.get(row["outcome"], row["outcome"]), bool(session["simulated"]), row["error"],
                    *[_field_value(row, key) for key, _ in _FIELDS], row.get("field_status"),
                    row.get("evidence"), None, None, "원인 미확인", None,
                    *_diagnostic_values(row),
                ]])
            for event in self.events(session_id, start, end):
                writer.writerow([_csv_safe(value) for value in [
                    "이벤트", event["at"], None, event["severity"], bool(session["simulated"]), None,
                    *[None for _ in _FIELDS], None, None, event["message"], event["facts"], event["hypothesis"],
                    event["recommendation"], *[None for _ in _DIAGNOSTIC_FIELDS],
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
                  "th,td{border:1px solid #425169;padding:8px;text-align:left;vertical-align:top;white-space:pre-line}"
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
        pieces.append("<th>수집 오류</th><th>항목별 상태</th><th>수집 근거/항목별 관측 시각</th>")
        pieces.extend(f"<th>{escape(label)}</th>" for _, label in _DIAGNOSTIC_FIELDS)
        pieces.append("</tr></thead><tbody>")
        for row in observations:
            values = [row["collected_at"], row.get("observed_at"), _OUTCOMES.get(row["outcome"], row["outcome"]),
                      *[_field_value(row, key) for key, _ in _FIELDS], row["error"],
                      row.get("field_status"), row.get("evidence"), *_diagnostic_values(row)]
            pieces.append("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in values) + "</tr>")
        pieces.append("</tbody></table></section><h2>이벤트 및 추가 확인</h2>")
        for event in events:
            pieces.append(f"<article><h3>{escape(event['at'])} · {escape(event['severity'])} · {escape(event['message'])}</h3><dl>"
                          f"<dt>관측 사실</dt><dd>{escape(event['facts'])}</dd>"
                          f"<dt>추정 원인</dt><dd>{escape(event['hypothesis'])}</dd>"
                          f"<dt>추가 확인 사항</dt><dd>{escape(event['recommendation'])}</dd></dl></article>")
        pieces.append("<p>이 보고서는 로컬에서 생성되었습니다. 외부 전송 기능은 없습니다.</p></html>")
        destination = Path(path)
        with _report_output(destination, encoding="utf-8") as handle:
            handle.write("".join(pieces))
        return destination

    def _combined_rows(self, session_ids: Iterable[int], start: str | None,
                       end: str | None, cancel_event: threading.Event | None = None):
        """Stream one consistent timeline using two independent ordered cursors.

        The identity cursor advances through prior observations, including all
        observations at the current instant, matching the existing report's
        last-known-identity semantics without retaining every historical row.
        """
        first, last = self._period(start, end)
        with self._reader(session_ids, cancel_event) as (connection, sessions):
            known = {}
            for identifier, session in sessions.items():
                identity = {}
                try:
                    target = parse_target(session["query"])
                    identity[target.kind] = target.value
                except ValueError:
                    pass
                known[identifier] = (identity, None)
            identities = iter(connection.execute(
                "SELECT p.* FROM polls p JOIN selected_sessions chosen ON chosen.id=p.session_id "
                "WHERE (? IS NULL OR collected_at <= ?) ORDER BY collected_at,p.id", (last, last)))
            previous = next(identities, None)
            args = (first, first, last, last)
            timeline = connection.execute(
                "SELECT p.collected_at stamp,0 kind,p.id,p.session_id,p.observation,p.diagnostics,"
                "p.outcome,p.error,NULL data FROM polls p JOIN selected_sessions c ON c.id=p.session_id "
                "WHERE (? IS NULL OR p.collected_at >= ?) AND (? IS NULL OR p.collected_at <= ?) "
                "UNION ALL SELECT e.at stamp,1 kind,e.id,e.session_id,NULL,NULL,NULL,NULL,e.data "
                "FROM events e JOIN selected_sessions c ON c.id=e.session_id "
                "WHERE (? IS NULL OR e.at >= ?) AND (? IS NULL OR e.at <= ?) ORDER BY 1,2,3",
                (*args, *args))
            emitted = set()
            for record in timeline:
                _check_cancel(cancel_event)
                while previous is not None and previous["collected_at"] <= record["stamp"]:
                    _check_cancel(cancel_event)
                    observation = _observation_record(previous)
                    identifier = previous["session_id"]
                    if observation.get("ip") or observation.get("mac"):
                        identity = dict(known[identifier][0])
                        identity.update({key: observation[key] for key in ("ip", "mac")
                                         if observation.get(key)})
                        known[identifier] = identity, observation.get("observed_at")
                    previous = next(identities, None)
                identifier = record["session_id"]
                session = sessions[identifier]
                identity, observed_at = known[identifier]
                prefix = [identifier, session["query"], identity.get("ip"), identity.get("mac"), observed_at]
                emitted.add(identifier)
                if record["kind"] == 0:
                    row = _observation_record(dict(record, collected_at=record["stamp"]))
                    yield [*prefix, "관측", row["collected_at"], row.get("observed_at"),
                           _OUTCOMES.get(row["outcome"], row["outcome"]), bool(session["simulated"]), row["error"],
                           *[_field_value(row, key) for key, _ in _FIELDS], row.get("field_status"),
                           row.get("evidence"), None, None, "원인 미확인", None, *_diagnostic_values(row)]
                else:
                    event = _read_history_record(record["data"], event=True)
                    yield [*prefix, "이벤트", event["at"], None, event["severity"], bool(session["simulated"]),
                           None, *[None for _ in _FIELDS], None, None, event["message"], event["facts"],
                           event["hypothesis"], event["recommendation"], *[None for _ in _DIAGNOSTIC_FIELDS]]
            for identifier in sorted(set(sessions) - emitted):
                _check_cancel(cancel_event)
                session = sessions[identifier]
                identity = {}
                try:
                    target = parse_target(session["query"])
                    identity[target.kind] = target.value
                except ValueError:
                    pass
                yield [identifier, session["query"], identity.get("ip"), identity.get("mac"), None,
                       "세션", None, None, "기간 내 기록 없음", bool(session["simulated"]), None,
                       *[None for _ in _FIELDS], None, None, None, None, "원인 미확인", None,
                       *[None for _ in _DIAGNOSTIC_FIELDS]]

    def export_many_csv(self, session_ids: Iterable[int], path: Path,
                        start: str | None = None, end: str | None = None, *,
                        cancel_event: threading.Event | None = None) -> Path:
        """Export selected sessions as one chronological, spreadsheet-safe timeline."""
        rows = self._combined_rows(session_ids, start, end, cancel_event)
        destination = Path(path)
        with _report_output(destination, encoding="utf-8-sig", newline="", cancel_event=cancel_event) as handle:
            writer = csv.writer(handle)
            writer.writerow(_COMBINED_HEADERS)
            writer.writerows([_csv_safe(value) for value in row] for row in rows)
        return destination

    def export_many_html(self, session_ids: Iterable[int], path: Path,
                         start: str | None = None, end: str | None = None, *,
                         cancel_event: threading.Event | None = None) -> Path:
        """Export the same merged timeline with all caller-controlled values escaped."""
        rows = self._combined_rows(session_ids, start, end, cancel_event)

        def escape(value: Any) -> str:
            return html.escape(_display(value), quote=True)

        pieces = ["<!doctype html><html lang='ko'><meta charset='utf-8'>",
                  "<meta name='viewport' content='width=device-width,initial-scale=1'>",
                  "<title>Aruba 클라이언트 통합 추적 보고서</title><style>",
                  "body{font-family:'Malgun Gothic',sans-serif;background:#101823;color:#e7eef7;"
                  "margin:24px;line-height:1.6}section{overflow:auto}table{border-collapse:collapse;"
                  "width:100%}th,td{border:1px solid #425169;padding:8px;text-align:left;"
                  "vertical-align:top;white-space:pre-line}th{background:#203047}h1{color:#7cdaeb}</style>",
                  "<h1>Aruba Client Live Tracker 통합 보고서</h1>",
                  f"<p>내보내기 기간: {escape(start)} ~ {escape(end)}</p>",
                  "<p>기록은 수집 시각순이며 시간은 UTC 오프셋이 포함된 ISO 8601 형식입니다. "
                  "가상 데이터는 실제 장비 관측이 아닙니다. 조회 실패는 연결 해제의 증거가 아닙니다. "
                  "대상 IP/MAC은 검색 조건 또는 이전 관측의 식별 정보이며 현재 측정값을 뜻하지 않습니다. "
                  "이벤트 행에는 새 측정값이 없습니다. 이전 조회값은 항목별 상태와 수집 근거의 관측 시각을 "
                  "확인하십시오. PHY Rate는 실제 처리량이 아닙니다. 확인 불가 항목은 추정하지 않습니다.</p>",
                  "<section><table><thead><tr>"]
        pieces.extend(f"<th>{escape(label)}</th>" for label in _COMBINED_HEADERS)
        pieces.append("</tr></thead><tbody>")
        destination = Path(path)
        with _report_output(destination, encoding="utf-8", cancel_event=cancel_event) as handle:
            handle.write("".join(pieces))
            for row in rows:
                handle.write("<tr>" + "".join(f"<td>{escape(value)}</td>" for value in row) + "</tr>")
            handle.write("</tbody></table></section><p>이 보고서는 로컬에서 생성되었습니다. "
                         "외부 전송 기능은 없습니다.</p></html>")
        return destination

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._db.close()
                self._closed = True
