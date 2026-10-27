"""Packaging exercises synthetic archives and isolated source trees."""
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def script_module(name):
    path = ROOT / 'scripts' / f'{name}.py'
    assert path.is_file(), f'Missing packaging helper: {name}'
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def source_bundle(monkeypatch):
    module = script_module('bundle_sources')
    content = b'synthetic complete corresponding source archive'
    monkeypatch.setattr(module, 'SOURCES', {
        'fixture.tar.xz': ('https://example.invalid/source', hashlib.sha256(content).hexdigest()),
    })
    return module, content


def test_corrupt_cached_source_is_downloaded_and_verified(tmp_path, monkeypatch):
    module, content = source_bundle(monkeypatch)
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'fixture.tar.xz').write_bytes(b'incomplete')
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(content))
    output = tmp_path / 'sources.zip'
    module.bundle(output, cache)
    assert (cache / 'fixture.tar.xz').read_bytes() == content
    with zipfile.ZipFile(output) as archive:
        assert archive.read('third-party-sources/fixture.tar.xz') == content
        manifest = json.loads(archive.read('third-party-sources/manifest.json'))
        assert manifest[0]['sha256'] == hashlib.sha256(content).hexdigest()
    assert output.with_suffix('.zip.sha256').read_text().split()[0] == hashlib.sha256(output.read_bytes()).hexdigest()


def test_interrupted_source_download_leaves_no_final_cache_file(tmp_path, monkeypatch):
    module, content = source_bundle(monkeypatch)

    class Interrupted(io.BytesIO):
        def read(self, size=-1):
            if self.tell():
                raise OSError('synthetic interrupted transfer')
            return super().read(8)

    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: Interrupted(content))
    cache = tmp_path / 'cache'
    with pytest.raises(OSError):
        module.bundle(tmp_path / 'first.zip', cache)
    assert not list(cache.iterdir())
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(content))
    module.bundle(tmp_path / 'retry.zip', cache)
    assert (cache / 'fixture.tar.xz').read_bytes() == content


def test_unverified_download_cannot_become_cached_source(tmp_path, monkeypatch):
    module, _ = source_bundle(monkeypatch)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'wrong bytes'))
    cache = tmp_path / 'cache'
    with pytest.raises(RuntimeError, match='checksum'):
        module.bundle(tmp_path / 'bad.zip', cache)
    assert not list(cache.iterdir())


def git(root, *arguments):
    return subprocess.run(['git', '-C', str(root), *arguments], check=True, capture_output=True)


def test_export_uses_tracked_public_files_and_archive_manifest(tmp_path):
    module = script_module('export_sources')
    source = tmp_path / 'checkout'
    source.mkdir()
    git(source, 'init')
    (source / 'src').mkdir()
    (source / 'docs').mkdir()
    (source / 'src' / 'app.py').write_text('print("synthetic")', encoding='utf-8')
    (source / 'README.md').write_text('Synthetic public documentation', encoding='utf-8')
    (source / '.gitignore').write_text('*.sqlite3\n*.log\n', encoding='utf-8')
    git(source, 'add', '.')
    (source / 'docs' / 'history.sqlite3').write_bytes(b'synthetic local history')
    (source / 'docs' / 'private.log').write_text('synthetic local diagnostics', encoding='utf-8')
    (source / 'docs' / 'untracked.md').write_text('synthetic unpublished draft', encoding='utf-8')
    output = tmp_path / 'SOURCE'
    module.export(source, output)
    assert (output / 'src' / 'app.py').read_bytes() == (source / 'src' / 'app.py').read_bytes()
    assert not (output / 'docs').exists()
    manifest = json.loads((output / 'source-manifest.json').read_text(encoding='utf-8'))
    assert 'src/app.py' in manifest['files']
    assert not any('history' in item or 'untracked' in item for item in manifest['files'])
    (output / 'src' / 'local.log').write_text('synthetic added runtime file', encoding='utf-8')
    rebuilt = tmp_path / 'REBUILT'
    module.export(output, rebuilt)
    assert (rebuilt / 'src' / 'app.py').read_bytes() == (source / 'src' / 'app.py').read_bytes()
    assert not (rebuilt / 'src' / 'local.log').exists()


