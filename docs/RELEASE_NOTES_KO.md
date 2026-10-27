Aruba Client Live Tracker v0.3.3

MM에서 장비 찾기를 실행할 때 show switches가 장비 정보 표와 Status/Configuration State 표를 나누어 반환하면 SWITCH_TABLE_PARSE_FAILED가 발생하던 파서 오류를 수정했습니다. 두 표를 각각 해석하고 Total Switches와 행 수를 검증합니다. 기존 단일 표도 지원하며 잘림·중복 IP·알 수 없는 표·잘못된 완료 건수는 계속 차단합니다. 형식 오류에는 CLI 원문을 포함하지 않는 한국어 세부 사유를 표시합니다.

조회 명령과 역할 판별 정책은 유지합니다. 최초 키 자동 저장·변경 키 차단, 단일/최대 10대 추적, 기존 설정과 SQLite 이력도 유지합니다. 장비 설정 변경이나 새로운 명령 변형을 추가하지 않았습니다.

Windows x64 ZIP 전체를 압축 해제하고 ArubaClientLiveTracker/ArubaClientLiveTracker.exe를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않습니다. 코드 서명되지 않았습니다. 체크섬 및 LGPL 대응 소스 ZIP을 함께 제공합니다.

검증 결과: 로컬 전체 329개 테스트와 실제 TCP loopback SSH의 분리 표 발견·선택 WLC 검사, 독립 리뷰를 통과했습니다. 최종 CI·Windows 태그 빌드·공개 다운로드 결과는 완료 후 기록합니다. 태그 빌드는 테스트·실제 EXE 단일/10대 실행 검사를 모두 통과해야 게시합니다. 실행 ZIP의 validation 폴더에 JUnit XML과 스모크 JSON을 포함합니다.

실제 Aruba 장비 접속과 Windows 11 실기/고배율은 사용자 확인 대상입니다. 자동 검사는 합성 출력과 loopback SSH, Qt offscreen으로 수행하며 실장비 검증으로 표현하지 않습니다.

저장소: https://github.com/sebia1993/aruba-client-live-tracker-
