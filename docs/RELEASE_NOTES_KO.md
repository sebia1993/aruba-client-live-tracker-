Aruba Client Live Tracker v0.3.3

MM에서 장비 찾기를 실행할 때 show switches가 장비 정보 표와 Status/Configuration State 표를 나누어 반환하면 SWITCH_TABLE_PARSE_FAILED가 발생하던 파서 오류를 수정했습니다. 두 표를 각각 해석하고 Total Switches와 행 수를 검증합니다. 기존 단일 표도 지원하며 잘림·중복 IP·알 수 없는 표·잘못된 완료 건수는 계속 차단합니다. 형식 오류에는 CLI 원문을 포함하지 않는 한국어 세부 사유를 표시합니다.

조회 명령과 역할 판별 정책은 유지합니다. 최초 키 자동 저장·변경 키 차단, 단일/최대 10대 추적, 기존 설정과 SQLite 이력도 유지합니다. 장비 설정 변경이나 새로운 명령 변형을 추가하지 않았습니다.

Windows x64 ZIP 전체를 압축 해제하고 ArubaClientLiveTracker/ArubaClientLiveTracker.exe를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않습니다. 코드 서명되지 않았습니다. 체크섬 및 LGPL 대응 소스 ZIP을 함께 제공합니다.

검증 완료: Linux·Windows 329개 테스트와 실제 TCP loopback SSH의 분리 표 발견·선택 WLC 검사, 독립 리뷰를 통과했습니다. Windows Server 2025 x64·Python 3.12.10·PyInstaller 6.16.0에서 EXE를 빌드하고 단일 5회, 다중 10대 각 5회(총 50회)의 관측·SQLite 저장·독립 MAC·정상 종료를 확인했습니다. 태그 빌드에서도 329개가 통과했습니다. 고정 의존성 25개의 공개 공지에서 영향 패키지는 0개였습니다.

CI: https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40442286970
Release: https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40442677825

게시 ZIP을 실제 다운로드하여 SHA-256·CRC·Windows x64 GUI EXE·일반 사용자 실행·한국어 번역·라이선스와 대응 소스·포함된 테스트/실행 증거를 확인했습니다.

Windows ZIP SHA-256: `5cdd4a93fe4f286ec64ecb923c2ea3686aceaaebec1630f645903db5fd880abc`

검증 기록: https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md
다운로드 검증 JSON: https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.3/release-verification.json

실제 Aruba 장비 접속과 Windows 11 실기/고배율은 사용자 확인 대상입니다. 자동 검사는 합성 출력과 loopback SSH, Qt offscreen으로 수행하며 실장비 검증으로 표현하지 않습니다.

저장소: https://github.com/sebia1993/aruba-client-live-tracker-