@pytest.mark.parametrize('entry', ['../outside.txt', '/absolute.txt', 'docs/history.sqlite3', 'docs/known_hosts'])
def test_archive_manifest_cannot_export_outside_or_runtime_files(tmp_path, entry):
    module = script_module('export_sources')
    source = tmp_path / 'SOURCE'
    source.mkdir()
    (source / 'source-manifest.json').write_text(json.dumps({'version': 1, 'files': [entry]}), encoding='utf-8')
    with pytest.raises(ValueError):
        module.export(source, tmp_path / 'output')


def test_verified_cached_source_is_reused_without_network(tmp_path, monkeypatch):
    module, content = source_bundle(monkeypatch)
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'fixture.tar.xz').write_bytes(content)

    def unavailable(*args, **kwargs):
        raise OSError('offline synthetic fixture')

    monkeypatch.setattr(module.urllib.request, 'urlopen', unavailable)
    module.bundle(tmp_path / 'sources.zip', cache)
    with zipfile.ZipFile(tmp_path / 'sources.zip') as archive:
        assert archive.read('third-party-sources/fixture.tar.xz') == content


def test_failed_recovery_removes_bad_cache_and_preserves_existing_bundle(tmp_path, monkeypatch):
    module, _ = source_bundle(monkeypatch)
    cache = tmp_path / 'cache'
    cache.mkdir()
    (cache / 'fixture.tar.xz').write_bytes(b'previous interrupted transfer')
    output = tmp_path / 'sources.zip'
    output.write_bytes(b'previous valid release')
    digest = output.with_suffix('.zip.sha256')
    digest.write_bytes(b'previous digest')
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(b'bad'))
    with pytest.raises(RuntimeError, match='checksum'):
        module.bundle(output, cache)
    assert list(cache.iterdir()) == []
    assert output.read_bytes() == b'previous valid release'
    assert digest.read_bytes() == b'previous digest'
    assert sorted(path.name for path in tmp_path.iterdir()) == ['cache', 'sources.zip', 'sources.zip.sha256']


@pytest.mark.parametrize('existing', [False, True])
def test_checksum_publish_failure_restores_previous_bundle_pair(tmp_path, monkeypatch, existing):
    module, content = source_bundle(monkeypatch)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(content))
    output = tmp_path / 'sources.zip'
    checksum = output.with_suffix('.zip.sha256')
    if existing:
        output.write_bytes(b'previous verified ZIP')
        checksum.write_bytes(b'previous matching SHA256')
    replace = Path.replace

    def blocked_checksum_replace(path, target):
        if Path(target) == checksum:
            raise PermissionError('synthetic locked checksum')
        return replace(path, target)

    monkeypatch.setattr(Path, 'replace', blocked_checksum_replace)
    with pytest.raises(PermissionError, match='locked checksum'):
        module.bundle(output, tmp_path / 'cache')
    if existing:
        assert output.read_bytes() == b'previous verified ZIP'
        assert checksum.read_bytes() == b'previous matching SHA256'
    else:
        assert not output.exists()
        assert not checksum.exists()
    assert not list(tmp_path.glob('.*.part'))
    assert not list(tmp_path.glob('.*.rollback'))
    monkeypatch.setattr(Path, 'replace', replace)
    module.bundle(output, tmp_path / 'cache')
    assert checksum.read_text(encoding='utf-8').split()[0] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert not list(tmp_path.glob('.*.rollback'))


def test_bundle_rollback_failure_keeps_recoverable_previous_zip(tmp_path, monkeypatch):
    module, content = source_bundle(monkeypatch)
    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: io.BytesIO(content))
    output = tmp_path / 'sources.zip'
    checksum = output.with_suffix('.zip.sha256')
    output.write_bytes(b'previous verified ZIP')
    checksum.write_bytes(b'previous matching SHA256')
    replace = Path.replace

    def blocked_publication_and_restore(path, target):
        if Path(target) == checksum or path.suffix == '.rollback':
            raise PermissionError('synthetic filesystem refusal')
        return replace(path, target)

    monkeypatch.setattr(Path, 'replace', blocked_publication_and_restore)
    with pytest.raises(RuntimeError, match='previous ZIP preserved'):
        module.bundle(output, tmp_path / 'cache')
    backups = list(tmp_path.glob('.*.rollback'))
    assert len(backups) == 1
    assert backups[0].read_bytes() == b'previous verified ZIP'
    assert checksum.read_bytes() == b'previous matching SHA256'
    assert not list(tmp_path.glob('.*.part'))


