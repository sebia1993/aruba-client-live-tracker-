# v0.3.3 빌드와 검증 기록

기록일: 2026-10-27. MM의 장비 찾기에서 `SWITCH_TABLE_PARSE_FAILED`가 발생한 사용자 보고를 조사했습니다. 사용자는 장비 정보 뒤에 별도 `Status / Configuration State` 표가 표시됨을 확인했습니다. 실제 주소·장비 원문·계정은 수집하지 않았습니다.

## 원인과 수정 범위

v0.3.2의 파서는 장비 목록을 단일 표로 가정하여 두 번째 표의 머리글을 IP 행으로 해석했습니다. 합성 출력과 실제 TCP loopback SSH 서버에서 같은 오류를 재현했습니다. HPE 공식 문서에도 identity 표 뒤에 Status/Configuration State/Config Sync Time(sec)/Config ID 표가 있는 형식이 기재돼 있습니다.

첫 장비 표와 문서에 근거한 후속 표를 각각 파싱하고, 두 표 모두 `Total Switches`와 행 수가 일치해야 목록을 채택하도록 수정합니다. 잘린 표·추가 행·알 수 없는 머리글·중복 IP·잘못된 완료 건수는 계속 거부합니다. 역할은 첫 표의 명시적인 Type에 근거합니다. 기존 단일 표와 정상 0건 표도 회귀 검사합니다. 조회 명령은 기존 `show switches` 그대로이며 새로운 명령 변형이나 전체 MD 탐색은 추가하지 않습니다.

형식 오류에는 고정된 한국어 세부 사유를 표시하며 CLI 원문·셀 값은 포함하지 않습니다. 기존 단일 표, 최초 키 자동 저장과 변경 키 차단, 단일/10대 추적을 유지합니다.

## 검증 상태

로컬 전체 329개 테스트(22.66초), 실제 TCP loopback SSH의 단일/분리 표 발견 및 선택 WLC 검사, 독립 코드 리뷰를 통과했습니다. Windows CI·네이티브 EXE 검사도 통과했습니다. Release 게시와 공개 다운로드의 SHA-256·CRC·구성 검증도 완료했습니다. v0.3.2의 결과는 이 버전의 검증으로 대체하지 않습니다.

## 최종 Windows CI

커밋 `be8869303d80d277d995ff4b931a0a6c2b0c819f`의 [CI 40442286970](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40442286970)는 Ubuntu와 Windows 모두 성공했습니다. Windows Server 2025 x64·Python 3.12.10·PyInstaller 6.16.0에서 초기 329개(46.76초), 빌드 재검사 329개(55.18초)를 통과했습니다. 두 JUnit의 실패·오류·건너뛰기는 0입니다.

실제 EXE 단일 데모는 1대 5회, 다중 데모는 10대 각 5회(총 50회), 독립 MAC 10개와 SQLite 저장·정상 종료를 확인했습니다. 소스 데모도 동일합니다. 의존성 25개의 공개 공지에서 영향 패키지는 0개였습니다. [CI 검증 JSON](validation/v0.3.3/ci-verification.json)에 아티팩트 요약을 보존합니다. 동일 커밋의 태그에서 Release를 빌드합니다.

## 최종 배포와 실제 다운로드

동일 커밋의 `v0.3.3` 태그에서 [Release 40442677825](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40442677825)가 329개(48.95초), Ruff, 실제 EXE 단일/10대 검사를 통과하고 [공개 릴리스](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.3)를 게시했습니다. 게시 파일을 직접 다운로드하여 검증했습니다.

| 파일 | 바이트 | SHA-256 |
|---|---:|---|
| `ArubaClientLiveTracker_v0.3.3_windows_x64.zip` | 43,342,235 | `5cdd4a93fe4f286ec64ecb923c2ea3686aceaaebec1630f645903db5fd880abc` |
| `ArubaClientLiveTracker_v0.3.3_third_party_sources.zip` | 72,212,226 | `20c95caa0fa265b0c2371d6507dac7784fda99f51b1ca2dcb96b6a9b6a8b74f1` |

[다운로드 검증 JSON](validation/v0.3.3/release-verification.json)은 ZIP CRC, AMD64 PE32+ Windows GUI EXE, 일반 사용자 asInvoker, Qt 한국어 번역, 라이선스 10개, 정확한 대응 소스 6개, 실행 소스 18개 일치(개행 정규화), 분리 표 회귀 검사를 포함한 필수 소스 30개, 329개 JUnit 및 단일/10대 실행 증거를 확인합니다. 713개 ZIP 멤버 검사에서 금지된 로컬 설정/DB/운영 로그 파일은 0개였습니다. 제한된 비밀 패턴 검사이며 모든 종류의 비밀정보 부재를 증명한다는 뜻은 아닙니다. 실제 운영 자료는 사용하지 않았습니다.

태그 이후 변경은 이 검증 기록과 문서뿐이며 실행 코드·의존성은 동일합니다.

## 공식 근거와 한계

- [HPE show switches](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm): 여러 표로 나눈 출력 예시. 해당 문서의 필터/debug 변형을 앱에서 실행한다는 뜻이 아닙니다.
- [ArubaOS 8.10 CLI Reference PDF](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8.x-CLI-Reference-Guide.pdf): 물리 3385쪽 `show switches state complete`의 동일한 분리 표 구조.
- [이전 v0.3.2 완료 기록](validation/v0.3.2/BUILD_VALIDATION_KO.md)

검증 데이터는 합성 자료이며 실제 Aruba 장비에 접속하지 않았습니다. 최종 실장비 발견·추적과 Windows 11 실기/고배율은 사용자 검증 대상입니다. 실행 파일은 코드 서명되지 않았습니다.
