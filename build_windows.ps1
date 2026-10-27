param([string]$Version = "0.3.7", [switch]$SkipInstall)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) { throw "Windows에서 실행하십시오." }
Set-Location $PSScriptRoot
if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*$') { throw "잘못된 버전입니다." }
function Invoke-Python { & python @args; if ($LASTEXITCODE -ne 0) { throw "Python 작업 실패: $args" } }
function Remove-ScopedDirectory {
    param([string]$Path, [string]$Parent)
    $scope = [IO.Path]::GetFullPath($Parent).TrimEnd('\', '/')
    $target = [IO.Path]::GetFullPath($Path).TrimEnd('\', '/')
    if (-not $target.StartsWith($scope + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw '정리 대상이 허용된 폴더 밖에 있습니다.'
    }
    $current = $target
    while ($current -ne $scope) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw '링크 폴더는 정리할 수 없습니다.' }
        }
        $current = [IO.Path]::GetDirectoryName($current)
    }
    if (Test-Path -LiteralPath $target) { Remove-Item -LiteralPath $target -Recurse -Force }
}
function Stop-SmokeProcess {
    param([System.Diagnostics.Process]$Process)
    if ($null -ne $Process -and -not $Process.HasExited) {
        if ($null -ne $Process.GetType().GetMethod('Kill', [type[]]@([bool]))) {
            $Process.Kill($true)
        } else {
            # Windows PowerShell 5.1 has no Kill(entireProcessTree) overload.
            # Use process objects rather than depending on taskkill executable access.
            $started = $Process.StartTime
            $snapshot = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, CreationDate)
            $parents = @($Process.Id)
            $descendants = @()
            while ($parents.Count -gt 0) {
                $children = @($snapshot | Where-Object { $_.ParentProcessId -in $parents -and $_.CreationDate -ge $started })
                $parents = @($children | ForEach-Object { [int]$_.ProcessId })
                foreach ($child in $children) {
                    $handle = Get-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
                    if ($null -ne $handle -and $handle.StartTime -ge $started) { $descendants += $handle }
                }
            }
            try {
                if (-not $Process.HasExited) { $Process.Kill() }
                [array]::Reverse($descendants)
                foreach ($child in $descendants) {
                    if (-not $child.HasExited) { $child.Kill() }
                    if (-not $child.WaitForExit(10000)) { throw '스모크 자식 프로세스를 종료할 수 없습니다.' }
                }
            } finally {
                foreach ($child in $descendants) { $child.Dispose() }
            }
        }
        if (-not $Process.WaitForExit(10000)) { throw '스모크 자식 프로세스를 종료할 수 없습니다.' }
    }
}
function Invoke-SmokeProcess {
    param([string]$Executable, [string[]]$Arguments, [int]$TimeoutMilliseconds = 90000)
    $process = $null
    try {
        $process = Start-Process -FilePath $Executable -ArgumentList $Arguments -WindowStyle Hidden -PassThru
        if (-not $process.WaitForExit($TimeoutMilliseconds)) { throw 'EXE 데모 검증 시간 초과' }
        # Cache ExitCode before disposing the handle, including fast-exiting children.
        $exitCode = $process.ExitCode
        if ($exitCode -ne 0) { throw "EXE 데모 검증 실패: $exitCode" }
    } finally {
        if ($null -ne $process) {
            try { Stop-SmokeProcess -Process $process } finally { $process.Dispose() }
        }
    }
}
Invoke-Python -c "import struct,sys; assert sys.platform == 'win32' and struct.calcsize('P') == 8, 'Python Windows x64 필요'"
Invoke-Python -c "import pathlib,tomllib; assert tomllib.loads(pathlib.Path('pyproject.toml').read_text(encoding='utf-8'))['project']['version'] == '$Version', 'Version과 pyproject.toml 불일치'"
if (-not $SkipInstall) {
    Invoke-Python -m pip install --requirement requirements-dev.txt
    Invoke-Python -m pip install --no-deps -e .
}
Invoke-Python -c "from aruba_client_live_tracker import __version__; assert __version__ == '$Version', '패키지 버전 불일치'"
Invoke-Python scripts/check_dependencies.py
Invoke-Python -m pytest -q --junitxml=artifacts/pytest-windows-build.xml
Invoke-Python -m ruff check src tests scripts
# Fail clearly if a previously built EXE/DLL is still locked by a running process.
$packageDir = Join-Path $PSScriptRoot 'dist/ArubaClientLiveTracker'
if (Test-Path $packageDir) {
    try { Remove-ScopedDirectory -Path $packageDir -Parent $PSScriptRoot }
    catch { throw "기존 실행 폴더를 정리할 수 없습니다. 실행 중인 EXE를 종료하십시오. $($_.Exception.Message)" }
}
Invoke-Python -m PyInstaller --noconfirm --clean ArubaClientLiveTracker.spec
Invoke-Python scripts/collect_licenses.py --output dist/ArubaClientLiveTracker/LICENSES
$sourceDir = Join-Path $packageDir 'SOURCE'
# Git-tracked allowlisted paths, or the previous export manifest for a gitless rebuild.
Invoke-Python scripts/export_sources.py --source $PSScriptRoot --output $sourceDir
foreach ($document in @('README.md', 'THIRD_PARTY_NOTICES.md', 'LICENSE', 'CHANGELOG.md', 'SECURITY.md')) {
    Copy-Item -LiteralPath (Join-Path $sourceDir $document) -Destination $packageDir
}
# Read user-facing docs from the safe export too: local diagnostics in docs never ship.
Copy-Item -LiteralPath (Join-Path $sourceDir 'docs') -Destination (Join-Path $packageDir 'docs') -Recurse
$validationDir = Join-Path $PSScriptRoot 'dist/validation'
if (Test-Path $validationDir) { Remove-ScopedDirectory -Path $validationDir -Parent $PSScriptRoot }
New-Item $validationDir -ItemType Directory -Force | Out-Null
Copy-Item artifacts/dependency-advisories.json,artifacts/pytest-windows-build.xml $validationDir/
$exe = Join-Path $packageDir 'ArubaClientLiveTracker.exe'
$previousPlatform = $env:QT_QPA_PLATFORM
$env:QT_QPA_PLATFORM = 'offscreen'
try {
    foreach ($mode in @('single', 'multi')) {
        # Spaces in this path deliberately exercise Windows argument quoting.
        $smokeDir = Join-Path ([IO.Path]::GetTempPath()) ("Aruba smoke " + [Guid]::NewGuid().ToString())
        New-Item $smokeDir -ItemType Directory | Out-Null
        try {
            $resultFile = Join-Path $smokeDir 'result.json'
            $modeArgument = if ($mode -eq 'multi') { '--multi-demo' } else { '--demo' }
            Invoke-SmokeProcess -Executable $exe -Arguments @($modeArgument,'--smoke-test','--data-dir',"`"$smokeDir`"",'--smoke-result',"`"$resultFile`"")
            if (-not (Test-Path $resultFile)) { throw "EXE $mode 검증 결과 파일 누락" }
            Copy-Item $resultFile (Join-Path $validationDir "windows-exe-$mode-smoke.json")
            $result = Get-Content $resultFile -Raw -Encoding utf8 | ConvertFrom-Json
            if (-not $result.success) { throw "EXE $mode 검증 결과 실패" }
            $expectedTargets = if ($mode -eq 'multi') { 10 } else { 1 }
            if ($result.target_count -ne $expectedTargets -or $result.independent_macs -ne $expectedTargets) {
                throw "EXE $mode 독립 대상 수 검증 실패"
            }
            $targetRows = @($result.target_observations.PSObject.Properties)
            if ($targetRows.Count -ne $expectedTargets) { throw "EXE $mode 대상별 SQLite 증거 누락" }
            foreach ($row in $targetRows) {
                if ([int]$row.Value -lt 5) { throw "EXE $mode 대상별 SQLite 관측 5회 미달" }
            }
        } finally {
            Remove-ScopedDirectory -Path $smokeDir -Parent ([IO.Path]::GetTempPath())
        }
    }
} finally { $env:QT_QPA_PLATFORM = $previousPlatform }
Copy-Item $validationDir (Join-Path $packageDir 'validation') -Recurse -Force
# Exact LGPL library versions are unchanged; verified cache entries are reused.
Invoke-Python scripts/bundle_sources.py --output "dist/ArubaClientLiveTracker_v${Version}_third_party_sources.zip"
$zip = "ArubaClientLiveTracker_v${Version}_windows_x64.zip"
Compress-Archive -Path $packageDir -DestinationPath "dist/$zip" -Force
$hash = (Get-FileHash "dist/$zip" -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "dist/$zip.sha256"), "$hash  $zip`n", [Text.UTF8Encoding]::new($false))
Write-Host "완료: dist/$zip (단일/10대 데모 스모크 결과: dist/validation)"