def test_download_is_not_visible_under_final_cache_name_until_verified(tmp_path, monkeypatch):
    module, content = source_bundle(monkeypatch)
    cache = tmp_path / 'cache'

    class InspectDuringDownload(io.BytesIO):
        def read(self, size=-1):
            assert not (cache / 'fixture.tar.xz').exists()
            return super().read(size)

    monkeypatch.setattr(module.urllib.request, 'urlopen', lambda *args, **kwargs: InspectDuringDownload(content))
    module.bundle(tmp_path / 'sources.zip', cache)
    assert (cache / 'fixture.tar.xz').read_bytes() == content


def tracked_source(tmp_path):
    source = tmp_path / 'checkout'
    source.mkdir()
    git(source, 'init')
    (source / 'src').mkdir()
    (source / 'src' / 'app.py').write_text('print("synthetic")', encoding='utf-8')
    git(source, 'add', '.')
    return source


@pytest.mark.parametrize('entry', [
    'docs/settings.json', 'docs/settings.json.recovery-20261027.bak',
    'docs/credentials.json', 'docs/id_rsa', 'docs/private.pem', 'docs/server.key',
    'docs/.env.production', 'docs/raw-output/capture.txt', 'docs/local-data/export.json',
    'src/history.db-wal', 'src/app.pyc', 'tests/__pycache__/test.py',
    'docs/customer.csv', 'private/notes.md',
])
def test_tracked_private_or_generated_files_are_excluded(tmp_path, entry):
    module = script_module('export_sources')
    source = tracked_source(tmp_path)
    private = source / entry
    private.parent.mkdir(parents=True, exist_ok=True)
    private.write_text('synthetic private fixture', encoding='utf-8')
    git(source, 'add', '-f', entry)
    output = tmp_path / 'SOURCE'
    module.export(source, output)
    assert not (output / entry).exists()
    assert (output / 'src' / 'app.py').is_file()
    manifest = json.loads((output / 'source-manifest.json').read_text(encoding='utf-8'))
    assert entry not in manifest['files']


@pytest.mark.parametrize('entry', [
    'C:/outside.txt', 'C:outside.txt', r'docs\..\outside.txt',
    'docs//outside.md', 'docs/./outside.md', 'docs/notes.md:secret',
    'docs/notes.md.', 'docs/notes.md ', 'docs/CON.md',
])
def test_manifest_rejects_windows_path_aliases(tmp_path, entry):
    module = script_module('export_sources')
    source = tmp_path / 'SOURCE'
    source.mkdir()
    (source / 'source-manifest.json').write_text(json.dumps({'version': 1, 'files': [entry]}), encoding='utf-8')
    with pytest.raises(ValueError):
        module.export(source, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_gitless_export_supports_modified_source_and_refreshes_hashes(tmp_path):
    module = script_module('export_sources')
    source = tracked_source(tmp_path)
    output = tmp_path / 'SOURCE'
    module.export(source, output)
    (output / 'src' / 'app.py').write_text('changed after export', encoding='utf-8')
    rebuilt = tmp_path / 'rebuilt'
    module.export(output, rebuilt)
    assert (rebuilt / 'src' / 'app.py').read_text(encoding='utf-8') == 'changed after export'
    manifest = json.loads((rebuilt / 'source-manifest.json').read_text(encoding='utf-8'))
    assert manifest['sha256']['src/app.py'] == hashlib.sha256(b'changed after export').hexdigest()


def test_gitless_tree_without_manifest_is_rejected(tmp_path):
    module = script_module('export_sources')
    source = tmp_path / 'old-source'
    source.mkdir()
    (source / 'README.md').write_text('synthetic older release', encoding='utf-8')
    with pytest.raises(ValueError, match='manifest'):
        module.export(source, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_git_symlink_mode_is_rejected_even_on_windows_checkouts(tmp_path):
    module = script_module('export_sources')
    source = tracked_source(tmp_path)
    blob = git(source, 'hash-object', '-w', 'src/app.py').stdout.decode().strip()
    git(source, 'update-index', '--cacheinfo', f'120000,{blob},src/app.py')
    with pytest.raises(ValueError, match='link'):
        module.export(source, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()


def test_manifest_rejects_duplicate_case_insensitive_paths(tmp_path):
    module = script_module('export_sources')
    source = tracked_source(tmp_path)
    output = tmp_path / 'SOURCE'
    module.export(source, output)
    manifest_file = output / 'source-manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8'))
    manifest['files'].append('src/APP.py')
    manifest_file.write_text(json.dumps(manifest), encoding='utf-8')
    with pytest.raises(ValueError):
        module.export(output, tmp_path / 'rebuilt')


def test_existing_export_is_not_overwritten_or_mixed_with_stale_files(tmp_path):
    module = script_module('export_sources')
    source = tracked_source(tmp_path)
    output = tmp_path / 'SOURCE'
    output.mkdir()
    (output / 'private.log').write_text('existing local data', encoding='utf-8')
    with pytest.raises(ValueError):
        module.export(source, output)
    assert list(output.iterdir()) == [output / 'private.log']


def test_tracked_directory_link_cannot_escape_source_root(tmp_path):
    module = script_module('export_sources')
    source = tracked_source(tmp_path)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'app.py').write_text('synthetic private outside file', encoding='utf-8')
    (source / 'src' / 'app.py').unlink()
    (source / 'src').rmdir()
    if os.name == 'nt':
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(source / 'src'), str(outside)],
                       check=True, capture_output=True, timeout=10)
    else:
        (source / 'src').symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(ValueError, match='link|reparse'):
            module.export(source, tmp_path / 'output')
        assert not (tmp_path / 'output').exists()
        assert (outside / 'app.py').read_text(encoding='utf-8') == 'synthetic private outside file'
    finally:
        # rmdir removes the Windows junction itself; unlink removes a POSIX link.
        if os.name == 'nt':
            (source / 'src').rmdir()
        else:
            (source / 'src').unlink()


