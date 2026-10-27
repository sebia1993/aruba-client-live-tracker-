Aruba Client Live Tracker v0.2.0

기존 단일 추적에 최대 10대 다중 모니터링을 추가합니다. 목록에서 대상을 선택하여 상세·그래프·이벤트를 보고, 대상별/전체 시작·중지·일시 정지·재개·새로고침을 사용합니다. 최대 2개 수집과 12개 SSH 연결을 공유하며 대상별 상태와 오류를 격리합니다. 대상/통합 CSV·HTML 및 10대 오프라인 데모를 제공합니다. 대상 목록은 저장하지 않으며 기존 SQLite 이력은 유지합니다.

Windows x64 실행 ZIP 전체를 압축 해제한 뒤 ArubaClientLiveTracker/ArubaClientLiveTracker.exe를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않습니다. 먼저 데모로 확인하고 함께 제공된 SHA-256을 비교하십시오. 코드 서명되지 않았습니다. LGPL 대응 소스 ZIP도 함께 보관·재배포합니다.

검증 구성: 기존 단일 회귀, 대상 격리·동시성·SSH 풀·승인/취소·통합 보고서·10대 데모 GUI, Windows PyInstaller 빌드와 실제 frozen EXE의 단일/10대 스모크. 이 문서만으로 성공을 주장하지 않으며 정확한 결과는 해당 Actions 실행과 docs/BUILD_VALIDATION_KO.md, 배포의 validation JSON을 확인하십시오.

미검증: 실제 ArubaOS 8.10 세부 버전/7240XM/AP-535의 명령과 출력 의미, 실장비 부하/장시간 실행, 실제 MM 장애 전환/MD 클러스터 로밍, Windows 11 실기·고배율 화면입니다. 사용자의 장비 검증이 필요합니다.

제한: 주기 사이의 짧은 사건을 놓칠 수 있고 PHY Rate는 실제 Throughput이 아닙니다. 미제공 지표는 확인 불가입니다. SQLite·설정·보고서는 암호화하지 않으므로 로컬에서 보호하십시오.

저장소: https://github.com/sebia1993/aruba-client-live-tracker-
