# v0.3.0 빌드와 검증 기록

기록일: 2026-10-27. 이 문서는 현재 버전의 실제 검증 결과만 기록합니다. 통합 검증과 Windows 네이티브 빌드·EXE 실행 검사를 완료했습니다. 태그 Release와 공개 다운로드 검증은 다음 단계입니다. 실제 Aruba 장비 접속과 Windows 11 실기 검증은 수행하지 않았습니다.

## 현재 상태

| 항목 | 기록 상태 |
|---|---|
| 버전 | pyproject·패키지·Windows 빌드·대응 소스 기본값 0.3.0 |
| 공개 원격 | `https://github.com/sebia1993/aruba-client-live-tracker-.git` (이름 끝 하이픈 포함) |
| Linux/Windows 자동 테스트·정적 검사 | Linux Python 3.12: 307개 통과(최종 20.95초), Ruff·diff 검사 통과. Windows에서도 307개·Ruff 통과 |
| 의존성 공지 검사 | 2026-10-27 고정 의존성 25개 검사, 공개 공지 영향 패키지 0개. Qt/PySide 6.8.3와 Paramiko 5.0.0 유지 |
| 간편 설정·발견 화면 | 실제 Qt 설정·발견·단일·10대 화면을 docs/assets/v030-*.png에 캡처 |
| 단일/10대 소스 데모 | Linux Qt offscreen 종료 코드 0. 단일 5회, 10대 각 5회(합계 50회) SQLite 저장 및 독립 MAC 수 확인 |
| Windows 네이티브 onedir·실제 EXE 단일/10대 | 최종 CI 40437725402 성공. EXE 단일 5회·10대 각 5회(총 50회) 관측/저장 및 정상 종료 확인 |
| 원격 푸시·태그·Release·다운로드 | main 푸시 및 최종 CI 완료. v0.3.0 태그·Release·공개 다운로드 검증 예정 |
| 사용자 MD 오류의 실제 원인 | 미확정. 단계별 진단 개선과 실환경 원인 확인은 구분 |

검증 후 코드 커밋, 실행 환경, 명령, 통과/실패 수, Actions URL, 산출물 이름과 SHA-256을 이 문서에 기록합니다. 테스트·빌드가 실패하면 실패 내용과 후속 검증을 남깁니다. 문서에 예정된 작업을 성공 결과로 기재하지 않습니다.

## 로컬 검증

`QT_QPA_PLATFORM=offscreen python -m pytest -q --junitxml=artifacts/pytest-v030.xml`에서 최종 307개 모두 통과했습니다. 실 TCP loopback Paramiko 서버로 최초 키 자동 저장, 변경 키의 비밀번호 인증 전 차단, MM 발견 및 별도 관리 주소의 MD 역할 검사를 확인했습니다. 별도 프로세스의 신뢰 파일 충돌·취소·기한도 검사했습니다.

최초 통합 실행은 안내 문구 기대값 차이로 1개 실패(301개 통과)했고 실제 진단 의미를 유지한 기대값으로 수정했습니다. 독립 리뷰에서 발견한 500행 이후 장비 선택 오류는 전체 장비 행을 보존하도록 수정했으며, 501행 회귀 테스트와 독립 1,001행 검사를 통과했습니다. 최종 소스/설계 리뷰에서 확인된 미해결 결함은 없습니다.

첫 GitHub CI [40436681206](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40436681206)의 Ubuntu 실행은 304개 통과·1개 실패였습니다. 명령 시간 초과 검사가 초기 연결 전체에 40ms를 부여해, CI의 파일 저장 지연 때문에 서버 키 단계 시간 초과가 먼저 발생했습니다. 해당 검사를 인증·최초 프롬프트 완료 뒤 명령 읽기 단계의 가상 시계를 진행하도록 분리했습니다. 느린 fsync 재현에서도 통과했고, 수정 후 로컬 전체 305개를 다시 통과했습니다. 최종 CI 결과는 별도 기록합니다. 이 실패를 정상으로 처리하거나 예외 코드 검사를 제거하지 않습니다.

