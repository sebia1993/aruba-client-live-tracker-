"""Deterministic, disconnected scenarios. No SSH/network imports or stored samples."""
from __future__ import annotations

import threading

from .models import Candidate, Observation, Outcome, PollResult, Target, utc_now

SCENARIOS = {
    "cycle": "전체 시나리오 순환", "normal": "정상 클라이언트 접속",
    "ip_search": "IP로 검색", "mac_search": "MAC으로 검색", "ip_change": "IP 변경",
    "snr_drop": "SNR 저하", "rate_drop": "Tx/Rx PHY Rate 변동", "roam": "AP 로밍",
    "role_change": "인증 Role 변경", "retries": "재전송 급증", "disconnect": "연결 해제",
    "reconnect": "연결 해제 후 재연결", "mm_failure": "MM 통신 실패", "md_failure": "MD 통신 실패",
    "md_change": "담당 MD 변경", "format_change": "CLI 출력 형식 변경",
    "invalid_mac": "잘못된 MAC 입력 안내", "duplicate": "중복 클라이언트 검색 결과",
}
_DEMO_MAC = "02:00:00:00:00:01"
_OTHER_MAC = "02:00:00:00:00:02"
_DEMO_IP = "192.0.2.100"
DEMO_CLIENTS: list[Candidate] = [
    Candidate(f"192.0.2.{100 + index}", f"02:00:00:00:00:{index + 1:02x}",
              f"192.0.2.{11 + index % 2}", "demo-employee", f"DEMO-AP-{index + 1:02d}", "802.1X")
    for index in range(10)
]
_SEQUENCE = (
    "normal", "normal", "ip_change", "snr_drop", "rate_drop", "roam", "role_change", "retries",
    "disconnect", "disconnect", "reconnect", "mm_failure", "normal", "md_failure", "normal",
    "md_change", "format_change", "normal", "duplicate",
)


