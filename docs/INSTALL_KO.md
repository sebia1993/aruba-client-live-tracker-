# Windows 설치 및 실행

## 실행 ZIP

대상은 Windows 11 x64, 일반 사용자 계정입니다. ZIP 전체를 예를 들어 사용자 문서 폴더에 풀고 `ArubaClientLiveTracker.exe`를 실행합니다. `_internal`, `LICENSES`, `docs` 폴더를 삭제하거나 EXE만 복사하지 마십시오. 최종 사용자의 Python 설치는 필요하지 않습니다.

서명되지 않은 실행 파일입니다. SmartScreen 경고가 나오면 출처와 SHA-256을 먼저 확인하십시오. 조직 정책을 우회하지 마십시오.

```powershell
Get-FileHash .\ArubaClientLiveTracker_v0.1.0_windows_x64.zip -Algorithm SHA256
```

값을 함께 제공된 `.sha256`와 비교합니다. GitHub의 자동 생성 `Source code (zip)`에는 실행 파일이 들어 있지 않습니다.

함께 제공하는 `ArubaClientLiveTracker_v0.1.0_third_party_sources.zip`은 LGPL 라이브러리의 대응 소스입니다. 실행에 필요한 파일은 아니지만 실행 ZIP과 함께 보관·재배포하십시오. 애플리케이션 재빌드 소스는 실행 ZIP의 `SOURCE`에도 들어 있습니다.

## 첫 실행

1. 데모 모드에서 `192.0.2.100` 또는 `02:00:00:00:00:01`을 검색합니다.
2. 추적 시작 후 현재 정보, 이벤트, 그래프를 확인합니다.
3. 실제 연결에서는 장비 설정에 Primary MM과 선택적 Standby MM, 담당 MD를 등록합니다.
4. `Current switch`가 SSH 관리 주소와 다르면 MD의 매핑에 MM에 나타나는 값을 추가합니다.
5. SSH 계정/비밀번호는 실행 중에만 입력합니다. 파일로 저장하지 않습니다.
6. 최초 서버 키 SHA-256 지문을 장비 관리자가 별도 경로로 확인한 지문과 비교 후 승인합니다.

사용자별 로컬 데이터 폴더에 SQLite/장비 설정/신뢰한 서버 키를 보관합니다. Windows에서는 일반적으로 `%LOCALAPPDATA%\ArubaClientLiveTracker` 아래입니다. 정확한 위치는 진단/이력 화면 또는 실행 인자 `--data-dir`를 확인하십시오. 내보낸 보고서는 운영망 정보를 포함할 수 있으므로 로컬에 보관합니다.

## 개발자 빌드

Windows x64 Python 3.12 및 PowerShell 7에서 다음을 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pwsh -File build_windows.ps1 -Version 0.1.0
```

스크립트는 고정 의존성 설치, pytest, 정적 검사, onedir 패키징, 라이선스 수집, 실제 EXE 데모 스모크, ZIP과 SHA-256 생성을 순서대로 수행합니다. 실패하면 중단합니다. 소스에서 빌드한 Qt/PySide 라이브러리를 사용하려면 해당 Python 환경의 동적 라이브러리를 호환 버전으로 교체한 후 동일 명령으로 재빌드할 수 있습니다.

## 저장소와 릴리스 게시

이 작업에서는 `gh repo create`가 `Resource not accessible by integration (createRepository)`로 거부되었습니다. 저장소/푸시/Actions/Release 성공으로 보고하지 않습니다. 소스 번들을 압축 해제하고 **저장소 생성 권한이 있는 본인 GitHub 인증**으로 다음을 수행합니다. 기존 저장소가 생겼다면 먼저 원격 내용을 확인하고 별도 브랜치/PR로 반영하십시오. 강제 푸시하지 마십시오.

```powershell
gh auth login
gh repo create sebia1993/aruba-client-live-tracker --public --description "Aruba Client Live Tracker"
git init -b main
git add .
git commit -m "feat: initial Aruba Client Live Tracker"
git remote add origin https://github.com/sebia1993/aruba-client-live-tracker.git
git push -u origin main
gh run list --repo sebia1993/aruba-client-live-tracker
```

소스에 `.git`이 포함되어 이미 초기화되었다면 `git init`/첫 커밋/remote 추가를 반복하지 않습니다. CI의 Ubuntu/Windows 검사 성공을 확인한 후 버전 태그를 게시합니다.

```powershell
git tag v0.1.0
git push origin v0.1.0
gh run list --repo sebia1993/aruba-client-live-tracker --workflow release.yml
gh release view v0.1.0 --repo sebia1993/aruba-client-live-tracker
```

Actions가 성공하면 Release의 `ArubaClientLiveTracker_v0.1.0_windows_x64.zip` 및 `.sha256`을 다운로드합니다. 실제 생성 후 사용할 Release 주소는 `https://github.com/sebia1993/aruba-client-live-tracker/releases/tag/v0.1.0`입니다. 현재 존재하는 다운로드 링크로 오해하지 마십시오. Actions 실행이 조직 정책으로 차단되면 저장소 설정에서 권한을 확인하십시오.
