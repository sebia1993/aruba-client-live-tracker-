# v0.2.0 빌드와 검증 기록

기록일: 2026-10-27. 실제 Aruba 장비 접속과 Windows 11 실기 검증은 수행하지 않았습니다.

## 현재 버전 상태

| 항목 | 기록 상태 |
|---|---|
| 버전 | pyproject·패키지·Windows 빌드 기본값 0.2.0 |
| 공개 원격 | `https://github.com/sebia1993/aruba-client-live-tracker-.git` (저장소 이름 끝 하이픈 포함) |
| v0.2.0 자동 테스트·정적 검사 | Linux Python 3.12: **178 passed (16.07s)**, Ruff 통과 |
| 고정 의존성 공지 | PyPI 25개 고정 패키지: 알려진 영향 공지 0건; 내장 네이티브 라이브러리 전체 감사는 아님 |
| 10대 GUI·스크린샷 | 단일 1대/5건, 다중 10대/50건; 125%·150% offscreen 스모크 통과, 실제 스크린샷 저장 |
| Windows Actions 빌드·단일/10대 EXE | 실행 결과 기록 대기 |
| 원격 푸시·Actions·Release | 실행 URL 및 실제 결과 기록 대기 |

워크플로와 빌드 스크립트가 존재한다는 사실을 실행 성공으로 취급하지 않습니다. 최종 실행 뒤 아래 증거를 갱신합니다. v0.1.0 테스트 121건과 Wine 스모크는 현재 버전의 결과가 아닙니다.

## 검증 증거와 산출물

- 소스 GUI: `--demo --smoke-test` 및 `--multi-demo --smoke-test`의 종료 코드·JSON, 대상별 SQLite 관측.
- Windows 빌드: CI/Release의 실제 Windows runner, pytest/ruff/의존성 공지, PyInstaller 로그.
- Frozen EXE: `dist/validation/windows-exe-single-smoke.json`, `windows-exe-multi-smoke.json`. 빌드는 두 프로세스 모두 성공해야 ZIP을 만듭니다.
- `ArubaClientLiveTracker_v0.2.0_windows_x64.zip`: EXE·동적 DLL·문서·고지·재귀적 `SOURCE`·검증 JSON.
- `ArubaClientLiveTracker_v0.2.0_third_party_sources.zip`: Qt 6.8.3/PySide·Shiboken 및 Paramiko 5.0.0의 정확한 대응 소스. 변경되지 않은 소스는 캐시를 재사용합니다.
- 각 ZIP의 `.sha256`. Release URL은 실제 게시 후 확인합니다.

공개 공지 검사는 빌드 시 PyPI 버전 공지를 확인하며 내장 네이티브 라이브러리 전체 감사를 의미하지 않습니다. 데스크톱 실행에는 외부 분석 서비스/API가 필요하지 않습니다.

## 검증 경계

Qt offscreen은 실제 창 생성·수집·SQLite·정상 종료를 확인하지만 Windows 11 화면·배율 실기를 대체하지 않습니다. Wine 실행도 Windows 11 네이티브와 구분합니다. 실제 ArubaOS 8.10/7240XM/AP-535의 명령·권한·단위·MM/MD 장애 전환·실장비 10대 부하와 24시간 사용은 미검증입니다. 실행 파일은 코드 서명되지 않았습니다.

## v0.1.0 과거 기록

기존 증거는 [validation/v0.1.0](validation/v0.1.0/BUILD_VALIDATION_KO.md)에 보관합니다. Linux/Windows Python 121건, Wine frozen 단일 데모, 배율 스모크, 당시 저장소 생성 오류는 모두 과거 버전의 기록입니다. 현재 원격 저장소는 존재하며 당시의 생성 실패를 현재 상태로 안내하지 않습니다.

## CI 초기 실행에서 수정한 문제

[첫 CI](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40430054152)는 Ubuntu의 Qt 런타임 `libEGL.so.1` 누락과 Windows 빌드 검사 콘솔의 CP1252 한국어 출력 오류로 실패했다. Linux 런타임 설치 단계를 추가하고 빌드 검사 출력 및 테스트 파일 읽기에 UTF-8을 명시했다. Windows 콘솔 오류를 오프라인 회귀 테스트로 재현한 뒤 수정했으며, 실패 결과를 숨기거나 테스트를 건너뛰지 않았다.