class DemoCollector:
    """Use the same collection contract with visibly simulated observations.

    Individual change scenarios begin with one baseline observation. Cycle wraps;
    it stores no observations and opens no network connections.
    """

    connection_count = 0
    simulated = True

    def __init__(self, scenario: str = "cycle"):
        if scenario not in SCENARIOS:
            raise ValueError("지원하지 않는 데모 시나리오입니다.")
        self.scenario = scenario
        self._step = 0
        self._offered_macs: set[str] = set()
        self._target: Target | None = None
        self._tracked_mac: str | None = None
        self._explicit_choice = False

    def _scenario(self) -> str:
        if self.scenario == "cycle":
            return _SEQUENCE[self._step % len(_SEQUENCE)]
        if self.scenario in {"duplicate", "invalid_mac", "normal", "ip_search", "mac_search"}:
            return self.scenario
        if self.scenario in {"disconnect", "reconnect"}:
            return ("normal", "disconnect", "disconnect", "reconnect")[min(self._step, 3)]
        return "normal" if self._step == 0 else self.scenario

    def poll(self, target: Target, selected_mac: str | None = None,
             cancel: threading.Event | None = None) -> PollResult:
        at = utc_now()
        if cancel is not None and cancel.is_set():
            return PollResult(Outcome.ERROR, error="가상 조회가 취소되었습니다.", collected_at=at)
        if target != self._target:
            self._target = target
            self._tracked_mac = None
            self._explicit_choice = False
            self._offered_macs.clear()
        scenario = self._scenario()
        self._step = (self._step + 1) % 1_000_000
        statuses = {"collected_at": at, "mm_status": "연결됨 · 가상", "md_status": "연결됨 · 가상"}
        if scenario == "invalid_mac":
            return PollResult(Outcome.ERROR, error="가상 시나리오: 잘못된 MAC은 검색창 입력 검사에서 거부됩니다.", **statuses)
        if scenario in {"mm_failure", "md_failure", "format_change"}:
            if scenario == "mm_failure":
                statuses.update(mm_status="조회 실패 · 가상", md_status="조회하지 않음")
                message = "가상 시나리오: MM 통신 실패. 연결 상태를 판정할 수 없습니다."
            elif scenario == "md_failure":
                statuses["md_status"] = "조회 실패 · 가상"
                message = "가상 시나리오: 담당 MD 통신 실패. 이전 유효 값을 보존합니다."
            else:
                message = "가상 시나리오: CLI 출력 형식을 인식할 수 없어 정상 관측으로 처리하지 않았습니다."
            return PollResult(Outcome.ERROR, error=message, **statuses)

        if selected_mac is not None:
            if self._offered_macs and selected_mac.lower() not in self._offered_macs:
                return PollResult(Outcome.ABSENT, **statuses)
            self._tracked_mac = selected_mac.lower()
            self._explicit_choice = True
        requested_mac = self._tracked_mac or (target.value.lower() if target.kind.lower() == "mac" else None)
        candidate = next((item for item in DEMO_CLIENTS
                          if (item.mac == requested_mac if requested_mac else item.ip == target.value)), None)
        if candidate is None or target.kind.lower() not in {"ip", "mac"}:
            return PollResult(Outcome.ABSENT, **statuses)
        if scenario == "duplicate" and target.kind.lower() == "ip" and not self._explicit_choice:
            other = DEMO_CLIENTS[(DEMO_CLIENTS.index(candidate) + 1) % len(DEMO_CLIENTS)]
            candidates = [
                Candidate(target.value, candidate.mac, candidate.current_switch, candidate.role,
                          candidate.ap_name, candidate.auth_method),
                Candidate(target.value, other.mac, other.current_switch, "demo-guest",
                          other.ap_name, other.auth_method),
            ]
            self._offered_macs = {item.mac for item in candidates}
            return PollResult(Outcome.AMBIGUOUS, candidates=candidates,
                              error="가상 시나리오: 같은 IP에 두 MAC이 있습니다. 추적할 MAC을 선택하십시오.",
                              **statuses)
        self._tracked_mac = candidate.mac
        if scenario == "disconnect":
            return PollResult(Outcome.ABSENT, **statuses)

        client_index = DEMO_CLIENTS.index(candidate)
        observation = Observation(
            collected_at=at, ip=candidate.ip, mac=candidate.mac, connected=True,
            ssid="DEMO-WLAN", ap_name=candidate.ap_name, bssid=f"02:10:00:00:00:{client_index + 1:02x}",
            md=f"DEMO-MD-{1 + client_index % 2:02d}",
            role="demo-employee", vlan="100", auth_method="802.1X", auth_result="인증 성공 · 가상",
            rssi=-58.0, snr=36.0, tx_rate=866.7, rx_rate=780.0, retries=20 + (self._step - 1) * 6,
            tx_packets=1000 + (self._step - 1) * 200, rx_packets=800 + (self._step - 1) * 150,
            channel="36", band="5 GHz", source="가상 데이터 · 실제 Aruba 장비 출력 아님", simulated=True,
            evidence={"origin": "offline synthetic scenario", "counter_source": "demo",
                      "scenario": SCENARIOS[scenario],
                      "rates": "가상 현재 PHY Rate; 실제 처리량 아님",
                      "counters": "가상 누적 Tx 패킷 및 재전송 카운터"},
        )
        if scenario == "ip_change":
            observation.ip = f"192.0.2.{101 + client_index}"
        elif scenario == "snr_drop":
            observation.snr, observation.rssi = 12.0, -79.0
        elif scenario == "rate_drop":
            observation.tx_rate, observation.rx_rate = 24.0, 18.0
        elif scenario == "roam":
            next_ap = (client_index + 1) % len(DEMO_CLIENTS) + 1
            observation.ap_name, observation.bssid = f"DEMO-AP-{next_ap:02d}", f"02:10:00:00:00:{next_ap:02x}"
            observation.snr, observation.channel = 28.0, "44"
        elif scenario == "role_change":
            observation.role, observation.vlan = "demo-quarantine", "200"
        elif scenario == "retries":
            observation.retries, observation.tx_packets = 350, 2000
        elif scenario == "md_change":
            next_ap = (client_index + 2) % len(DEMO_CLIENTS) + 1
            observation.md, observation.ap_name = f"DEMO-MD-{2 - client_index % 2:02d}", f"DEMO-AP-{next_ap:02d}"
            observation.bssid = f"02:10:00:00:00:{next_ap:02x}"
        elif scenario == "duplicate" and observation.mac == _OTHER_MAC:
            observation.role, observation.md = "demo-guest", "DEMO-MD-02"
            observation.ap_name, observation.bssid = "DEMO-AP-02", "02:10:00:00:00:02"
        return PollResult(Outcome.OK, observation, raw={"데모": "가상 데이터입니다. 실제 CLI 원문이 아닙니다."}, **statuses)

    def close(self) -> None:
        """No resources to release; collector can be restarted after close."""
