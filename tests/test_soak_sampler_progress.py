"""Real Windows child/filesystem regressions for progress version handling.

Only the frozen EXE boundary is substituted with a small Python progress writer.
Native metrics, file I/O, sampler loop, result qualification and child cleanup stay real.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(os.name != 'nt', reason='Real Windows sampler/child boundary')

WRITER = r'''
import json, os, sys, time
from pathlib import Path
configuration = json.loads(sys.argv[1])
report = Path(configuration['report'])
progress = report.with_suffix('.progress.json')
started = time.monotonic()
for index, (deadline, body) in enumerate(configuration['publications']):
    time.sleep(max(0, deadline - (time.monotonic() - started)))
    temporary = progress.with_suffix('.tmp')
    temporary.write_text(json.dumps(body), encoding='utf-8')
    retry_until = time.monotonic() + 1
    while True:
        try:
            temporary.replace(progress)
            break
        except PermissionError:
            if time.monotonic() >= retry_until:
                raise
            time.sleep(.01)
    # A duplicate logical version deliberately receives a different physical file timestamp.
    stamp = time.time_ns() + index * 1000000
    os.utime(progress, ns=(stamp, stamp))
time.sleep(max(0, configuration['finish_at'] - (time.monotonic() - started)))
if configuration['final'] is not None:
    report.write_text(json.dumps(configuration['final']), encoding='utf-8')
'''


def load_sampler():
    path = Path(__file__).parents[1] / 'scripts' / 'run_windows_soak.py'
    spec = importlib.util.spec_from_file_location('soak_progress_regression', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def identity():
    return dict(mode='frozen', version='fixture', build_id='fixture-0123456789ab')


def progress(heartbeat, elapsed, **changes):
    body = dict(run_id='progress-fixture', runtime=identity(), heartbeat_count=heartbeat,
                elapsed_seconds=elapsed)
    body.update(changes)
    return body


def final_result():
    return dict(success=True, run_id='progress-fixture', runtime=identity(),
                elapsed_seconds=2.2, requested_seconds=2, heartbeat_count=3,
                max_heartbeat_gap_seconds=1, target_count=10, independent_macs=10,
                db_integrity='ok', unclosed_sessions=0, required_observations_per_target=1,
                target_observations={str(index): 1 for index in range(10)}, qt_platform='windows',
                max_collection_gap_seconds=1, persisted_max_gap_seconds=1,
                persisted_start_gap_seconds=1, persisted_end_gap_seconds=1)


def run_writer(tmp_path, monkeypatch, publications, *, finish_at=2.2, final=None, stale_after=60):
    module = load_sampler()
    real_popen = subprocess.Popen
    children = []

    def fixture_child(command, **options):
        report = command[command.index('--smoke-result') + 1]
        configuration = dict(report=report, publications=publications, finish_at=finish_at, final=final)
        child = real_popen([sys.executable, '-I', '-c', WRITER, json.dumps(configuration)], **options)
        children.append(child)
        return child

    monkeypatch.setattr(module.subprocess, 'Popen', fixture_child)
    monkeypatch.setattr(module, 'PROGRESS_TIMEOUT_SECONDS', stale_after)
    directory = tmp_path / '진행 상태 회귀'
    code = module.main(['--exe', sys.executable, '--directory', str(directory),
                        '--seconds', '2', '--sample-interval', '.25'])
    summary = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
    assert len(children) == 1
    assert children[0].returncode is not None, 'runner must reap its exact owned child'
    return code, summary


def test_same_progress_version_republished_with_new_mtime_can_complete(tmp_path, monkeypatch):
    first = progress(1, .05)
    publications = [(0.05, first), (.6, first), (1.1, progress(2, 1.1)), (1.6, progress(3, 1.6))]
    code, summary = run_writer(tmp_path, monkeypatch, publications, final=final_result())
    assert code == 0, summary['failures']
    assert summary['success'] is True
    assert summary['qualification'] == 'short-rehearsal-passed'
    assert summary['last_progress']['heartbeat_count'] == 3
    assert summary['eight_hour_passed'] is False


def test_duplicate_publications_do_not_extend_stale_watchdog(tmp_path, monkeypatch):
    first = progress(1, .05)
    publications = [(deadline, first) for deadline in (.05, .4, .8, 1.2, 1.6)]
    code, summary = run_writer(tmp_path, monkeypatch, publications, finish_at=3, stale_after=.7)
    assert code == 1
    assert 'PROGRESS_STALE' in summary['failures']
    assert summary['wall_seconds'] < 1.8, 'duplicate writes must not keep the run alive'


@pytest.mark.parametrize('changed', [
    progress(2, .6, run_id='another-run'),
    progress(2, .6, runtime=dict(mode='frozen', version='other', build_id='other-build')),
    progress(0, .6),
    progress(2, .01),
    progress(2, .05),
    progress(1, .6),
], ids=['run-id-change', 'runtime-change', 'heartbeat-backwards', 'elapsed-backwards',
        'only-heartbeat-advances', 'only-elapsed-advances'])
def test_identity_or_partial_progress_changes_fail_closed(tmp_path, monkeypatch, changed):
    publications = [(.05, progress(1, .05)), (.6, changed)]
    code, summary = run_writer(tmp_path, monkeypatch, publications, finish_at=2.2)
    assert code == 1
    assert any(failure.startswith('SAMPLER_ERROR:') for failure in summary['failures'])
    assert 'PROGRESS_STALE' not in summary['failures']
    assert summary['wall_seconds'] < 1.8, 'invalid progress must fail before ordinary child completion'
