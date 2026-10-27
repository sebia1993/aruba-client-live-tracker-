# Windows 설치 및 실행

## 실행 ZIP

대상은 Windows 11 x64, 일반 사용자 계정입니다. 공개 저장소는 [sebia1993/aruba-client-live-tracker-](https://github.com/sebia1993/aruba-client-live-tracker-)입니다. [Releases](https://github.com/sebia1993/aruba-client-live-tracker-/releases)에서 게시된 버전의 실행 ZIP과 SHA-256, LGPL 대응 소스 ZIP을 받습니다. 이름 끝 하이픈을 포함합니다. 게시 여부는 [검증 기록](BUILD_VALIDATION_KO.md)을 확인하십시오.

ZIP 전체를 사용자 문서 폴더 등에 풀고 `ArubaClientLiveTracker/ArubaClientLiveTracker.exe`를 실행합니다. `_internal`, `LICENSES`, `docs`를 삭제하거나 EXE만 복사하지 마십시오. Python 설치와 관리자 권한은 필요하지 않습니다. 서명되지 않은 파일이므로 SmartScreen 경고 시 출처와 SHA-256을 확인하고 조직 정책을 따릅니다.

```powershell
Get-FileHash .\ArubaClientLiveTracker_v0.3.8_windows_x64.zip -Algorithm SHA256
```

`.sha256`와 비교하십시오. 자동 생성 `Source code (zip)`은 실행 배포가 아닙니다. `ArubaClientLiveTracker_v0.3.8_third_party_sources.zip`은 LGPL 대응 소스로 실행 ZIP과 함께 보관·재배포합니다. 애플리케이션 코드·테스트·워크플로·빌드 스크립트는 실행 ZIP의 `SOURCE`에도 들어 있습니다.

## 첫 실행

1. 데모 모드에서 `192.0.2.100` 또는 `02:00:00:00:00:01`로 단일 추적을 확인합니다.
2. 다중 모니터링에서 IP/MAC을 한 줄씩 등록하고 선택 상세와 개별·전체 제어를 확인합니다. 소스 실행 시 `--multi-demo`는 10대 데모를 준비합니다.
3. 실제 연결은 전체 추적을 중지한 뒤 모드·추적 방식·장비 설정을 바꿉니다.
4. 간편 설정에서 MM 이름/IP와 공통 SSH 계정을 입력하고 장비 찾기를 실행합니다. 입력한 MM은 기본 선택되며 필요한 장비를 선택한 뒤 검사·등록합니다. 발견은 `show switches`, 선택 장비 검사는 `show version`·`show switchinfo`만 사용합니다.
5. 역할·모델·버전·진단을 검토하고 저장합니다. 명확한 역할 근거가 없는 AUTO는 추적에서 제외합니다. 기존 수동 Primary/Standby MM·MD·`Current switch` 매핑도 사용할 수 있으며 발견 결과로 덮어쓰지 않습니다.
6. 공통 SSH 계정/비밀번호는 실행 중 발견·추적에서 재사용하며 파일에 저장하지 않습니다. 최초 서버 키는 질문이나 opt-in 없이 자동 저장하고 변경 키·알고리즘은 인증 전에 차단합니다.

설정 v1은 계속 읽으며 저장 시 v2로 기록합니다. 기존 SQLite는 진단 컬럼을 추가하고 이전 이력을 유지합니다.

대상 목록은 메모리에서만 유지되며 재실행하면 다시 등록해야 합니다. 수집 이력·장비 설정·신뢰한 서버 키는 사용자별 로컬 데이터 폴더에 저장합니다. Windows는 보통 `%LOCALAPPDATA%\ArubaClientLiveTracker`입니다. 실행 인자 `--data-dir`로 경로를 지정할 수 있습니다. SQLite와 보고서는 암호화하지 않습니다.

## 개발자 빌드

Git, Windows x64 Python 3.12 및 Windows PowerShell 5.1 또는 PowerShell 7에서 실행합니다.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pwsh -File build_windows.ps1 -Version 0.3.8
```

스크립트는 버전 일치, 고정 의존성 설치·공지 검사, pytest, ruff, onedir 패키징, 라이선스 수집, 실제 EXE의 단일/10대 데모 스모크를 확인한 뒤 실행 ZIP·대응 소스 ZIP·각 SHA-256을 만듭니다. 실패하면 중단합니다. 각 EXE 실행은 90초로 제한되며 결과 JSON과 pytest JUnit XML은 `dist/validation` 및 실행 ZIP의 `validation`에 보관합니다. CI의 운영체제별 JUnit도 아티팩트로 남깁니다. Qt offscreen 검증은 Windows 11 실기 화면 검증과 다릅니다.

기존 EXE를 실행 중이면 종료한 후 다시 빌드하십시오. `build/upstream-sources`의 검증된 LGPL 소스를 재사용합니다. Qt/PySide 6.8.3와 Paramiko 5.0.0 핀은 이전 버전과 같으며 소스 ZIP 이름만 배포 버전에 맞춥니다. 호환되는 재빌드 Qt DLL로 교체할 수 있도록 동적 연결을 유지합니다.

## 저장소와 릴리스 게시

원격 저장소는 이미 존재합니다. 유지보수자는 원격 이력과 CI 결과를 확인한 뒤 일반 푸시와 태그로 게시합니다. 기존 저장소를 재생성하거나 강제 푸시하지 않습니다.

```powershell
git remote -v
git push -u origin main
gh run list --repo sebia1993/aruba-client-live-tracker-
# CI 성공을 확인한 뒤 태그를 게시합니다.
git tag v0.3.8
git push origin v0.3.8
gh run list --repo sebia1993/aruba-client-live-tracker- --workflow release.yml
gh release view v0.3.8 --repo sebia1993/aruba-client-live-tracker-
```

`origin` 주소는 `https://github.com/sebia1993/aruba-client-live-tracker-.git`입니다. CI의 Windows 빌드와 태그 릴리스는 GitHub Actions를 우선 사용합니다. 수동 워크플로 실행은 아티팩트만 만들고, 버전 태그 실행은 검증 후 Release를 게시하도록 구성했습니다. v0.3.8 페이지는 게시 후 `https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.8`입니다. Actions/Release의 실제 성공 여부는 실행 기록으로 확인합니다.

## 실행 버전 확인과 복구

사용자 도움말의 앱 버전·빌드 식별자·실행 경로를 확인하면 이전 바로가기와 새 EXE를 구분할 수 있습니다. 실행 경로는 로컬 도움말에만 표시되며 자동 업로드하지 않습니다. 장비 발견 실패 시에는 기존 장비 목록과 매핑을 유지합니다. 원문 전체 대신 단계·오류 코드·값 없는 구조 진단으로 먼저 확인합니다.

손상된 설정을 저장할 때는 기존 바이트를 `settings.json.recovery-*.bak`에 먼저 보존하고 생성 위치를 안내합니다. 이 파일에는 운영 정보가 있을 수 있으므로 로컬에서만 관리하십시오. 백업이 실패하면 기존 설정은 덮어쓰지 않습니다. 이력 DB 잠금이나 종료 기록 저장 실패는 화면 안내를 확인하고 잠금을 해제한 뒤 중지 또는 닫기를 다시 시도합니다.

새 배포의 SOURCE는 `source-manifest.json`으로 공개 파일 목록과 해시를 기록합니다. `.git` 메타데이터가 없는 SOURCE에서도 수정·재빌드할 수 있으며 새 SOURCE 내보내기 때 해시를 갱신합니다. manifest가 없는 구버전 SOURCE는 그 버전의 빌드 스크립트를 사용하십시오. 해시는 전자서명이나 출처 인증을 대신하지 않습니다.
