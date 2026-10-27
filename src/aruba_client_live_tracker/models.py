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
class Device:
    name: str
    host: str
    kind: str = "MD"  # MM_PRIMARY, MM_STANDBY, MD
    port: int = 22
    enabled: bool = True
    mappings: tuple[str, ...] = ()


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
