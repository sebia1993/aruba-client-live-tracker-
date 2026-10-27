"""Read-only, fail-closed MM→registered MD collection orchestration."""
from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

from .commands import (
    association_command,
    client_table_command,
    global_user_command,
    history_commands,
    normalize_mac,
    parse_target,
    stats_command,
    user_command,
)
from .models import Credentials, Device, Diagnostic, Outcome, PollResult, Target, utc_now
from .parsers import (
    ParseError,
    UnsupportedCommand,
    parse_association,
    parse_client_stats,
    parse_client_table,
    parse_global_users,
    parse_user,
    reject_errors,
)
from .session_pool import OwnerCommandRunner
from .ssh import SSHError, SSHSession

POLL_TIMEOUT = 75.0
MAX_POLL_RAW_BYTES = 2 * 1024 * 1024
HISTORY_INTERVAL = 60.0
MAX_POLL_DIAGNOSTICS = 32


@dataclass
class _PollContext:
    """Keep partial evidence even when a later validation or command fails."""

    credentials: Credentials
    result: PollResult = dataclass_field(default_factory=lambda: PollResult(Outcome.ERROR))
    device: Device | None = None
    command: str = ""
    stage: str = "identity"

    def clean(self, value: str, limit: int) -> str:
        value = "".join(char for char in value if char.isprintable())
        for secret in (self.credentials.password, self.credentials.username):
            if secret:
                value = value.replace(secret, "[숨김]")
        return value[:limit]

    def diagnose(self, code: str, message: str, *, stage: str | None = None) -> Diagnostic:
        device = self.device
        diagnostic = Diagnostic(
            stage or self.stage, self.clean(code, 64), self.clean(message, 512),
            device_name=self.clean(device.name, 128) if device else "",
            endpoint=self.clean(f"{device.host}:{device.port}", 256) if device else "",
            command=self.clean(self.command, 512),
        )
        if len(self.result.diagnostics) < MAX_POLL_DIAGNOSTICS:
            self.result.diagnostics.append(diagnostic)
        return diagnostic

    def failure(self, exc: Exception) -> Diagnostic:
        # Exception text may contain credentials, server banners, or arbitrary raw CLI.
        # Only stable application messages cross into persistent diagnostics/reports.
        if isinstance(exc, SSHError):
            code = exc.code if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", exc.code) else "SSH_ERROR"
            upper = code.upper()
            if upper.startswith(("HOST_KEY", "KNOWN_HOSTS")):
                stage, message = "host_key", "SSH 서버 키 검사 또는 저장에 실패하여 연결을 차단했습니다."
            elif upper.startswith("AUTH"):
                stage, message = "auth", "SSH 인증에 실패했습니다. 공통 계정 정보를 확인하십시오."
            elif upper in ("NETWORK", "CONNECTION_CLOSED", "COOLDOWN", "TIMEOUT"):
                stage, message = "connect", "SSH 연결 또는 응답을 확인할 수 없습니다."
            elif upper == "CANCELLED":
                stage, message = self.stage, "조회가 중지되었습니다."
            elif upper == "OUTPUT_LIMIT":
                stage, message = self.stage, "조회 출력량 제한을 초과했습니다."
            else:
                stage, message = self.stage, "SSH 조회를 완료하지 못했습니다."
        elif isinstance(exc, UnsupportedCommand):
            stage, code, message = self.stage, "COMMAND_REJECTED", "명령어가 거부되었습니다. 지원 여부와 조회 권한을 확인하십시오."
        elif isinstance(exc, ParseError):
            stage, code, message = "parse", "PARSE_FAILED", "CLI 출력 형식을 해석할 수 없습니다. 로컬 원문에서 필수 항목과 완료 건수를 확인하십시오."
        else:
            stage, code, message = self.stage, "VALIDATION_FAILED", "조회 입력 또는 장비 설정을 확인하십시오."
        return self.diagnose(code, message, stage=stage)

    def finish(self, outcome: Outcome, **values) -> PollResult:
        self.result.outcome = outcome
        for key, value in values.items():
            setattr(self.result, key, value)
        return self.result


