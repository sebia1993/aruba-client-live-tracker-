from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Outcome(StrEnum):
    OK = "ok"
    ABSENT = "absent"
    ERROR = "error"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class Target:
    kind: str
    value: str


@dataclass(frozen=True)
class DeviceIdentity:
    hostname: str = ""
    switch_ip: str = ""
    reported_role: str = ""
    model: str = ""
    version: str = ""
    observed_at: str = ""
    source: str = ""


@dataclass(frozen=True)
class Device:
    name: str
    host: str
    kind: str = "MD"  # AUTO, MM_PRIMARY, MM_STANDBY, MD; UI registration defaults to AUTO.
    port: int = 22
    enabled: bool = True
    mappings: tuple[str, ...] = ()
    identity: DeviceIdentity | None = None
    origin: str = "manual"  # Existing explicit settings are never overwritten by discovery.


@dataclass(frozen=True)
class Credentials:
    username: str = field(repr=False)
    password: str = field(repr=False)


@dataclass(frozen=True)
class Candidate:
    ip: str
    mac: str
    current_switch: str
    role: str | None = None
    ap_name: str | None = None
    auth_method: str | None = None


@dataclass
class Observation:
    collected_at: str = field(default_factory=utc_now)
    ip: str | None = None
    mac: str | None = None
    connected: bool = True
    ssid: str | None = None
    ap_name: str | None = None
    bssid: str | None = None
    md: str | None = None
    role: str | None = None
    vlan: str | None = None
    auth_method: str | None = None
    auth_result: str | None = None
    rssi: float | None = None
    snr: float | None = None
    tx_rate: float | None = None
    rx_rate: float | None = None
    retries: int | None = None
    tx_packets: int | None = None
    rx_packets: int | None = None
    retry_pct: float | None = None
    channel: str | None = None
    band: str | None = None
    source: str = ""
    simulated: bool = False
    field_status: dict[str, str] = field(default_factory=dict)
    evidence: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Diagnostic:
    stage: str
    code: str
    message: str
    device_name: str = ""
    endpoint: str = ""
    command: str = ""
    at: str = field(default_factory=utc_now)
    severity: str = "오류"


DIAGNOSTIC_STAGE_LABELS = {
    "connect": "SSH 연결", "host_key": "서버 키 검사", "auth": "SSH 인증",
    "discovery": "장비 발견", "identity": "장비 역할 판별", "mm_lookup": "MM 단말 검색",
    "md_mapping": "담당 WLC 매핑", "md_command": "WLC 명령 실행",
    "parse": "CLI 출력 해석", "wireless": "무선 항목 조회", "storage": "이력 저장",
}


@dataclass
class PollResult:
    outcome: Outcome
    observation: Observation | None = None
    candidates: list[Candidate] = field(default_factory=list)
    error: str = ""
    collected_at: str = field(default_factory=utc_now)
    mm_status: str = "확인 불가"
    md_status: str = "확인 불가"
    raw: dict[str, str] = field(default_factory=dict, repr=False)
    diagnostics: list[Diagnostic] = field(default_factory=list)


@dataclass
class Event:
    kind: str
    message: str
    severity: str = "정보"
    at: str = field(default_factory=utc_now)
    recommendation: str = ""
    facts: dict = field(default_factory=dict)
    hypothesis: str = "원인 미확인"


@dataclass
class TrackerView:
    result: PollResult
    observation: Observation | None
    events: list[Event]
    stale: bool
    state: str
    last_success: str | None
    last_change: str | None
    previous_ap: str | None = None
