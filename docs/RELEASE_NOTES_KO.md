Aruba Client Live Tracker v0.3.0

MM 이름/IP와 공통 SSH 계정으로 장비 목록을 발견하고 선택한 장비의 역할·모델·버전을 검사할 수 있습니다. show switches/show version/show switchinfo의 읽기 전용 결과를 사용하며, 불명확한 역할은 AUTO로 남겨 추적에서 제외합니다. 기존 수동 장비·관리 주소·Current switch 매핑을 보존합니다. 최초 서버 키는 질문이나 opt-in 없이 자동 저장하고 변경된 키·알고리즘은 인증 전에 차단합니다. 공통 계정은 실행 중에만 재사용하며 파일에 저장하지 않습니다.

연결·키·인증·발견·식별·MM 조회·MD 매핑·MD 명령·해석·무선·저장 단계를 진단에 표시하고 SQLite 및 CSV/HTML 보고서에 보존합니다. 설정 v1은 계속 읽으며 저장 시 v2를 사용합니다. 기존 DB에 진단 컬럼을 추가하며 이력과 기존 단일/최대 10대 모니터링을 유지합니다. 사용자가 경험한 MD 오류의 실제 원인은 아직 미확정이며, 자동 등록만으로 해결됐다고 주장하지 않습니다.

Windows x64 실행 ZIP 전체를 압축 해제한 뒤 ArubaClientLiveTracker/ArubaClientLiveTracker.exe를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않습니다. 먼저 데모로 확인하고 제공된 SHA-256을 비교하십시오. 코드 서명되지 않았습니다. LGPL 대응 소스 ZIP도 함께 보관·재배포합니다. Qt/PySide 6.8.3와 Paramiko 5.0.0 버전 및 정확한 대응 소스 검증을 유지합니다.

검증 상태: Linux 통합 테스트 305개, Ruff, 단일/10대 소스 GUI 스모크를 통과했습니다. Windows 네이티브 빌드·실제 EXE 단일/10대 스모크·공개 다운로드 검증은 진행 중입니다. 최신 결과는 docs/BUILD_VALIDATION_KO.md와 해당 Actions 실행 및 배포 validation JSON/XML을 확인하십시오. 이전 v0.2.0의 178개 통과나 배포 해시를 이 버전의 결과로 사용하지 않습니다. 태그 워크플로는 테스트·빌드·두 EXE 스모크를 통과해야 Release를 게시하도록 구성되어 있습니다.

미검증: 실제 ArubaOS 8.10 세부 버전/7240XM/AP-535의 명령과 출력 의미·역할·실장비 부하·장시간 실행·MM 장애 전환·MD 클러스터 로밍, Windows 11 실기와 고배율 화면입니다. Qt offscreen과 Windows CI runner는 실기 검증과 구분합니다.

제한: 주기 사이의 짧은 사건을 놓칠 수 있고 PHY Rate는 실제 Throughput이 아닙니다. 미제공 지표는 확인 불가입니다. SQLite·설정·보고서는 암호화하지 않으므로 로컬에서 보호하십시오.

저장소: https://github.com/sebia1993/aruba-client-live-tracker-
