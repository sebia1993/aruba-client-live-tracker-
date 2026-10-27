# v0.3.6 빌드와 검증 기록

기록일: 2026-10-27. Windows 11 Pro x64에서 인계 ZIP을 보존하고 공개 기준 커밋 2beb4ed의 수정 19개 파일·새 테스트 2개를 적용했습니다. 처음 실행한 Windows 기준 검사는 466개 통과·패키징 8개 실패(55.42초)로 인계 수치를 재현했습니다.

## 발견 오류와 수정 근거

공식 show switches/paging 문서, ArubaOS v8.10.0.10 릴리스 노트와 association Flags 문서를 대조했습니다. 구체적인 확인 범위·제한은 [CLI 근거](CLI_COMMANDS_KO.md)에 기록했습니다.

합성 표와 실제 루프백 SSH로 첫 머리글의 들여쓰기 손실과 반복 머리글 오인을 재현했습니다. 올바른 단일/분리 표·IPv4/IPv6·None·페이지 경계를 처리하며 주소·중복·건수·완료 검증을 유지합니다. 빈 주소 셀의 9행/0/0은 주소 자체 오류가 아니라 구조 문제로 안내합니다. 실제 사용자가 받은 바이트를 확인한 것이 아니므로 실제 장애 원인이나 해결을 확정하지 않습니다.

## 로컬 검증

- Python 3.12 x64 전용 가상환경, 실제 import 경로 확인.
- 최종 로컬 빌드 검사: 567개 통과, 실패·오류·건너뛰기 0. 실제 소요 시간과 항목은 실행 ZIP의 validation/pytest-windows-build.xml에 기록됩니다.
- Ruff와 diff 공백 검사 통과. 고정 의존성 25개의 공개 버전 공지에서 영향 패키지 0개. 내장 네이티브 라이브러리 전체 감사는 아닙니다.
- 소스 단일: 1대 5회, 다중: 10대 각 5회, 독립 MAC·SQLite·정상 종료 확인.
- 실제 Windows 창에서 단일 데모·일시 정지·재개·중지·재시작과 10대 목록을 확인했습니다. Windows 디스플레이 설정을 바꾸어 1920×1080의 실제 100%·125%·150%, 1280×720의 100%를 확인했습니다. 1366×768은 이 PC가 지원하지 않아 직접 검증하지 못했습니다.
- 낮은 해상도 첫 실행의 높이 초과를 확인해 초기·최소 창 크기를 작업 영역에 맞췄습니다. 910×480 논리 화면을 포함한 단일/다중 10개 회귀가 통과했습니다. 논리 화면 모의 검사는 실제 1366×768 검증을 대신하지 않습니다.
- 2,100회 합성 수집 반복, 세션 풀 상한·해제 및 실패/실제 해제 구분 회귀는 전체 테스트에 포함됩니다.
- 실제 SQLite 잠금, 종료 기록/DB close 실패, 보고서 중간 쓰기, 손상 설정/이력, 소스 캐시 중단을 별도 재현했습니다.

빌드 스크립트는 테스트·정적 검사·라이선스·단일/10대 실제 EXE 검사가 성공해야 ZIP을 생성합니다. 실행 ZIP의 validation 폴더에는 해당 빌드의 실제 XML·JSON이 들어 있습니다. 새 폴더 압축 해제와 공개 배포 후 다운로드 결과는 [저장소의 최신 검증 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md)에서 확인하십시오. 로컬 ZIP과 GitHub runner ZIP은 Python 세부 버전·빌드 환경에 따라 파일 해시가 다를 수 있으므로 각각의 체크섬으로 검사합니다.

## Windows 11 배포 ZIP 검사

최종 소스 식별자는 `f0c712ec979fce288a48f6bc4e4cdfaef38142845ea7e147d2cc603df3b264c1`, 도움말 빌드 식별자는 `0.3.6-f0c712ec979f`입니다. 로컬 최종 빌드의 567개 검사는 72.22초에 통과했습니다. 실행은 일반 사용자 권한(asInvoker), 콘솔 없는 AMD64 GUI이며 미서명입니다.

새 한글·공백 경로에 ZIP 전체를 풀고, 자식 PATH에서 Python·가상환경을 제외하고 별도 한글 임시 폴더를 사용했습니다. 단일 5회와 10대 5회 실행 모두 성공했습니다. 매 실행에서 대상별 5회 관측, 독립 MAC, SQLite 저장, 모든 세션 종료 기록을 확인했습니다. 합계 275개 관측이며 인터넷 연결을 물리적으로 끊은 시험은 아닙니다.

ZIP 741개 항목의 CRC·경로·대소문자 중복·운영 설정/DB/키 제외, SOURCE 225개 파일 해시, LGPL 대응 소스 6개 고정 해시, `.git` 없는 SOURCE 재내보내기 일치를 확인했습니다. 실행 폴더의 내장 Python 3.12 DLL을 사용했습니다.

최종 EXE를 실제 1280×720·100%, 1920×1080·125%/150%에서 다시 실행했습니다. 첫 창이 작업 영역 안에 들어오고 스크롤로 하단 설정·도움말에 접근했습니다. 도움말의 버전·빌드 식별자, 10대 전체 일시 정지 상태와 정상 종료를 확인했습니다. 테스트 후 두 모니터를 원래 1920×1080·100%로 복원했습니다.

