"""Conservative observation state machine. Network failures are never client absences."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from .models import Event, Observation, Outcome, PollResult, TrackerView


class Tracker:
    def __init__(self):
        self.reset()

    def reset(self):
        self.last: Observation | None = None
        self.baseline: Observation | None = None
        self.last_success: str | None = None
        self.last_change: str | None = None
        self.previous_ap: str | None = None
        self.absences = 0
        self.connected: bool | None = None
        self.failed = False
        self.partial_failures: dict[str, str] = {}

    def apply(self, result: PollResult) -> TrackerView:
        events: list[Event] = []
        at = result.collected_at

        def emit(kind, message, recommendation="", facts=None, severity="정보"):
            events.append(Event(kind, message, severity, at, recommendation, facts or {}))

        if result.outcome == Outcome.ERROR:
            self.absences = 0
            self.baseline = None
            if not self.failed:
                emit('collection_failed', result.error or '장비 조회 실패',
                     'MM/MD 관리 연결, SSH 권한, 서버 키와 CLI 진단을 확인하세요.', severity='경고')
            self.failed = True
            state = '조회 실패 · 이전 조회값' if self.last else '조회 실패'
        elif result.outcome == Outcome.AMBIGUOUS:
            self.absences = 0
            self.baseline = None
            state = '대상 선택 필요'
        elif result.outcome == Outcome.ABSENT:
            if self.failed:
                emit('collection_recovered', '장비 조회가 복구되었습니다.',
                     '완료된 검색 결과에 대상이 없습니다. 클라이언트 연결 상태는 별도로 확인하세요.')
                self.failed = False
            self.baseline = None
            self.absences += 1
            if self.absences >= 2:
                if self.connected is not False:
                    emit('disconnected', '연속 2회 정상 조회에서 대상이 발견되지 않았습니다.',
                         '무선 연결과 인증 이력을 확인하세요. 종료 원인은 아직 확인되지 않았습니다.',
                         {'consecutive_absences': self.absences}, '경고')
                    self.last_change = at
                self.connected = False
                state = '연결 해제'
            else:
                state = '미접속 확인 중'
        elif result.outcome == Outcome.OK and result.observation is not None:
            current = replace(result.observation, field_status=dict(result.observation.field_status),
                              evidence=dict(result.observation.evidence))
            if not current.connected:
                return self.apply(replace(result, outcome=Outcome.ABSENT, observation=None))
            group_labels = {'association': 'AP 연결 상태', 'client_stats': '클라이언트 통계',
                            'client_table': 'AP 클라이언트 표', 'client_trail': 'AP 이동 이력',
                            'client_match': 'ClientMatch 이력', 'auth_trace': '인증 이력'}
            for group in ('association', 'client_stats', 'client_table', 'client_trail', 'client_match', 'auth_trace'):
                status = current.field_status.get(group)
                if status is None:
                    continue
                if status != '정상':
                    if self.partial_failures.get(group) != status:
                        emit('field_collection_failed', f'일부 항목 조회: {group_labels[group]} · {status}',
                             'CLI 진단에서 해당 명령 지원 여부·권한·응답 형식을 확인하세요.',
                             {'collection': group, 'status': status}, '주의')
                    self.partial_failures[group] = status
                elif group in self.partial_failures:
                    del self.partial_failures[group]
                    emit('field_collection_recovered', f'항목 조회 복구: {group_labels[group]}', facts={'collection': group})
            if self.failed:
                emit('collection_recovered', '장비 연결 및 조회가 복구되었습니다.')
            self.failed = False
            self.absences = 0
            connection_known = current.field_status.get('connected', '정상') == '정상'
            if connection_known and self.connected is not True:
                emit('reconnected' if self.connected is False else 'connected',
                     '클라이언트 재연결 감지' if self.connected is False else '클라이언트 최초 연결 감지',
                     facts={'ap': current.ap_name, 'mac': current.mac})
                self.last_change = at
            previous = self.baseline
            current.retry_pct = None
            if connection_known and previous is not None and previous.mac == current.mac:
                self._changes(previous, current, emit)
                current.retry_pct = self._retry_ratio(previous, current)
                if current.retry_pct is not None and current.retry_pct >= 20:
                    emit('retries_high', f'관측 구간 재전송 비율 {current.retry_pct:.1f}%',
                         '전파 간섭, 신호 품질 및 단말 상태를 추가 확인하세요.',
                         {'retry_pct': current.retry_pct}, '주의')
            self.baseline = replace(current, field_status=dict(current.field_status),
                                    evidence=dict(current.evidence)) if connection_known else None
            # Display cached individual values, but never compare them as fresh measurements.
            if self.last and self.last.mac == current.mac and self.last.ap_name == current.ap_name and self.last.bssid == current.bssid:
                for field in ('snr', 'rssi', 'tx_rate', 'rx_rate', 'retries', 'tx_packets', 'rx_packets'):
                    if getattr(current, field) is None and getattr(self.last, field) is not None:
                        setattr(current, field, getattr(self.last, field))
                        current.field_status[field] = '이전 조회값 · ' + current.field_status.get(field, '확인 불가')
                        current.evidence[field] = self.last.evidence.get(field, self.last.collected_at)
            if connection_known:
                self.connected = True
            self.last = current
            self.last_success = current.collected_at
            state = '연결됨' if connection_known else '세션 발견 · 무선 연결 확인 불가'
        else:
            return self.apply(replace(result, outcome=Outcome.ERROR, error='정상 조회에 관측값이 없습니다.'))
        stale = result.outcome != Outcome.OK
        return TrackerView(result, self.last, events, stale, state, self.last_success,
                           self.last_change, self.previous_ap)

    def _changes(self, previous, current, emit):
        def changed(name):
            old, new = getattr(previous, name), getattr(current, name)
            return old is not None and new is not None and old != new

        if changed('ap_name') or changed('bssid'):
            self.previous_ap = previous.ap_name
            emit('roam', 'AP 또는 BSSID 변경 감지',
                 '정상 조회 사이의 변경입니다. 정확한 이동 시각은 CLI 이력과 대조하세요.',
                 {'previous_ap': previous.ap_name, 'new_ap': current.ap_name,
                  'previous_bssid': previous.bssid, 'new_bssid': current.bssid,
                  'snr_before': previous.snr, 'snr_after': current.snr,
                  'role_before': previous.role, 'role_after': current.role,
                  'observed_before': previous.collected_at, 'observed_after': current.collected_at})
        for field, kind, label in [('role','role_changed','Role'), ('vlan','vlan_changed','VLAN'),
                                   ('ip','ip_changed','IP'), ('md','md_changed','담당 MD')]:
            if changed(field):
                emit(kind, f'{label} 변경: {getattr(previous, field)} → {getattr(current, field)}',
                     '정책 또는 이동 이력과 비교하세요.',
                     {'before': getattr(previous, field), 'after': getattr(current, field)})
        if changed('auth_method') or changed('auth_result'):
            emit('auth_changed', '인증 정보 변경 감지', '인증 CLI 이력을 추가 확인하세요.',
                 {'method_before': previous.auth_method, 'method_after': current.auth_method,
                  'result_before': previous.auth_result, 'result_after': current.auth_result})
        if current.snr is not None and previous.snr is not None and previous.snr >= 20 > current.snr:
            emit('snr_low', f'SNR 저하: {previous.snr:g} → {current.snr:g} dB',
                 '간섭, AP와의 거리, 단말 위치를 확인하세요. SNR만으로 원인을 확정할 수 없습니다.',
                 {'before': previous.snr, 'after': current.snr}, '주의')
        for field in ('tx_rate', 'rx_rate'):
            before, after = getattr(previous, field), getattr(current, field)
            if before is not None and after is not None and before >= 12 and after < before * 0.5:
                emit('rate_drop', f'{"Tx" if field == "tx_rate" else "Rx"} PHY Rate 급감: {before:g} → {after:g} Mbps',
                     'PHY Rate는 실제 처리량이 아닙니다. 신호와 재전송을 함께 확인하세요.',
                     {'direction': field, 'before': before, 'after': after}, '주의')

    @staticmethod
    def _retry_ratio(previous: Observation, current: Observation) -> float | None:
        # Never span collection gaps, radio changes, counter resets or ambiguous denominators.
        source = current.evidence.get('counter_source')
        if source not in ('client_table', 'demo') or previous.evidence.get('counter_source') != source:
            return None
        for name in ('mac','ap_name','bssid','md'):
            old, new = getattr(previous, name), getattr(current, name)
            if old is None or new is None or old != new:
                return None
        if any(x is None for x in (previous.retries, current.retries, previous.tx_packets, current.tx_packets)):
            return None
        try:
            elapsed = (datetime.fromisoformat(current.collected_at) - datetime.fromisoformat(previous.collected_at)).total_seconds()
        except (TypeError, ValueError):
            return None
        if not 0 < elapsed <= 120:
            return None
        packets = current.tx_packets - previous.tx_packets
        retries = current.retries - previous.retries
        if packets <= 0 or retries < 0 or retries > packets:
            return None
        # Ratio of counter deltas, not measured RF packet loss.
        return round(100 * retries / packets, 2)