def map_md(current_switch: str, devices: list[Device]) -> Device:
    matches = [device for device in devices if device.enabled and device.kind == "MD"
               and current_switch in (device.host, *device.mappings)]
    if not matches:
        raise ValueError("담당 MD 매핑이 없습니다. 장비 설정에서 Current switch 값과 SSH 관리 주소의 매핑을 추가하십시오.")
    if len(matches) > 1:
        raise ValueError("담당 MD 매핑이 중복됩니다. 하나의 장비에만 해당 값을 등록하십시오.")
    return matches[0]


class LiveCollector:
    def __init__(self, devices: list[Device], credentials: Credentials, known_hosts: Path,
                 approve_host_key: Callable[[Device, str, str], bool] | None = None, *,
                 command_runner: OwnerCommandRunner | None = None):
        self.devices = list(devices)
        self.credentials = credentials
        self.known_hosts = Path(known_hosts)
        self.approve_host_key = approve_host_key
        self._command_runner = command_runner
        self._runner_md: Device | None = None
        self._sessions: dict[str, tuple[Device, SSHSession]] = {}
        self._lock = threading.Lock()
        self._session_lock = threading.RLock()
        self._history_at: dict[tuple[str, str], float] = {}
        self._history_raw: dict[str, str] = {}
        self._history_status: dict[str, str] = {}
        self._target: Target | None = None
        self._tracked_mac: str | None = None

    def close(self) -> None:
        with self._session_lock:
            if self._command_runner is not None:
                self._command_runner.close()
            self._runner_md = None
            for _, session in self._sessions.values():
                session.close()
            self._sessions.clear()
            self._history_at.clear()
            self._history_raw.clear()
            self._history_status.clear()

    def _session(self, device: Device) -> SSHSession:
        slot = "md" if device.kind == "MD" else "mm"
        with self._session_lock:
            previous = self._sessions.get(slot)
            if previous is not None and previous[0] == device:
                return previous[1]
            if previous is not None:
                previous[1].close()
            session = SSHSession(device, self.credentials, self.known_hosts, self.approve_host_key)
            self._sessions[slot] = (device, session)
            if slot == "md":
                self._history_at.clear()
                self._history_raw.clear()
                self._history_status.clear()
            return session

    def _drop(self, device: Device) -> None:
        if self._command_runner is not None:
            self._command_runner.drop(device)
            return
        slot = "md" if device.kind == "MD" else "mm"
        with self._session_lock:
            previous = self._sessions.pop(slot, None)
            if previous:
                previous[1].close()

    def poll(self, target: Target, selected_mac: str | None = None,
             cancel: threading.Event | None = None) -> PollResult:
        if not self._lock.acquire(blocking=False):
            return PollResult(Outcome.ERROR, error="이전 조회가 진행 중입니다.",
                              diagnostics=[Diagnostic("mm_lookup", "BUSY", "이전 조회가 진행 중입니다.")])
        context = _PollContext(self.credentials)
        try:
            return self._poll(target, selected_mac, cancel, context)
        except (SSHError, ParseError, ValueError) as exc:
            diagnostic = context.failure(exc)
            for name in ("mm_status", "md_status"):
                status = getattr(context.result, name)
                if status.endswith("조회 중"):
                    setattr(context.result, name, status.removesuffix("조회 중") + "조회 실패")
            return context.finish(Outcome.ERROR, error=diagnostic.message)
        finally:
            self._lock.release()

    def _poll(self, target: Target, selected_mac: str | None,
              cancel: threading.Event | None, context: _PollContext) -> PollResult:
        # Revalidate even an externally constructed Target: the UI is not a trust boundary.
        normalized = parse_target(target.value)
        if normalized.kind != target.kind:
            raise ValueError("검색 형식과 값이 일치하지 않습니다.")
        if cancel is not None and cancel.is_set():
            raise SSHError("CANCELLED", "조회가 중지되었습니다.")
        if target != self._target:
            self._target = target
            self._tracked_mac = None
            self._history_at.clear()
            self._history_raw.clear()
            self._history_status.clear()
        if selected_mac is not None:
            normalized_selection = normalize_mac(selected_mac)
            if normalized_selection != self._tracked_mac:
                self._history_at.clear()
                self._history_raw.clear()
                self._history_status.clear()
            self._tracked_mac = normalized_selection
        # Once resolved, pin identity to MAC so DHCP address changes do not switch users.
        lookup_target = Target("mac", self._tracked_mac) if self._tracked_mac else normalized
        deadline = time.monotonic() + POLL_TIMEOUT
        raw = context.result.raw
        raw_bytes = 0

        def run(device: Device, command: str) -> str:
            nonlocal raw_bytes
            context.device, context.command = device, command
            if cancel is not None and cancel.is_set():
                raise SSHError("CANCELLED", "조회가 중지되었습니다.")
            if self._command_runner is None:
                output = self._session(device).run(command, cancel=cancel, deadline=deadline)
            else:
                if device.kind == "MD" and self._runner_md != device:
                    self._runner_md = device
                    self._history_at.clear()
                    self._history_raw.clear()
                    self._history_status.clear()
                output = self._command_runner.run(device, command, cancel=cancel, deadline=deadline)
            size = len(output.encode("utf-8", errors="replace"))
            if raw_bytes + size > MAX_POLL_RAW_BYTES:
                raise SSHError("OUTPUT_LIMIT", "한 번의 조회 출력량 제한을 초과했습니다.")
            raw_bytes += size
            raw[f"{device.name} | {command}"] = output
            return output

        controllers = sorted([d for d in self.devices if d.enabled and d.kind in ("MM_PRIMARY", "MM_STANDBY")],
                             key=lambda d: d.kind != "MM_PRIMARY")
        if not controllers:
            message = "사용 가능한 MM이 없습니다. 장비 연결 설정을 등록하십시오."
            context.diagnose("MM_NOT_CONFIGURED", message, stage="identity")
            return context.finish(Outcome.ERROR, error=message)
        if sum(d.kind == "MM_PRIMARY" for d in controllers) > 1 or sum(d.kind == "MM_STANDBY" for d in controllers) > 1:
            message = "MM Primary와 Standby는 각각 하나씩만 사용하도록 설정하십시오."
            context.diagnose("MM_ROLE_DUPLICATE", message, stage="identity")
            return context.finish(Outcome.ERROR, error=message)
        mm_status = "확인 불가"
        candidates = []
        last_error = ""
        for mm in controllers:
            context.stage = "mm_lookup"
            context.result.mm_status = f"{mm.name} 조회 중"
            try:
                candidates = parse_global_users(run(mm, global_user_command(lookup_target)), lookup_target)
                mm_status = f"{mm.name} 연결 정상"
                if last_error:
                    mm_status += " (대체 MM 조회)"
                break
            except SSHError as exc:
                diagnostic = context.failure(exc)
                self._drop(mm)
                if not exc.retryable or diagnostic.stage in ("host_key", "auth"):
                    return context.finish(Outcome.ERROR, error=diagnostic.message, mm_status="연결 차단")
                last_error = diagnostic.message
            except ParseError as exc:
                diagnostic = context.failure(exc)
                return context.finish(Outcome.ERROR, error=diagnostic.message, mm_status=f"{mm.name} 조회 실패")
        else:
            return context.finish(Outcome.ERROR, error=last_error or "MM 조회 실패", mm_status="통신 실패", raw=raw)
        context.result.mm_status = mm_status
        if not candidates:
            return context.finish(Outcome.ABSENT, mm_status=mm_status, md_status="조회 대상 없음", raw=raw)
        identities = {(c.mac, c.current_switch) for c in candidates}
        if len(candidates) != 1 or len(identities) != 1:
            context.diagnose("CLIENT_AMBIGUOUS", "여러 단말 또는 담당 MD가 검색되어 선택이 필요합니다.")
            return context.finish(Outcome.AMBIGUOUS, candidates=candidates,
                              error="여러 클라이언트 또는 담당 MD가 검색되었습니다. 단말을 선택하십시오.", mm_status=mm_status, raw=raw)
        candidate = candidates[0]
        self._tracked_mac = candidate.mac
        context.stage, context.command = "md_mapping", ""
        try:
            md = map_md(candidate.current_switch, self.devices)
        except ValueError as exc:
            # map_md produces only fixed local messages; never include the switch value.
            message = str(exc)
            context.diagnose("MD_MAPPING_FAILED", message)
            return context.finish(Outcome.ERROR, error=message, mm_status=mm_status, md_status="매핑 필요", raw=raw)
        context.stage = "md_command"
        context.result.md_status = f"{md.name} 조회 중"
        try:
            obs = parse_user(run(md, user_command(candidate.mac)), candidate.mac)
        except (SSHError, ParseError) as exc:
            diagnostic = context.failure(exc)
            if isinstance(exc, SSHError):
                self._drop(md)
            return context.finish(Outcome.ERROR, error=diagnostic.message, mm_status=mm_status, md_status=f"{md.name} 조회 실패", raw=raw)
        if obs is None:
            context.diagnose("MM_MD_MISMATCH", "MM과 MD의 클라이언트 정보가 일치하지 않습니다.")
            # MM still reports this MD: the disagreement is not proof of disconnection.
            return context.finish(Outcome.ERROR, error="MM과 MD의 클라이언트 정보가 일치하지 않습니다. 다음 조회에서 다시 확인합니다.",
                              mm_status=mm_status, md_status="관측 불일치", raw=raw)
        obs.collected_at = utc_now()
        obs.md = md.name
        obs.source = f"{mm.name} → {md.name} / SSH"
        for field, value in [("ip", candidate.ip), ("role", candidate.role),
                             ("ap_name", candidate.ap_name), ("auth_method", candidate.auth_method)]:
            if getattr(obs, field) is None:
                setattr(obs, field, value)
                if value is not None:
                    obs.evidence[field] = f"MM global-user-table | 조회={obs.collected_at}"
        for field in ("ip", "mac", "role", "vlan", "ssid", "bssid", "ap_name", "auth_method", "auth_result"):
            if getattr(obs, field) is not None:
                obs.evidence.setdefault(field, f"{user_command(candidate.mac)} | 조회={obs.collected_at}")
        for field in ("rssi", "snr", "tx_rate", "rx_rate", "retries", "tx_packets", "rx_packets", "channel", "band"):
            obs.field_status[field] = "확인 불가"
        md_partial = False
        transport_failed = False

        def optional(group: str, command: str, parser, fields: tuple[str, ...]) -> dict:
            nonlocal md_partial, transport_failed
            context.stage, context.device, context.command = "wireless", md, command
            if transport_failed:
                obs.field_status[group] = "조회 실패"
                for field in fields:
                    if getattr(obs, field, None) is None:
                        obs.field_status[field] = "조회 실패"
                return {}
            try:
                values = parser(run(md, command))
                obs.field_status[group] = "정상"
                for field, value in values.items():
                    if hasattr(obs, field):
                        setattr(obs, field, value)
                        obs.field_status[field] = "정상"
                        sample = values.get("rx_sample_time" if field in ("snr", "rx_rate") else "tx_sample_time", "확인 불가")
                        obs.evidence[field] = f"{command} | 조회={utc_now()} | 장비 표본 시각={sample}"
                return values
            except (SSHError, ParseError, ValueError) as exc:
                context.failure(exc)
                md_partial = True
                status = "지원하지 않음" if isinstance(exc, UnsupportedCommand) else "조회 실패"
                obs.field_status[group] = status
                for field in fields:
                    if getattr(obs, field, None) is None:
                        obs.field_status[field] = status
                if isinstance(exc, SSHError):
                    transport_failed = True
                    self._drop(md)
                return {}

        association = optional("association", association_command(candidate.mac),
                               lambda out: parse_association(out, candidate.mac),
                               ("connected", "bssid", "ap_name", "channel", "band"))
        if "connected" not in association:
            obs.field_status["connected"] = "확인 불가"
        stats = optional("client_stats", stats_command(candidate.mac), parse_client_stats,
                         ("snr", "tx_packets", "rx_packets"))
        if stats:
            obs.evidence["counter_source"] = "client_stats"
        if obs.ap_name:
            try:
                command = client_table_command(obs.ap_name)
                wireless = optional("client_table", command, lambda out: parse_client_table(out, candidate.mac, expected_bssid=obs.bssid),
                                    ("snr", "tx_rate", "rx_rate", "retries", "tx_packets", "rx_packets"))
                if all(field in wireless for field in ("tx_packets", "rx_packets", "retries")):
                    obs.evidence["counter_source"] = "client_table"
                else:
                    obs.retries = None  # Do not combine counters from different command families.
                    obs.field_status["retries"] = "확인 불가"
            except ValueError:
                context.stage, context.device, context.command = "wireless", md, ""
                context.diagnose("AP_NAME_UNSUPPORTED", "AP 이름 형식이 지원되지 않아 무선 표 조회를 생략했습니다.")
                md_partial = True
                obs.field_status["client_table"] = "AP 이름 형식 미지원"
        else:
            obs.field_status["client_table"] = "AP 이름 확인 불가"
        key = (md.host, candidate.mac)
        if not transport_failed and time.monotonic() - self._history_at.get(key, -HISTORY_INTERVAL) >= HISTORY_INTERVAL:
            self._history_at[key] = time.monotonic()
            # Keep only current target; bounded even after switching clients repeatedly.
            self._history_at = {key: self._history_at[key]}
            for index, command in enumerate(history_commands(candidate.mac)):
                def history_parser(output: str) -> dict:
                    reject_errors(output)
                    return {}
                group = ("client_trail", "client_match", "auth_trace")[index]
                optional(group, command, history_parser, ())
                self._history_status[group] = obs.field_status[group]
                source_key = f"{md.name} | {command}"
                if source_key in raw:
                    output = raw.pop(source_key)
                    dated_key = source_key + f" | 이력 조회={utc_now()}"
                    raw[dated_key] = output
                    self._history_raw = {k: v for k, v in self._history_raw.items() if command not in k}
                    self._history_raw[dated_key] = output
        while sum(len(value.encode("utf-8", errors="replace")) for value in self._history_raw.values()) > MAX_POLL_RAW_BYTES:
            self._history_raw.pop(next(iter(self._history_raw)))
        for cached_key, cached_output in self._history_raw.items():
            if cached_key in raw:
                continue
            cached_bytes = len(cached_output.encode("utf-8", errors="replace"))
            if raw_bytes + cached_bytes <= MAX_POLL_RAW_BYTES:
                raw[cached_key] = cached_output
                raw_bytes += cached_bytes
        for group, status in self._history_status.items():
            obs.field_status.setdefault(group, status + " · 이전 이력 조회값")
        if cancel is not None and cancel.is_set():
            context.diagnose("CANCELLED", "조회가 중지되었습니다.")
            return context.finish(Outcome.ERROR, error="조회가 중지되었습니다.", mm_status=mm_status, md_status="중지", raw=raw)
        return context.finish(Outcome.OK, observation=obs, mm_status=mm_status,
                          md_status=f"{md.name} " + ("일부 항목 조회 실패" if md_partial else "연결 정상"), raw=raw)