@pytest.mark.skipif(os.name != 'nt', reason='Windows build smoke lifecycle requires Windows PowerShell')
def test_windows_smoke_timeout_terminates_the_child_process_tree(tmp_path):
    fixture = tmp_path / 'synthetic child.py'
    marker = tmp_path / 'processes.json'
    fixture.write_text(
        'import json, os, subprocess, sys, time\n'
        'from pathlib import Path\n'
        'child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])\n'
        'Path(sys.argv[1]).write_text(json.dumps([os.getpid(), child.pid]))\n'
        'time.sleep(120)\n', encoding='utf-8',
    )
    harness = tmp_path / 'exercise.ps1'
    harness.write_text('''param($BuildScript, $Python, $Fixture, $Marker)
$ErrorActionPreference = 'Stop'
$OutputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($BuildScript, [ref]$tokens, [ref]$errors)
if ($errors.Count -gt 0) { throw 'Invalid build script' }
foreach ($name in @('Stop-SmokeProcess', 'Invoke-SmokeProcess')) {
    $function = $ast.Find({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }, $true)
    if ($null -eq $function) { throw "Missing smoke lifecycle function: $name" }
    . ([scriptblock]::Create($function.Extent.Text))
}
$failed = $false
try {
    Invoke-SmokeProcess -Executable $Python -Arguments @('"' + $Fixture + '"', '"' + $Marker + '"') -TimeoutMilliseconds 3000
} catch {
    if ($_.Exception.Message -notmatch '시간 초과') { throw }
    $failed = $true
}
if (-not $failed) { throw 'Expected smoke timeout' }
if (-not (Test-Path -LiteralPath $Marker)) { throw 'Synthetic child was not started' }
foreach ($processId in (Get-Content -LiteralPath $Marker -Raw | ConvertFrom-Json)) {
    if ($null -ne (Get-Process -Id $processId -ErrorAction SilentlyContinue)) { throw 'Synthetic child survived timeout' }
}
''', encoding='utf-8-sig')
    result = subprocess.run([
        'powershell', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
        '-BuildScript', str(ROOT / 'build_windows.ps1'), '-Python', sys.executable,
        '-Fixture', str(fixture), '-Marker', str(marker),
    ], capture_output=True, text=True, encoding='utf-8', timeout=30)
    assert result.returncode == 0, result.stderr
