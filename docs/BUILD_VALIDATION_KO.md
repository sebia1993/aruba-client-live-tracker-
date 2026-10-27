# v0.3.0 빌드와 검증 기록

기록일: 2026-10-27. 이 문서는 현재 버전의 실제 검증 결과만 기록합니다. 통합 검증·Windows 빌드·배포 확인은 아직 완료 전입니다. 실제 Aruba 장비 접속과 Windows 11 실기 검증은 수행하지 않았습니다.

## 현재 상태

| 항목 | 기록 상태 |
|---|---|
| 버전 | pyproject·패키지·Windows 빌드·대응 소스 기본값 0.3.0 |
| 공개 원격 | `https://github.com/sebia1993/aruba-client-live-tracker-.git` (이름 끝 하이픈 포함) |
| Linux/Windows 자동 테스트·정적 검사 | Linux Python 3.12: 305개 통과(21.94초), Ruff·diff 검사 통과. Windows 결과 대기 |
| 의존성 공지 검사 | 2026-10-27 고정 의존성 25개 검사, 공개 공지 영향 패키지 0개. Qt/PySide 6.8.3와 Paramiko 5.0.0 유지 |
| 간편 설정·발견 화면 | 실제 Qt 설정·발견·단일·10대 화면을 docs/assets/v030-*.png에 캡처 |
| 단일/10대 소스 데모 | Linux Qt offscreen 종료 코드 0. 단일 5회, 10대 각 5회(합계 50회) SQLite 저장 및 독립 MAC 수 확인 |
| Windows 네이티브 onedir·실제 EXE 단일/10대 | Actions 실행 결과 대기 |
| 원격 푸시·태그·Release·다운로드 | v0.3.0 확인 전. 게시 완료나 해시를 추정하지 않음 |
| 사용자 MD 오류의 실제 원인 | 미확정. 단계별 진단 개선과 실환경 원인 확인은 구분 |

검증 후 코드 커밋, 실행 환경, 명령, 통과/실패 수, Actions URL, 산출물 이름과 SHA-256을 이 문서에 기록합니다. 테스트·빌드가 실패하면 실패 내용과 후속 검증을 남깁니다. 문서에 예정된 작업을 성공 결과로 기재하지 않습니다.

## 로컬 검증

`QT_QPA_PLATFORM=offscreen python -m pytest -q --junitxml=artifacts/pytest-v030.xml`에서 305개 모두 통과했습니다. 실 TCP loopback Paramiko 서버로 최초 키 자동 저장, 변경 키의 비밀번호 인증 전 차단, MM 발견 및 별도 관리 주소의 MD 역할 검사를 확인했습니다. 별도 프로세스의 신뢰 파일 충돌·취소·기한도 검사했습니다.

최초 통합 실행은 안내 문구 기대값 차이로 1개 실패(301개 통과)했고 실제 진단 의미를 유지한 기대값으로 수정했습니다. 독립 리뷰에서 발견한 500행 이후 장비 선택 오류는 전체 장비 행을 보존하도록 수정했으며, 501행 회귀 테스트와 독립 1,001행 검사를 통과했습니다. 최종 소스/설계 리뷰에서 확인된 미해결 결함은 없습니다.

## 보존할 증거

- pytest JUnit: CI `artifacts/pytest-<OS>.xml`, Windows 빌드 `artifacts/pytest-windows-build.xml` 및 `dist/validation/pytest-windows-build.xml`.
- 단일/10대 소스 데모: 종료 코드, 스모크 JSON, 대상별 SQLite 관측 수.
- Windows EXE: 실제 Windows runner의 빌드 로그와 `dist/validation/windows-exe-single-smoke.json`, `windows-exe-multi-smoke.json`. 두 프로세스 모두 성공해야 ZIP을 생성합니다.
- 발견/역할: 합성 CLI와 가짜 SSH 테스트, 선택 장비 검사, 수동 설정 보존, 불명확한 AUTO 제외, 변경 키/저장 실패 차단 및 자격 증명 미저장 테스트.
- 공개 자산: `ArubaClientLiveTracker_v0.3.0_windows_x64.zip`, 대응 소스 ZIP과 각 `.sha256`의 실제 다운로드·CRC·SHA-256·구성 검증.
- 배포 구성: EXE·교체 가능한 동적 Qt DLL·문서·LICENSES·재귀적 SOURCE·검증 JSON/XML, 사용자 데이터/비밀정보 미포함 검사.

## 검증 경계와 과거 기록

Qt offscreen은 창 생성·수집·SQLite·종료를 검사하지만 Windows 11 실기 화면과 배율, 실제 ArubaOS 8.10/7240XM/AP-535의 권한·출력·역할·부하·장시간 실행을 증명하지 않습니다. 실행 파일은 코드 서명되지 않았습니다. 공개 의존성 공지 검사는 내장 네이티브 라이브러리 전체 감사를 뜻하지 않습니다.

- [v0.2.0 완료 기록](validation/v0.2.0/BUILD_VALIDATION_KO.md): 당시 CI 178개·Windows EXE·Release·다운로드 증거.
- [v0.1.0 과거 기록](validation/v0.1.0/BUILD_VALIDATION_KO.md): 당시 Python 121개·Wine 스모크·저장소 생성 오류.

이전 버전의 결과와 SHA-256은 현재 v0.3.0의 증거로 사용하지 않습니다.