후속 CI [40437075203](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40437075203)는 Ubuntu·Windows 모두 성공했습니다(커밋 7878fc6). Windows Server 2025 x64·Python 3.12.10에서 305개 테스트, 네이티브 EXE 단일/10대 스모크를 통과했습니다. 이후 작은 논리 화면에서 설정·발견 창의 초기 높이를 화면에 맞추는 수정을 추가했습니다. 실제 Qt 910×512 논리 화면 모의 검사에서 두 창 878×448, 모든 버튼 표시를 확인했고 큰 화면 기본 크기도 보존합니다. 이 변경 후 307개 전체 테스트와 정적 검사, 독립 리뷰를 통과했으며 최종 Windows CI를 재실행합니다. 실제 Windows 11 고배율 실기는 여전히 미검증입니다.

## 최종 소스의 Windows CI

커밋 `ff2dbdac36ffbe603db700bf176a87f643513a65`의 [CI 40437725402](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40437725402)는 Ubuntu·Windows 모두 성공했습니다. Windows Server 2025 x64, Python 3.12.10, PyInstaller 6.16.0에서 초기 307개(51.92초), 빌드 단계 307개(49.67초)를 통과했습니다. 실제 EXE의 단일/10대 스모크는 독립 MAC 1개/10개, 대상별 SQLite 5개 관측과 정상 종료를 확인했습니다. 두 JUnit 모두 오류·실패·건너뛰기 0입니다. [CI 검증 JSON](ci-verification.json)에 원본 아티팩트의 요약을 보존합니다. 태그 준비에서 바뀌는 것은 검증 문서이며 실행 코드는 동일합니다.

## 보존할 증거

- pytest JUnit: CI `artifacts/pytest-<OS>.xml`, Windows 빌드 `artifacts/pytest-windows-build.xml` 및 `dist/validation/pytest-windows-build.xml`.
- 단일/10대 소스 데모: 종료 코드, 스모크 JSON, 대상별 SQLite 관측 수.
- Windows EXE: 실제 Windows runner의 빌드 로그와 `dist/validation/windows-exe-single-smoke.json`, `windows-exe-multi-smoke.json`. 두 프로세스 모두 성공해야 ZIP을 생성합니다.
- 발견/역할: 합성 CLI와 가짜 SSH 테스트, 선택 장비 검사, 수동 설정 보존, 불명확한 AUTO 제외, 변경 키/저장 실패 차단 및 자격 증명 미저장 테스트.
- 공개 자산: `ArubaClientLiveTracker_v0.3.0_windows_x64.zip`, 대응 소스 ZIP과 각 `.sha256`의 실제 다운로드·CRC·SHA-256·구성 검증.
- 배포 구성: EXE·교체 가능한 동적 Qt DLL·문서·LICENSES·재귀적 SOURCE·검증 JSON/XML, 사용자 데이터/비밀정보 미포함 검사.

## 검증 경계와 과거 기록

Qt offscreen은 창 생성·수집·SQLite·종료를 검사하지만 Windows 11 실기 화면과 배율, 실제 ArubaOS 8.10/7240XM/AP-535의 권한·출력·역할·부하·장시간 실행을 증명하지 않습니다. 실행 파일은 코드 서명되지 않았습니다. 공개 의존성 공지 검사는 내장 네이티브 라이브러리 전체 감사를 뜻하지 않습니다.

- [v0.2.0 완료 기록](../v0.2.0/BUILD_VALIDATION_KO.md): 당시 CI 178개·Windows EXE·Release·다운로드 증거.
- [v0.1.0 과거 기록](../v0.1.0/BUILD_VALIDATION_KO.md): 당시 Python 121개·Wine 스모크·저장소 생성 오류.

이전 버전의 결과와 SHA-256은 현재 v0.3.0의 증거로 사용하지 않습니다.

## v0.3.0 태그 빌드 중단

[Release 40438268055](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40438268055)는 커밋 b2b183e에서 306개 통과·1개 실패로 중단했습니다. 10대×300회 반복 테스트의 60초 제한에서 모든 대상이 240~241회까지 진행했습니다. 패키징 및 게시 단계에 도달하지 않았고 다운로드용 릴리스는 생성되지 않았습니다. 공개 태그는 보존하고, 테스트의 처리 속도 의존성을 수정한 v0.3.1로 배포합니다.