| 로컬 파일(dist/) | 바이트 | SHA-256 |
|---|---:|---|
| ArubaClientLiveTracker_v0.3.6_windows_x64.zip | 40390059 | `1e2eaacb9d474dbca82b11e17d23d71518e1ddebff2f27278237be8eb6a10459` |
| ArubaClientLiveTracker_v0.3.6_third_party_sources.zip | 72212226 | `5534442d95d0f505866f4c89198f419d72b3ceab927a13bf0839d4e7671409ae` |

로컬 상세 증거: `artifacts/build-windows11-final.txt`, `artifacts/local-package-verification-final.json`, `artifacts/ci-pr-40475399680/`.

## GitHub CI

[PR #1](https://github.com/sebia1993/aruba-client-live-tracker-/pull/1)의 검사 대상과 변경 불가능한 v0.3.6 태그 대상은 `87006ff81df039192a2e6c6fd2e13edb17d1ef71`입니다. [CI 40475399680](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40475399680)은 Linux 566개 통과·Windows 전용 1개 건너뛰기, Windows 567개 통과, Windows 빌드 재검사 567개 통과입니다. 실패·오류는 모두 0이며 소스/EXE 단일·10대 JSON 6개도 모두 성공했습니다. 모든 JSON의 빌드 식별자가 위 최종 소스와 일치했습니다.

병합 커밋 `6b00429d1d8ea804971dd7ec8774afeff1f306b5`의 파일 트리는 태그 대상과 같습니다. 태그는 CI 검증 커밋에 직접 연결하며 이후 검증 기록만 별도 문서 커밋으로 갱신합니다.

[main CI 40475994222](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40475994222)도 Linux·Windows 모두 성공했습니다.

## 공개 Release와 재다운로드

[Windows Release 40476070643](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40476070643)이 같은 태그 대상 커밋에서 567개 테스트·단일/10대 EXE 검사를 통과하고 [v0.3.6](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.6)을 2026-10-27 17:51 KST에 정식 게시했습니다. 초안·사전 릴리스가 아닙니다.

인증 없는 공개 URL에서 4개 자산을 새로 다운로드했습니다. 체크섬 파일과 GitHub 자산 digest가 실제 ZIP 해시와 일치했습니다. 743개 ZIP 항목, SOURCE 225개 해시·재내보내기, 서드파티 소스 6개 고정 해시를 확인했습니다. 새 한글 경로와 분리 임시 폴더에서 단일 5회·10대 5회(총 275개 관측)를 재실행해 전부 통과했고 SQLite 미종료 세션은 0개였습니다. 실제 Windows 11 창에서 공개 EXE의 데모 표시·중지·종료도 확인했습니다. 공개 EXE의 빌드 식별자는 로컬 최종 코드와 같습니다.

| 공개 다운로드 | 바이트 | SHA-256 |
|---|---:|---|
| [Windows x64 실행 ZIP](https://github.com/sebia1993/aruba-client-live-tracker-/releases/download/v0.3.6/ArubaClientLiveTracker_v0.3.6_windows_x64.zip) | 43472820 | `b0067ca8ce7519fc2e8d1ebf6997b390cf485b24e04ba28ee8a8512945a76c9d` |
| [서드파티 대응 소스 ZIP](https://github.com/sebia1993/aruba-client-live-tracker-/releases/download/v0.3.6/ArubaClientLiveTracker_v0.3.6_third_party_sources.zip) | 72212226 | `cb25227fecf8805e7f134a68accdb25c9725257b1b78c0822fdb02a035bb5011` |

공개 파일 보관 위치는 `artifacts/published-v0.3.6/`, 재실행 결과는 `artifacts/published-package-verification.json`, 서버 증거는 `artifacts/release-validation-40476070643/`입니다. 실행 ZIP은 빌드 시점의 문서와 테스트 XML·EXE JSON을 보존하며, 게시 이후의 이 검증 기록과 다운로드 안내는 main 문서에서 갱신합니다.

## 해석 제한

자동·루프백 자료는 합성입니다. 실제 MM/Standby/MD에서 장비 발견·선택 검사·설정 저장·재시작·IP/MAC 검색·담당 MD 추적은 사용자 확인이 필요합니다. 원문·운영 주소·계정을 요구하거나 실제 장비에 접속하지 않았습니다. 실제 디스플레이 배율 검증과 환경 변수 배율 모의 검증은 구분합니다.

현장에서는 기존 설정과 서버 키를 보존한 상태로 새 EXE의 도움말 빌드 식별자를 확인한 뒤, 장비 찾기 → 필요한 장비 선택 검사 → 저장 → 종료/재실행 → IP/MAC 추적을 확인하십시오. 반복 오류가 남으면 원문이나 주소 대신 단계·오류 코드·출력 행 번호·열 길이 등 값 없는 진단을 확인합니다. 이 운영 절차는 **실장비 검증 대기**이며 자동 시험으로 대체하지 않습니다.

이전 결과는 [v0.3.5 기록](validation/v0.3.5/BUILD_VALIDATION_KO.md)에 보존했습니다.
