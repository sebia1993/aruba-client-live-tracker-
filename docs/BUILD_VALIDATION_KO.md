# v0.3.5 빌드와 검증 기록

기록일: 2026-10-27. 사용자는 v0.3.4에서도 `SWITCH_TABLE_PARSE_FAILED`와 출력 9행·IP 열 12자·IPv6 열 14자 진단을 보고했습니다. 운영망 원문·주소·계정은 수집하지 않았습니다.

## 원인 재현과 수정 범위

공식 ArubaOS 8.10 CLI Reference 물리 1629·3361쪽에 전체 페이지 안내 `--More-- (q) quit (u) pageup (/) search (n) repeat`가 있습니다. 기존 SSH 코드는 `--More--`만 제거하여 남은 `(q) quit (u)` 12자와 `pageup (/) sea` 14자가 주소 셀로 전달됐습니다. 정상 가상 장비 6대 표에 이 안내문을 넣고 실제 루프백 SSH로 수집하여 사용자가 보고한 9행/12/14 오류를 정확히 재현했습니다. 삽입 위치 9행은 재현을 위해 지정한 것이며 사용자 원문을 확인했다는 뜻이 아닙니다.

SSH 계층에서 전체 안내문과 바로 뒤의 알려진 지우기 제어를 제거한 후 기존 파서에 전달합니다. 실제 다음 행의 들여쓰기는 유지합니다. 주소 파서를 완화하거나 잘못된 행을 건너뛰지 않으며 새 명령·장비 설정 변경도 없습니다. 한 페이지당 스페이스만 보내고 기존 출력량·페이지 수·시간·취소 제한은 유지합니다.

## 자동 검증 범위

수정 전 새 SSH 전송 회귀 10건과 실제 SSH 통합 4건이 실패했고, 수정 후 통과했습니다. 전체/짧은 페이지 안내, TCP 경계별 분할, ANSI, CR·백스페이스 지우기, 같은 줄에 덮어쓴 다음 행, 들여쓰기, 여러 페이지와 일반 데이터 보존을 검사합니다. 실제 루프백 SSH 서버는 스페이스를 받기 전 다음 페이지를 보내지 않습니다. 일반/분리 표 6대 발견과 선택 WLC 검사, 페이지 이후 실제 잘못된 IP/행 수 불일치의 계속 차단을 확인합니다.

로컬 전체 368개 테스트(31.60초), Ruff, 저장소 보안 검사와 독립 리뷰를 통과했습니다. 독립 리뷰는 전체 안내문의 51개 분할 경계에서 두 페이지와 다음 행 들여쓰기를 보존하고 페이지마다 스페이스만 보내는 것도 확인했습니다. 소스 GUI 단일 5회·10대 각 5회 수집과 SQLite 저장·정상 종료를 확인했고, 고정 의존성 25개의 공개 공지에서 영향 패키지는 0개였습니다. Windows CI와 실제 EXE 검사도 통과했습니다. 공개 ZIP의 실제 다운로드·체크섬·구성 검증도 통과했습니다. [v0.3.4 검증 기록](validation/v0.3.4/BUILD_VALIDATION_KO.md)은 별도로 보존합니다.

## Windows CI 결과

커밋 `1600484cd117ebff2853628f00a78e73152de151`의 [CI 40454672860](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40454672860)는 Ubuntu와 Windows 모두 성공했습니다. Ubuntu 368개(31.207초), Windows 초기 368개(43.942초), Windows 빌드 재검사 368개(44.963초)가 통과했습니다. 시간은 JUnit 기록이며 실패·오류·건너뛰기는 모두 0입니다.

Windows Server 2025 x64·Python 3.12.10·PyInstaller 6.16.0에서 실제 EXE를 빌드했습니다. 단일 데모 1대 5회, 다중 데모 10대 각 5회(총 50회), 독립 MAC 10개와 SQLite 저장·정상 종료를 확인했습니다. 양쪽 운영체제의 소스 데모도 동일하게 통과했습니다. [CI 검증 JSON](validation/v0.3.5/ci-verification.json)에 실제 아티팩트·로그와 해시를 대조한 결과를 보존합니다. 동일 커밋에 v0.3.5 태그를 게시했습니다.

## 공개 릴리스와 다운로드 검증

동일 커밋의 `v0.3.5` 태그에서 [Release 40454982350](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40454982350)가 368개(JUnit 54.019초), Ruff, 실제 EXE 단일/10대 검사를 통과하고 [공개 릴리스](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.5)를 게시했습니다. 실패·오류·건너뛰기는 0입니다. 작은 검증 아티팩트의 SHA-256과 ZIP CRC도 업로드 기록과 대조했습니다.

| 파일 | 바이트 | SHA-256 |
|---|---:|---|
| `ArubaClientLiveTracker_v0.3.5_windows_x64.zip` | 43,384,484 | `28d465a46e52429ec0a40c8a8edf5ce3032b3a7faa0e6aa29c4b27572b919243` |
| `ArubaClientLiveTracker_v0.3.5_third_party_sources.zip` | 72,212,226 | `c8d8f295a0aef3c534536065422317bf4a0cadbb561a0159faea8cb88b0bff5a` |

실제 공개 파일을 직접 다운로드한 [검증 JSON](validation/v0.3.5/release-verification.json)은 ZIP CRC, AMD64 PE32+ Windows GUI EXE, 일반 사용자 asInvoker, Qt 한국어 번역, 라이선스 10개, 대응 소스 6개와 고정 해시, 실행 소스 18개 일치(개행 정규화), 페이지 회귀를 포함한 필수 소스 32개, 368개 JUnit 및 단일/10대 실행 증거를 확인합니다. ZIP 멤버 725개의 이름·제한된 텍스트 패턴 검사에서 금지된 로컬 설정/DB/운영 로그 파일은 0개였습니다. 모든 종류의 비밀정보 부재를 증명하는 검사는 아니며 실제 운영 자료를 사용하지 않았습니다.

태그 이후 변경은 검증 문서와 결과뿐이며 실행 코드·의존성은 동일합니다. 기존 EXE를 종료하고 새 ZIP을 별도 폴더에 전체 압축 해제해 실행합니다. 실제 MM에서의 오류 해소는 아직 확인하지 않았습니다.

## 공식 근거와 제한

2026-10-27 다음 공식 문서를 확인했습니다.

- [ArubaOS 8.10 CLI Reference](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8.x-CLI-Reference-Guide.pdf): 물리 1629·3361쪽 전체 페이지 안내.
- [show ap arm status](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-arm-status.htm), [show snmp trap-list](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-snmp-trap-lst.htm): 같은 안내문을 보여 주는 공식 HTML. 두 명령을 앱에서 새로 실행한다는 뜻이 아닙니다.
- [paging](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/paging.htm): 기본 활성화와 세션별 적용. 큰 터미널 크기를 요청해도 페이지 안내가 없다고 가정하지 않습니다.

공식 문서는 안내문을 입증합니다. CR·백스페이스·화면 지우기 바이트와 TCP 분할은 합성 전송 시험이며 실장비 캡처가 아닙니다. 실제 ArubaMM-HW-10K·ArubaOS 8.10 환경에서의 해결과 Windows 11 실기/고배율은 사용자 검증 대상입니다. 실행 파일은 코드 서명되지 않았습니다.
