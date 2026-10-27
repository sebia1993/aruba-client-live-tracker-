param([string]$Version = "0.3.5", [switch]$SkipInstall)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) { throw "Windows에서 실행하십시오." }
Set-Location $PSScriptRoot
if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*$') { throw "잘못된 버전입니다." }
function Invoke-Python { & python @args; if ($LASTEXITCODE -ne 0) { throw "Python 작업 실패: $args" } }
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
    try { Remove-Item $packageDir -Recurse -Force }
    catch { throw "기존 실행 폴더를 정리할 수 없습니다. 실행 중인 EXE를 종료하십시오. $($_.Exception.Message)" }
}
Invoke-Python -m PyInstaller --noconfirm --clean ArubaClientLiveTracker.spec
Invoke-Python scripts/collect_licenses.py --output dist/ArubaClientLiveTracker/LICENSES
Copy-Item README.md,THIRD_PARTY_NOTICES.md,LICENSE,CHANGELOG.md,SECURITY.md $packageDir/
Copy-Item docs $packageDir/docs -Recurse -Force
$sourceDir = Join-Path $packageDir 'SOURCE'
New-Item $sourceDir -ItemType Directory -Force | Out-Null
# Copy directories recursively so new coordinator/pool/UI modules are included.
Copy-Item src,scripts,tests,docs,LICENSES,.github $sourceDir/ -Recurse -Force
Copy-Item README.md,.gitignore,pyproject.toml,requirements.txt,requirements-dev.txt,ArubaClientLiveTracker.spec,build_windows.ps1,LICENSE,THIRD_PARTY_NOTICES.md,CHANGELOG.md,SECURITY.md $sourceDir/
Get-ChildItem $sourceDir -Recurse -Directory | Where-Object { $_.Name -eq "__pycache__" -or $_.Name -like "*.egg-info" } | Remove-Item -Recurse -Force
$validationDir = Join-Path $PSScriptRoot 'dist/validation'
if (Test-Path $validationDir) { Remove-Item $validationDir -Recurse -Force }
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
        $process = $null
        try {
            $resultFile = Join-Path $smokeDir 'result.json'
            $modeArgument = if ($mode -eq 'multi') { '--multi-demo' } else { '--demo' }
            $process = Start-Process -FilePath $exe -ArgumentList @($modeArgument,'--smoke-test','--data-dir',"`"$smokeDir`"",'--smoke-result',"`"$resultFile`"") -PassThru
            if (-not $process.WaitForExit(90000)) { throw "EXE $mode 데모 검증 시간 초과" }
            $process.WaitForExit()
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
            if ($process.ExitCode -ne 0) { throw "EXE $mode 데모 검증 실패: $($process.ExitCode)" }
        } finally {
            if ($null -ne $process) {
                if (-not $process.HasExited) { $process.Kill(); $process.WaitForExit() }
                $process.Dispose()
            }
            Remove-Item $smokeDir -Recurse -Force -ErrorAction SilentlyContinue
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
