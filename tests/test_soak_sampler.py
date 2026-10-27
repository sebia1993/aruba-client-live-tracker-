"""Fail-closed evidence qualification and real owned Windows process sampling."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest


def load_sampler():
    path = Path(__file__).parents[1] / 'scripts' / 'run_windows_soak.py'
    assert path.exists(), 'external Windows soak sampler is missing'
    spec = importlib.util.spec_from_file_location('soak_sampler', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def resource_samples(seconds=28800, interval=10):
    return [dict(elapsed_seconds=t, private_bytes=100_000_000, working_set_bytes=80_000_000,
                 handles=200, threads=12) for t in range(0, seconds, interval)]


def result(seconds=28800):
    return dict(success=True, run_id='test-run', runtime=dict(mode='frozen', version='0.3.7',
                build_id='0.3.7-abcdef123456'), elapsed_seconds=seconds, requested_seconds=seconds,
                heartbeat_count=seconds, max_heartbeat_gap_seconds=1.1, target_count=10,
                qt_platform='windows', max_collection_gap_seconds=10,
                persisted_max_gap_seconds=10, persisted_start_gap_seconds=1,
                persisted_end_gap_seconds=1,
                independent_macs=10, db_integrity='ok', unclosed_sessions=0,
                required_observations_per_target=1,
                target_observations={str(i): seconds // 10 for i in range(10)})


def qualify(module, *, final=None, samples=None, seconds=28800, **kwargs):
    return module.assess_run(result() if final is None else final,
                             resource_samples() if samples is None else samples,
                             seconds=seconds, sample_interval=10, wall_seconds=seconds + 3,
                             exit_code=0, progress_identity=dict(run_id='test-run', runtime=result()['runtime']),
                             **kwargs)


def test_full_duration_requires_complete_frozen_evidence():
    report = qualify(load_sampler())
    assert report['success'] is True
    assert report['eight_hour_passed'] is True
    assert report['qualification'] == 'eight-hour-passed'


@pytest.mark.parametrize(('field', 'bad', 'reason'), [
    ('success', False, 'APP_FAILED'), ('elapsed_seconds', 28798, 'APP_DURATION_SHORT'),
    ('requested_seconds', 30, 'REQUEST_MISMATCH'), ('run_id', 'another', 'RUN_ID_MISMATCH'),
    ('db_integrity', 'corrupt', 'DB_INTEGRITY_FAILED'), ('unclosed_sessions', 1, 'UNCLOSED_SESSIONS'),
    ('target_count', 9, 'TARGETS_INCOMPLETE'), ('independent_macs', 9, 'TARGETS_INCOMPLETE'),
    ('heartbeat_count', 1, 'HEARTBEAT_INCOMPLETE'), ('max_heartbeat_gap_seconds', 61, 'HEARTBEAT_STALLED'),
    ('target_observations', {}, 'OBSERVATIONS_INCOMPLETE'),
])
def test_incomplete_evidence_never_passes(field, bad, reason):
    evidence = result()
    evidence[field] = bad
    report = qualify(load_sampler(), final=evidence)
    assert report['success'] is False
    assert reason in report['failures']


@pytest.mark.parametrize('runtime', [dict(mode='source', version='0.3.7', build_id='source'),
                                      dict(mode='frozen', version='changed', build_id='changed'),
                                      dict(mode='frozen', version='0.3.7', build_id=42)])
def test_runtime_identity_cannot_change(runtime):
    final = result()
    final['runtime'] = runtime
    assert qualify(load_sampler(), final=final)['success'] is False


def test_missing_result_or_sparse_resource_samples_fail_closed():
    module = load_sampler()
    assert module.assess_run(None, [], seconds=28800, sample_interval=10,
                             wall_seconds=2, exit_code=0, progress_identity=None)['success'] is False
    report = qualify(module, samples=resource_samples()[::4])
    assert 'RESOURCE_SAMPLES_INCOMPLETE' in report['failures']


def test_short_rehearsal_is_never_eight_hour_pass():
    report = qualify(load_sampler(), final=result(40), samples=resource_samples(40), seconds=40)
    assert report['success'] is True
    assert report['eight_hour_passed'] is False
    assert report['qualification'] == 'short-rehearsal-passed'


def test_headless_long_run_cannot_qualify_native_eight_hour_requirement():
    report = qualify(load_sampler(), headless=True)
    assert report['success'] is False
    assert report['eight_hour_passed'] is False
    assert 'NATIVE_GUI_REQUIRED' in report['failures']


def test_headless_short_rehearsal_is_clearly_labelled():
    final = result(40)
    final['qt_platform'] = 'offscreen'
    report = qualify(load_sampler(), final=final, samples=resource_samples(40), seconds=40, headless=True)
    assert report['success'] is True
    assert report['qualification'] == 'headless-short-rehearsal-passed'
    assert report['eight_hour_passed'] is False


@pytest.mark.parametrize('field', ['max_collection_gap_seconds', 'persisted_max_gap_seconds',
                                   'persisted_start_gap_seconds', 'persisted_end_gap_seconds'])
@pytest.mark.parametrize('bad', [None, float('nan'), float('inf'), -1, 30.01])
def test_missing_stale_or_invalid_collection_freshness_never_passes(field, bad):
    final = result()
    final[field] = bad
    report = qualify(load_sampler(), final=final)
    assert report['success'] is False
    assert 'COLLECTION_FRESHNESS_FAILED' in report['failures']


@pytest.mark.parametrize('platform', [None, 'offscreen', 'minimal'])
def test_native_evidence_requires_windows_qt_platform(platform):
    final = result()
    final['qt_platform'] = platform
    report = qualify(load_sampler(), final=final)
    assert 'QT_PLATFORM_MISMATCH' in report['failures']


@pytest.mark.parametrize(('field', 'increment', 'failure'), [
    ('private_bytes', 80_000_000, 'PRIVATE_BYTES_GROWTH'),
    ('handles', 51, 'HANDLE_GROWTH'), ('threads', 5, 'THREAD_GROWTH'),
])
def test_sustained_growth_after_warmup_is_reported(field, increment, failure):
    samples = resource_samples()
    for sample in samples:
        if sample['elapsed_seconds'] >= 28000:
            sample[field] += increment
    report = qualify(load_sampler(), samples=samples)
    assert report['success'] is False
    assert failure in report['failures']


def test_startup_growth_and_small_allocator_drift_are_not_leaks():
    samples = resource_samples()
    for sample in samples:
        if sample['elapsed_seconds'] < 500:
            sample['private_bytes'] = 10_000_000
        if sample['elapsed_seconds'] > 28000:
            sample['private_bytes'] += 40_000_000
    assert qualify(load_sampler(), samples=samples)['success'] is True


def test_observation_minimum_cannot_be_lowered_by_the_app_result():
    final = result()
    final['required_observations_per_target'] = 1
    final['target_observations'] = {str(i): 1 for i in range(10)}
    report = qualify(load_sampler(), final=final)
    assert 'OBSERVATIONS_INCOMPLETE' in report['failures']


@pytest.mark.parametrize('field', ['private_bytes', 'working_set_bytes', 'handles', 'threads'])
def test_nonfinite_resource_metrics_fail_closed(field):
    samples = resource_samples()
    samples[-1][field] = float('nan')
    assert 'RESOURCE_SAMPLE_INVALID' in qualify(load_sampler(), samples=samples)['failures']


def test_child_environment_isolated_without_mutating_parent(tmp_path):
    module = load_sampler()
    source = {'PATH': 'unsafe', 'PYTHONPATH': 'unsafe', 'PYTHONHOME': 'unsafe',
              'QT_QPA_PLATFORM': 'offscreen', 'SystemRoot': r'C:\Windows', 'KEEP': 'yes'}
    env = module.child_environment(tmp_path, source, headless=False)
    assert env['PATH'] == r'C:\Windows\System32'
    assert not any(key.upper().startswith('PYTHON') for key in env)
    assert 'QT_QPA_PLATFORM' not in env
    assert env['TEMP'] == str(tmp_path / '임시')
    assert source['PATH'] == 'unsafe'
    assert module.child_environment(tmp_path, source, headless=True)['QT_QPA_PLATFORM'] == 'offscreen'


@pytest.mark.skipif(os.name != 'nt', reason='Windows native metrics only')
def test_native_sampler_reads_and_closes_only_owned_child():
    module = load_sampler()
    with subprocess.Popen([sys.executable, '-I', '-c', 'import time; time.sleep(15)']) as child:
        try:
            with module.WindowsSampler(child.pid) as sampler:
                sample = sampler.sample()
                assert sample['private_bytes'] > 0
                assert sample['working_set_bytes'] > 0
                assert sample['handles'] > 0
                assert sample['threads'] >= 1
            assert sampler.closed
            assert child.poll() is None
        finally:
            child.terminate()
            child.wait(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows runner only')
def test_runner_records_real_child_early_exit_without_claiming_pass(tmp_path):
    module = load_sampler()
    run_dir = tmp_path / '조기 종료'
    code = module.main(['--exe', sys.executable, '--directory', str(run_dir), '--seconds', '40'])
    import json
    summary = json.loads((run_dir / 'summary.json').read_text(encoding='utf-8'))
    assert code == 1
    assert summary['status'] == 'failed'
    assert summary['eight_hour_passed'] is False
    assert 'RESULT_MISSING' in summary['failures']
    assert summary['executable_sha256'] and summary['executable_size'] > 0
    assert summary['pid'] > 0
    assert summary['qt_platform'] == 'windows'


def test_existing_directory_is_preserved_and_no_child_started(tmp_path):
    module = load_sampler()
    existing = tmp_path / 'existing'
    existing.mkdir()
    sentinel = existing / 'keep.txt'
    sentinel.write_text('keep')
    with pytest.raises(SystemExit):
        module.main(['--exe', sys.executable, '--directory', str(existing), '--seconds', '5'])
    assert list(existing.iterdir()) == [sentinel]
    assert sentinel.read_text() == 'keep'


@pytest.mark.skipif(os.name != 'nt', reason='Windows runner only')
def test_stale_progress_kills_only_owned_child_and_records_failure(tmp_path, monkeypatch):
    """A real isolated sleeping child replaces only the external frozen-EXE boundary."""
    import json
    module = load_sampler()
    real_popen = subprocess.Popen
    children = []

    def fixture_child(command, **options):
        child = real_popen([sys.executable, '-I', '-c', 'import time; time.sleep(2.5)'], **options)
        children.append(child)
        return child

    companion = real_popen([sys.executable, '-I', '-c', 'import time; time.sleep(15)'])
    try:
        monkeypatch.setattr(module.subprocess, 'Popen', fixture_child)
        monkeypatch.setattr(module, 'PROGRESS_TIMEOUT_SECONDS', .1, raising=False)
        directory = tmp_path / 'stale'
        assert module.main(['--exe', sys.executable, '--directory', str(directory), '--seconds', '10']) == 1
        summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
        assert 'PROGRESS_STALE' in summary['failures']
        assert summary['wall_seconds'] < 2
        assert children[0].returncode is not None
        assert companion.poll() is None
    finally:
        companion.terminate()
        companion.wait(timeout=5)


@pytest.mark.skipif(os.name != 'nt', reason='Windows runner only')
def test_native_read_error_is_recorded_and_child_is_reaped(tmp_path, monkeypatch):
    import json
    module = load_sampler()
    real_popen = subprocess.Popen
    children = []

    def fixture_child(command, **options):
        child = real_popen([sys.executable, '-I', '-c', 'import time; time.sleep(5)'], **options)
        children.append(child)
        return child

    def fail_read(self):
        raise OSError('simulated read failure')

    monkeypatch.setattr(module.subprocess, 'Popen', fixture_child)
    monkeypatch.setattr(module.WindowsSampler, 'sample', fail_read)
    directory = tmp_path / 'read-error'
    assert module.main(['--exe', sys.executable, '--directory', str(directory), '--seconds', '10']) == 1
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    assert 'SAMPLER_ERROR:OSError' in summary['failures']
    assert children[0].returncode is not None


@pytest.mark.skipif(os.name != 'nt', reason='Windows runner only')
def test_nonfinite_progress_still_writes_failure_summary(tmp_path, monkeypatch):
    import json
    module = load_sampler()
    real_popen = subprocess.Popen
    progress = dict(run_id='invalid-json', runtime=result()['runtime'],
                    heartbeat_count=1, elapsed_seconds=float('nan'))

    def fixture_child(command, **options):
        progress_path = str(Path(command[command.index('--smoke-result') + 1]).with_suffix('.progress.json'))
        script = ('import sys,time; from pathlib import Path; '
                  'Path(sys.argv[1]).write_text(sys.argv[2],encoding="utf-8"); time.sleep(3)')
        return real_popen([sys.executable, '-I', '-c', script, progress_path, json.dumps(progress)], **options)

    monkeypatch.setattr(module.subprocess, 'Popen', fixture_child)
    directory = tmp_path / 'nonfinite-progress'
    assert module.main(['--exe', sys.executable, '--directory', str(directory), '--seconds', '10']) == 1
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    assert summary['status'] == 'failed'
    assert 'SAMPLER_ERROR:ValueError' in summary['failures']
