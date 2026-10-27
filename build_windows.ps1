param([string]$Version = "0.1.0", [switch]$SkipInstall)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
if ($PSVersionTable.PSVersion.Major -ge 6 -and -not $IsWindows) { throw "Windows에서 실행하십시오." }
Set-Location $PSScriptRoot
if ($Version -notmatch '^\d+\.\d+\.\d+(?:[-.][A-Za-z0-9]+)*$') { throw "잘못된 버전입니다." }
function Invoke-Python { & python @args; if ($LASTEXITCODE -ne 0) { throw "Python 작업 실패: $args" } }
Invoke-Python -c "import struct,sys; assert sys.platform == 'win32' and struct.calcsize('P') == 8, 'Python Windows x64 필요'"
if (-not $SkipInstall) {
    Invoke-Python -m pip install --requirement requirements-dev.txt
    Invoke-Python -m pip install --no-deps -e .
}
Invoke-Python scripts/check_dependencies.py
Invoke-Python -m pytest -q
Invoke-Python -m ruff check src tests scripts
Invoke-Python -m PyInstaller --noconfirm --clean ArubaClientLiveTracker.spec
Invoke-Python scripts/collect_licenses.py --output dist/ArubaClientLiveTracker/LICENSES
Copy-Item README.md, THIRD_PARTY_NOTICES.md, LICENSE dist/ArubaClientLiveTracker/
Copy-Item docs dist/ArubaClientLiveTracker/docs -Recurse -Force
New-Item dist/ArubaClientLiveTracker/SOURCE -ItemType Directory -Force | Out-Null
Copy-Item src,scripts,tests,docs,LICENSES dist/ArubaClientLiveTracker/SOURCE/ -Recurse -Force
Copy-Item README.md,.gitignore,pyproject.toml,requirements.txt,requirements-dev.txt,ArubaClientLiveTracker.spec,build_windows.ps1,LICENSE,THIRD_PARTY_NOTICES.md dist/ArubaClientLiveTracker/SOURCE/
Get-ChildItem dist/ArubaClientLiveTracker/SOURCE -Recurse -Directory | Where-Object { $_.Name -eq "__pycache__" -or $_.Name -like "*.egg-info" } | Remove-Item -Recurse -Force
Invoke-Python scripts/bundle_sources.py --output "dist/ArubaClientLiveTracker_v${Version}_third_party_sources.zip"
$smokeDir = Join-Path ([IO.Path]::GetTempPath()) ([Guid]::NewGuid().ToString())
New-Item $smokeDir -ItemType Directory | Out-Null
try {
    $exe = Join-Path $PSScriptRoot 'dist/ArubaClientLiveTracker/ArubaClientLiveTracker.exe'
    $resultFile = Join-Path $smokeDir 'result.json'
    $process = Start-Process -FilePath $exe -ArgumentList @('--demo','--smoke-test','--data-dir',"`"$smokeDir`"",'--smoke-result',"`"$resultFile`"") -PassThru
    if (-not $process.WaitForExit(90000)) { $process.Kill(); throw "EXE 데모 검증 시간 초과" }
    if (-not (Test-Path $resultFile)) { throw "EXE 검증 결과 파일 누락" }
    $result = Get-Content $resultFile -Raw | ConvertFrom-Json
    if (-not $result.success) { throw "EXE 검증 결과 실패" }
    if ($process.ExitCode -ne 0) { throw "EXE 데모 검증 실패: $($process.ExitCode)" }
} finally { Remove-Item $smokeDir -Recurse -Force -ErrorAction SilentlyContinue }
$zip = "ArubaClientLiveTracker_v${Version}_windows_x64.zip"
Compress-Archive -Path dist/ArubaClientLiveTracker -DestinationPath "dist/$zip" -Force
$hash = (Get-FileHash "dist/$zip" -Algorithm SHA256).Hash.ToLowerInvariant()
[IO.File]::WriteAllText((Join-Path $PSScriptRoot "dist/$zip.sha256"), "$hash  $zip`n", [Text.UTF8Encoding]::new($false))
Write-Host "완료: dist/$zip"
