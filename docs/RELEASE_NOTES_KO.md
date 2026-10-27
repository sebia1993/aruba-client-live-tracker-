Aruba Client Live Tracker v0.1.0

Windows x64 실행 ZIP 전체를 압축 해제한 뒤 ArubaClientLiveTracker.exe를 실행하십시오. Python 설치나 관리자 권한은 필요하지 않습니다. 먼저 데모 모드로 확인하십시오. 함께 제공되는 SHA-256과 비교하십시오. 이 실행 파일은 코드 서명되지 않았습니다. LGPL 대응 소스 ZIP도 함께 제공합니다.

테스트 범위: 입력/명령 주입 방지, 합성 Aruba CLI 파서, MM→MD 매핑, 상태/로밍/오류 판정, 로컬 SQLite/보고서, 서버 키 검증, 데모 GUI, Windows PyInstaller 빌드 및 frozen EXE 데모 스모크. 정확한 결과는 해당 Actions 실행과 docs/BUILD_VALIDATION_KO.md를 확인하십시오.

미검증: 실제 ArubaOS 8.10 세부 버전/7240XM/AP-535에서 명령 지원 및 출력 의미, 실제 MM 장애 전환/MD 클러스터 로밍, Windows 11 실기와 고배율 화면. 사용자 장비 검증이 필요합니다.

제한: 10~60초 주기 관측 사이의 짧은 사건을 놓칠 수 있습니다. PHY Rate는 실제 Throughput이 아닙니다. 제공되지 않는 지표는 확인 불가로 표시합니다. SQLite는 암호화하지 않습니다. 설정과 보고서는 로컬에서 보호하십시오.
