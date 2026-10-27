from dataclasses import replace

from aruba_client_live_tracker.models import Observation, Outcome, PollResult
from aruba_client_live_tracker.tracker import Tracker


def observed(**kw):
    defaults = dict(mac='02:00:00:00:00:01', ip='192.0.2.100', ap_name='LAB-AP-A', bssid='02:00:00:00:01:01', md='LAB-MD-A', snr=35, tx_rate=400, rx_rate=300, tx_packets=1000, retries=10, role='employee', vlan='100', evidence={'counter_source': 'client_table'})
    defaults.update(kw)
    return Observation(**defaults)


def ok(obs):
    return PollResult(Outcome.OK, obs, collected_at=obs.collected_at)


def kinds(view):
    return {e.kind for e in view.events}


def test_failure_preserves_value_and_never_disconnects_or_roams():
    tracker = Tracker()
    first = tracker.apply(ok(observed()))
    assert 'connected' in kinds(first)
    failed = tracker.apply(PollResult(Outcome.ERROR, error='MD 조회 실패'))
    assert failed.stale and failed.observation.ap_name == 'LAB-AP-A'
    assert kinds(failed) == {'collection_failed'}
    recovered = tracker.apply(ok(observed(ap_name='LAB-AP-B')))
    assert 'collection_recovered' in kinds(recovered)
    assert 'roam' not in kinds(recovered)


def test_disconnect_needs_two_complete_absences_and_error_breaks_evidence():
    tracker = Tracker()
    tracker.apply(ok(observed()))
    assert tracker.apply(PollResult(Outcome.ABSENT)).state == '미접속 확인 중'
    tracker.apply(PollResult(Outcome.ERROR, error='MM 응답 없음'))
    assert 'disconnected' not in kinds(tracker.apply(PollResult(Outcome.ABSENT)))
    disconnected = tracker.apply(PollResult(Outcome.ABSENT))
    assert disconnected.state == '연결 해제'
    assert 'disconnected' in kinds(disconnected)
    reconnected = tracker.apply(ok(observed()))
    assert 'reconnected' in kinds(reconnected)
    assert 'roam' not in kinds(reconnected)


def test_consecutive_roam_captures_before_after():
    tracker = Tracker()
    tracker.apply(ok(observed()))
    changed = tracker.apply(ok(observed(ap_name='LAB-AP-B', bssid='02:00:00:00:01:02', snr=18, role='guest', vlan='200')))
    assert {'roam', 'role_changed', 'vlan_changed', 'snr_low'} <= kinds(changed)
    event = next(e for e in changed.events if e.kind == 'roam')
    assert event.facts['previous_ap'] == 'LAB-AP-A'
    assert event.facts['snr_before'] == 35 and event.facts['snr_after'] == 18
    assert changed.previous_ap == 'LAB-AP-A'


def test_retry_delta_resets_on_ap_error_counter_reset_or_gap():
    first = observed(collected_at='2026-01-01T00:00:00+00:00')
    second = replace(first, collected_at='2026-01-01T00:00:15+00:00', tx_packets=1100, retries=20)
    tracker = Tracker()
    tracker.apply(ok(first))
    assert tracker.apply(ok(second)).observation.retry_pct == 10.0
    for change in [dict(ap_name='LAB-AP-B'), dict(tx_packets=50), dict(retries=1), dict(collected_at='2026-01-01T00:10:00+00:00')]:
        tracker = Tracker()
        tracker.apply(ok(first))
        assert tracker.apply(ok(replace(second, **change))).observation.retry_pct is None
    tracker.apply(PollResult(Outcome.ERROR))
    assert tracker.apply(ok(second)).observation.retry_pct is None


def test_auth_ip_rate_md_changes_and_reset():
    tracker = Tracker()
    tracker.apply(ok(observed(auth_method='802.1X', auth_result='성공')))
    view = tracker.apply(ok(observed(ip='192.0.2.101', md='LAB-MD-B', auth_method='MAC', auth_result='실패', tx_rate=20, rx_rate=10)))
    assert {'ip_changed','md_changed','auth_changed','rate_drop'} <= kinds(view)
    tracker.reset()
    assert tracker.apply(PollResult(Outcome.ERROR)).observation is None


def test_ambiguous_never_uses_arbitrary_candidate_or_false_recovery():
    tracker = Tracker()
    tracker.apply(ok(observed()))
    view = tracker.apply(PollResult(Outcome.AMBIGUOUS))
    assert view.stale and not view.events
    assert 'roam' not in kinds(tracker.apply(ok(observed(ap_name='LAB-AP-B'))))


def test_unknown_values_do_not_generate_changes_or_invent_retry():
    tracker = Tracker()
    tracker.apply(ok(observed(ap_name=None, role=None, snr=None, retries=None)))
    view = tracker.apply(ok(observed()))
    assert 'roam' not in kinds(view) and 'role_changed' not in kinds(view)
    assert view.observation.retry_pct is None


def test_partial_failure_preserves_individual_metric_with_age_but_not_change_baseline():
    tracker = Tracker()
    first = observed(evidence={'snr': '수집 시각 00:00:00'}, collected_at='2026-01-01T00:00:00+00:00')
    tracker.apply(ok(first))
    partial = tracker.apply(ok(observed(snr=None, field_status={'snr': '조회 실패'}, collected_at='2026-01-01T00:00:15+00:00')))
    assert partial.observation.snr == 35
    assert '이전 조회값' in partial.observation.field_status['snr']
    assert '00:00:00' in partial.observation.evidence['snr']
    recovered = tracker.apply(ok(observed(snr=12, collected_at='2026-01-01T00:00:30+00:00')))
    assert 'snr_low' not in kinds(recovered)


def test_unknown_association_does_not_claim_wireless_connection_or_roaming():
    tracker = Tracker()
    first = tracker.apply(ok(observed(field_status={'connected': '확인 불가'})))
    assert '확인 불가' in first.state
    assert 'connected' not in kinds(first)
    second = tracker.apply(ok(observed(ap_name='LAB-AP-B')))
    assert 'roam' not in kinds(second)


def test_mixed_counter_sources_never_compute_rate():
    tracker = Tracker()
    tracker.apply(ok(observed(collected_at='2026-01-01T00:00:00+00:00', evidence={'counter_source': 'client_stats'})))
    view = tracker.apply(ok(observed(collected_at='2026-01-01T00:00:15+00:00', retries=20, tx_packets=1100, evidence={'counter_source': 'client_table'})))
    assert view.observation.retry_pct is None


def test_partial_command_failure_and_recovery_events_are_not_repeated():
    tracker = Tracker()
    first = tracker.apply(ok(observed(field_status={'client_table': '조회 실패'})))
    assert 'field_collection_failed' in kinds(first)
    again = tracker.apply(ok(observed(field_status={'client_table': '조회 실패'})))
    assert 'field_collection_failed' not in kinds(again)
    restored = tracker.apply(ok(observed(field_status={'client_table': '정상'})))
    assert 'field_collection_recovered' in kinds(restored)
