"""Run one owned frozen EXE with synthetic targets; record local soak evidence.

No third-party modules, device access, UI automation, or system setting changes.
Example: python scripts/run_windows_soak.py --exe <snapshot.exe> --directory <new-run-folder>
Short runs are rehearsals; only >=28800 real seconds can qualify as an eight-hour pass.
Resource thresholds are conservative screening, not a proof of absence of leaks.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import math
import os
import statistics
import subprocess
import time
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

EIGHT_HOURS = 28800
PROGRESS_TIMEOUT_SECONDS = 60
PERMISSION_RETRY_SECONDS = 1.0
PERMISSION_MAX_ATTEMPTS = 51
THRESHOLDS = {'private_bytes_absolute': 64 * 1024 * 1024, 'private_bytes_ratio': 0.25,
              'handles': 50, 'threads': 4}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def retry_permission(operation):
    """Windows readers/atomic renames can briefly deny access; never retry forever."""
    deadline = time.monotonic() + PERMISSION_RETRY_SECONDS
    for attempt in range(1, PERMISSION_MAX_ATTEMPTS + 1):
        try:
            return operation()
        except PermissionError as error:
            remaining = deadline - time.monotonic()
            if attempt == PERMISSION_MAX_ATTEMPTS or remaining <= 0:
                error.soak_io_attempts = attempt
                raise
            time.sleep(min(.02, remaining))


def atomic_json(path: Path, value: dict):
    temporary = path.with_suffix(path.suffix + '.tmp')
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    retry_permission(lambda: temporary.write_text(payload, encoding='utf-8'))
    retry_permission(lambda: temporary.replace(path))


def read_json_object(path: Path):
    def reject_constant(value):
        raise ValueError('NONFINITE_JSON')

    value = json.loads(retry_permission(lambda: path.read_text(encoding='utf-8')), parse_constant=reject_constant)
    if not isinstance(value, dict):
        raise ValueError('JSON_OBJECT_REQUIRED')
    return value


def child_environment(directory: Path, original=None, *, headless=False):
    original = os.environ if original is None else original
    env = {key: value for key, value in original.items() if not key.upper().startswith('PYTHON')
           and key.upper() not in {'QT_QPA_PLATFORM', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'}}
    env['PATH'] = env.get('SystemRoot', r'C:\Windows') + r'\System32'
    env['TEMP'] = env['TMP'] = str(directory / '임시')
    if headless:
        env['QT_QPA_PLATFORM'] = 'offscreen'
    return env


def classify_resources(samples: list[dict], seconds: int, interval: float):
    """Compare medians after declared warmup against the final observation window."""
    fields = ('elapsed_seconds', 'private_bytes', 'working_set_bytes', 'handles', 'threads')
    valid = [sample for sample in samples if isinstance(sample, dict) and all(
        isinstance(sample.get(field), (int, float)) and math.isfinite(sample[field]) and sample[field] >= 0
        for field in fields)]
    invalid = len(valid) != len(samples)
    samples = valid
    warmup = min(600.0, seconds * .2)
    window = min(300.0, max(interval * 3, seconds * .05))
    if seconds < 600:
        window = max(interval, seconds * .25)
    baseline = [s for s in samples if warmup <= s['elapsed_seconds'] <= warmup + window]
    final = [s for s in samples if s['elapsed_seconds'] >= seconds - window]
    failures = ['RESOURCE_SAMPLE_INVALID'] if invalid else []
    required = max(2, math.floor(seconds / interval * .9))
    minimum_window = 3 if seconds >= 600 else 1
    gaps = [b['elapsed_seconds'] - a['elapsed_seconds'] for a, b in zip(samples, samples[1:])]
    if (len(samples) < required or len(baseline) < minimum_window or len(final) < minimum_window
            or any(gap <= 0 or gap > interval * 3 for gap in gaps)):
        failures.append('RESOURCE_SAMPLES_INCOMPLETE')
    report = dict(warmup_seconds=warmup, comparison_window_seconds=window, sample_count=len(samples),
                  required_samples=required, baseline_sample_count=len(baseline),
                  final_sample_count=len(final), thresholds=THRESHOLDS.copy(), failures=failures)
    if baseline and final:
        medians = {label: {field: statistics.median(s[field] for s in selected)
                          for field in ('private_bytes', 'working_set_bytes', 'handles', 'threads')}
                   for label, selected in (('baseline', baseline), ('final', final))}
        report.update(medians)
        before, after = medians['baseline'], medians['final']
        growth = {field: after[field] - before[field] for field in before}
        report['growth'] = growth
        if (growth['private_bytes'] > THRESHOLDS['private_bytes_absolute']
                and growth['private_bytes'] > before['private_bytes'] * THRESHOLDS['private_bytes_ratio']):
            failures.append('PRIVATE_BYTES_GROWTH')
        if growth['handles'] > THRESHOLDS['handles']:
            failures.append('HANDLE_GROWTH')
        if growth['threads'] > THRESHOLDS['threads']:
            failures.append('THREAD_GROWTH')
    return report


def assess_run(final, samples, *, seconds, sample_interval, wall_seconds, exit_code,
               progress_identity, errors=(), headless=False):
    """Pure fail-closed qualification; never substitute app intent for elapsed evidence."""
    failures = list(errors)
    if headless and seconds >= EIGHT_HOURS:
        failures.append('NATIVE_GUI_REQUIRED')
    resources = classify_resources(samples, seconds, sample_interval)
    failures.extend(resources['failures'])
    if exit_code != 0:
        failures.append('PROCESS_EXIT_FAILED')
    if wall_seconds < seconds:
        failures.append('WALL_DURATION_SHORT')
    if not isinstance(final, dict):
        failures.append('RESULT_MISSING')
    else:
        if final.get('success') is not True:
            failures.append('APP_FAILED')
        if final.get('requested_seconds') != seconds:
            failures.append('REQUEST_MISMATCH')
        elapsed = final.get('elapsed_seconds')
        if not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < seconds:
            failures.append('APP_DURATION_SHORT')
        runtime = final.get('runtime')
        if (not isinstance(runtime, dict) or runtime.get('mode') != 'frozen'
                or not isinstance(runtime.get('version'), str) or not runtime['version']
                or not isinstance(runtime.get('build_id'), str) or not runtime['build_id']
                or 'unavailable' in runtime.get('build_id', '')):
            failures.append('RUNTIME_NOT_FROZEN')
        if (not progress_identity or not progress_identity.get('run_id')
                or final.get('run_id') != progress_identity.get('run_id')):
            failures.append('RUN_ID_MISMATCH')
        if not progress_identity or runtime != progress_identity.get('runtime'):
            failures.append('RUNTIME_IDENTITY_CHANGED')
        if final.get('db_integrity') != 'ok':
            failures.append('DB_INTEGRITY_FAILED')
        if final.get('unclosed_sessions') != 0:
            failures.append('UNCLOSED_SESSIONS')
        if final.get('target_count') != 10 or final.get('independent_macs') != 10:
            failures.append('TARGETS_INCOMPLETE')
        if final.get('qt_platform') != ('offscreen' if headless else 'windows'):
            failures.append('QT_PLATFORM_MISMATCH')
        freshness = ('max_collection_gap_seconds', 'persisted_max_gap_seconds',
                     'persisted_start_gap_seconds', 'persisted_end_gap_seconds')
        if any(not isinstance(final.get(field), (int, float)) or not math.isfinite(final[field])
               or not 0 <= final[field] <= 30 for field in freshness):
            failures.append('COLLECTION_FRESHNESS_FAILED')
        count = final.get('heartbeat_count', 0)
        gap = final.get('max_heartbeat_gap_seconds', math.inf)
        if not isinstance(count, int) or count < max(1, math.floor(seconds * .8)):
            failures.append('HEARTBEAT_INCOMPLETE')
        if not isinstance(gap, (int, float)) or not math.isfinite(gap) or gap > 15:
            failures.append('HEARTBEAT_STALLED')
        observations = final.get('target_observations')
        expected_minimum = max(1, int(seconds / 10 * .8))
        minimum = final.get('required_observations_per_target', expected_minimum)
        if (not isinstance(minimum, int) or minimum < 1 or not isinstance(observations, dict)
                or len(observations) != 10
                or any(not isinstance(n, int) or n < max(minimum, expected_minimum)
                       for n in observations.values())):
            failures.append('OBSERVATIONS_INCOMPLETE')
    success = not failures
    short_label = 'headless-short-rehearsal-passed' if headless else 'short-rehearsal-passed'
    return dict(success=success, eight_hour_passed=success and seconds >= EIGHT_HOURS,
                qualification=('eight-hour-passed' if seconds >= EIGHT_HOURS else short_label)
                if success else 'failed', failures=list(dict.fromkeys(failures)), resources=resources)


class WindowsSampler:
    """Read native counters for a PID supplied immediately after creating our child."""

    def __init__(self, pid):
        if os.name != 'nt':
            raise OSError('WINDOWS_REQUIRED')
        self.pid = pid
        self.closed = False
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.kernel.OpenProcess.restype = wintypes.HANDLE
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel.CloseHandle.restype = wintypes.BOOL
        self.handle = self.kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        if not self.closed:
            self.kernel.CloseHandle(self.handle)
            self.closed = True

    def sample(self):
        size_t = ctypes.c_size_t

        class Memory(ctypes.Structure):
            _fields_ = [('cb', wintypes.DWORD), ('PageFaultCount', wintypes.DWORD),
                        ('PeakWorkingSetSize', size_t), ('WorkingSetSize', size_t),
                        ('QuotaPeakPagedPoolUsage', size_t), ('QuotaPagedPoolUsage', size_t),
                        ('QuotaPeakNonPagedPoolUsage', size_t), ('QuotaNonPagedPoolUsage', size_t),
                        ('PagefileUsage', size_t), ('PeakPagefileUsage', size_t), ('PrivateUsage', size_t)]

        memory = Memory()
        memory.cb = ctypes.sizeof(memory)
        memory_info = self.kernel.K32GetProcessMemoryInfo
        memory_info.argtypes = [wintypes.HANDLE, ctypes.POINTER(Memory), wintypes.DWORD]
        memory_info.restype = wintypes.BOOL
        if not memory_info(self.handle, ctypes.byref(memory), memory.cb):
            raise ctypes.WinError(ctypes.get_last_error())
        handles = wintypes.DWORD()
        handle_count = self.kernel.GetProcessHandleCount
        handle_count.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        handle_count.restype = wintypes.BOOL
        if not handle_count(self.handle, ctypes.byref(handles)):
            raise ctypes.WinError(ctypes.get_last_error())
        return dict(private_bytes=memory.PrivateUsage, working_set_bytes=memory.WorkingSetSize,
                    handles=handles.value, threads=self.thread_count())

    def thread_count(self):
        class Thread(ctypes.Structure):
            _fields_ = [('dwSize', wintypes.DWORD), ('cntUsage', wintypes.DWORD),
                        ('th32ThreadID', wintypes.DWORD), ('th32OwnerProcessID', wintypes.DWORD),
                        ('tpBasePri', wintypes.LONG), ('tpDeltaPri', wintypes.LONG), ('dwFlags', wintypes.DWORD)]

        snapshot = self.kernel.CreateToolhelp32Snapshot
        snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        snapshot.restype = wintypes.HANDLE
        handle = snapshot(4, 0)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            first, following = self.kernel.Thread32First, self.kernel.Thread32Next
            for function in (first, following):
                function.argtypes = [wintypes.HANDLE, ctypes.POINTER(Thread)]
                function.restype = wintypes.BOOL
            entry = Thread()
            entry.dwSize = ctypes.sizeof(entry)
            if not first(handle, ctypes.byref(entry)):
                raise ctypes.WinError(ctypes.get_last_error())
            count = 0
            while True:
                count += entry.th32OwnerProcessID == self.pid
                if not following(handle, ctypes.byref(entry)):
                    if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                        raise ctypes.WinError(ctypes.get_last_error())
                    break
            if not count:
                raise OSError('OWNED_PROCESS_HAS_NO_THREADS')
            return count
        finally:
            self.kernel.CloseHandle(handle)


def run(args):
    if os.name != 'nt':
        raise ValueError('WINDOWS_REQUIRED')
    exe = args.exe.resolve(strict=True)
    if not exe.is_file() or exe.suffix.lower() != '.exe':
        raise ValueError('FROZEN_EXE_REQUIRED')
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=False)  # Never reuse or overwrite any run directory.
    (directory / '임시').mkdir()
    result_path = directory / 'result.json'
    progress_path = result_path.with_suffix('.progress.json')
    summary_path = directory / 'summary.json'
    command = [str(exe), '--multi-demo', '--soak-seconds', str(args.seconds),
               '--data-dir', str(directory / 'data'), '--smoke-result', str(result_path)]
    with exe.open('rb') as executable_file:
        digest = hashlib.file_digest(executable_file, 'sha256').hexdigest()
    summary = dict(status='starting', success=False, eight_hour_passed=False, qualification='incomplete',
                   started_at=utc_now(), executable=str(exe), executable_sha256=digest,
                   executable_size=exe.stat().st_size, requested_seconds=args.seconds,
                   sample_interval_seconds=args.sample_interval, headless=args.headless,
                   qt_platform='offscreen' if args.headless else 'windows', command=command,
                   resource_policy=dict(warmup_seconds=min(600, args.seconds * .2), thresholds=THRESHOLDS))
    atomic_json(summary_path, summary)
    process = None
    sampler = None
    samples, errors = [], []
    identity = None
    final = None
    started = time.monotonic()
    last_progress = started
    previous_heartbeat = -1
    previous_elapsed = -1
    stage = 'PROCESS_LAUNCH'
    try:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0  # Background launch, retaining the native Windows Qt platform.
        with (directory / 'stdout.log').open('xb') as stdout, (directory / 'stderr.log').open('xb') as stderr:
            process = subprocess.Popen(command, cwd=directory, env=child_environment(directory, headless=args.headless),
                                       stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                                       startupinfo=startup, creationflags=subprocess.CREATE_NO_WINDOW)
        summary.update(status='running', pid=process.pid)
        stage = 'SUMMARY_WRITE'
        atomic_json(summary_path, summary)
        stage = 'RESOURCE_OPEN'
        sampler = WindowsSampler(process.pid)
        next_sample = started
        with (directory / 'resources.jsonl').open('x', encoding='utf-8') as stream:
            while process.poll() is None:
                now = time.monotonic()
                if now - started > args.seconds + 120:
                    errors.append('PROCESS_TIMEOUT')
                    break
                stage = 'PROGRESS_READ'
                try:
                    progress = read_json_object(progress_path)
                except FileNotFoundError:
                    progress = None  # Startup or replacement race; watchdog is not extended.
                if progress is not None:
                    current_identity = {key: progress.get(key) for key in ('run_id', 'runtime')}
                    if not current_identity['run_id'] or not isinstance(current_identity['runtime'], dict):
                        raise ValueError('PROGRESS_IDENTITY_INVALID')
                    if identity is None:
                        identity = current_identity
                        summary['progress_identity'] = identity
                    elif identity != current_identity:
                        raise ValueError('PROGRESS_IDENTITY_CHANGED')
                    heartbeat = progress['heartbeat_count']
                    elapsed = progress['elapsed_seconds']
                    # Content is the version. An mtime read before atomic replacement
                    # can belong to a different generation than the JSON body.
                    if (heartbeat, elapsed) != (previous_heartbeat, previous_elapsed):
                        if heartbeat <= previous_heartbeat or elapsed <= previous_elapsed:
                            raise ValueError('PROGRESS_NOT_ADVANCING')
                        previous_heartbeat, previous_elapsed = heartbeat, elapsed
                        last_progress = now
                        summary['last_progress'] = progress
                if now - last_progress > PROGRESS_TIMEOUT_SECONDS:
                    errors.append('PROGRESS_STALE')
                    break
                if now >= next_sample:
                    stage = 'RESOURCE_SAMPLE'
                    try:
                        sample = sampler.sample()
                    except OSError:
                        if process.poll() is not None:  # Normal exit racing a scheduled sample.
                            break
                        raise
                    sample.update(elapsed_seconds=now - started, observed_at=utc_now(), pid=process.pid)
                    samples.append(sample)
                    stream.write(json.dumps(sample, allow_nan=False) + '\n')
                    stream.flush()
                    summary.update(sample_count=len(samples), elapsed_seconds=now - started,
                                   last_sample=sample, updated_at=utc_now())
                    stage = 'SUMMARY_WRITE'
                    atomic_json(summary_path, summary)
                    next_sample += args.sample_interval
                time.sleep(.25)
        if errors and process.poll() is None:
            process.kill()  # Exact Popen child only; never a process-name or global taskkill.
        process.wait(timeout=10)
        if result_path.exists():
            stage = 'RESULT_READ'
            final = read_json_object(result_path)
    except KeyboardInterrupt:
        errors.append('RUN_INTERRUPTED')
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as exc:
        errors.append(f'SAMPLER_ERROR:{type(exc).__name__}')
        # Error categories deliberately omit exception messages containing local paths/data.
        summary['error_context'] = dict(stage=stage, type=type(exc).__name__,
                                        errno=getattr(exc, 'errno', None), winerror=getattr(exc, 'winerror', None),
                                        attempts=getattr(exc, 'soak_io_attempts', 1))
    finally:
        if sampler:
            sampler.close()
        if process:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process._handle.Close()  # Popen owns a separate Windows process handle.
    wall_seconds = time.monotonic() - started
    summary.update(assess_run(final, samples, seconds=args.seconds, sample_interval=args.sample_interval,
                              wall_seconds=wall_seconds, exit_code=process.returncode if process else None,
                              progress_identity=identity, errors=errors, headless=args.headless))
    summary.update(status='completed' if summary['success'] else 'failed', finished_at=utc_now(),
                   wall_seconds=wall_seconds, exit_code=process.returncode if process else None,
                   app_result=final)
    atomic_json(summary_path, summary)
    return 0 if summary['success'] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe', type=Path, required=True)
    parser.add_argument('--directory', type=Path, required=True, help='New directory; existing paths are rejected')
    parser.add_argument('--seconds', type=int, default=EIGHT_HOURS)
    parser.add_argument('--sample-interval', type=float, default=10)
    parser.add_argument('--headless', action='store_true', help='Offscreen rehearsal; default uses native Qt Windows')
    args = parser.parse_args(argv)
    if not 1 <= args.seconds <= 86400:
        parser.error('--seconds must be 1..86400')
    if not math.isfinite(args.sample_interval) or not .1 <= args.sample_interval <= 30:
        parser.error('--sample-interval must be .1..30 seconds')
    try:
        return run(args)
    except (OSError, ValueError) as exc:
        parser.error(f'Cannot start a new isolated Windows run ({type(exc).__name__})')


if __name__ == '__main__':
    raise SystemExit(main())
