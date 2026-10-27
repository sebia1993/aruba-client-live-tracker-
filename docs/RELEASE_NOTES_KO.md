# Aruba Client Live Tracker v0.3.8

대용량 이력에서 전체 관측을 한 번에 읽고 GUI 스레드에서 보고서를 만들던 경로를 개선했습니다. 미리보기는 최근 표시 범위만 읽으며, CSV/HTML은 독립 읽기 연결에서 순차 기록합니다. 기존 파일 형식·이력 선택·기간 조건은 유지하고, 내보내기 중 창을 닫으면 취소합니다.

합성 100만 건 기준 미리보기 21.716초 → 0.120초, HTML 내보내기 프로세스 최대 private memory 약 6.18GB → 75MB였습니다. 개선 후 내보내기 중에도 GUI heartbeat와 모니터링 저장이 진행됐고, 시험 데이터의 CSV/HTML은 기존 결과와 SHA-256이 일치했습니다. 실행 환경에 따라 시간·메모리는 달라집니다.

실제 SQLite 용량 제한·시험용 프로세스 강제 종료·손상 DB 원본 보존과 실제 Paramiko 루프백 반복 연결 단절/복구를 검증했습니다. 물리 전원 차단이나 운영망 장비 검증을 대신하지 않습니다. 설정·서버 키·이력을 보존하며 Aruba 명령·출력 파서·자동 TOFU 정책은 유지합니다.

Windows x64 ZIP 전체를 새 폴더에 풀고 `ArubaClientLiveTracker/ArubaClientLiveTracker.exe`를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않으며 미서명입니다. `_internal` 등 폴더를 포함한 ZIP 전체와 SHA-256, 서드파티 대응 소스를 함께 보관하십시오.

빌드 `0.3.8-506867ece370`의 실제 native Windows 8시간 진단이 정상 종료했습니다. 외부 기록기 28,801.734초·앱 28,800.515초 동안 합성 대상 10대가 각각 2,836건, 총 28,360건을 저장했습니다. SQLite 무결성·외래키·세션 10개 정상 종료, 저장 공백과 2,881개 자원 표본의 메모리·핸들·스레드 기준을 확인했습니다. 이전 중단·실패 실행은 보존하고 이번 실행 시간에 합산하지 않았습니다. 시스템 시각 보정에 따른 표시 시각 차이는 단조 경과 시계와 Windows 이벤트로 대조했습니다.

최종 로컬 전체 708개 검사와 수정본 CI가 통과했습니다. CI의 실제 검증 artifact는 Linux 688개 통과·Windows 전용 20개 제외, Windows 검사 및 빌드 재검사 각각 708개 통과와 source/frozen smoke 6개 성공을 확인했습니다. 장시간 진단은 새 합성 데이터 폴더만 사용하며 실제 SSH는 별도 루프백 장애 시험으로 확인했습니다.

8시간 실측 문서를 포함한 로컬 ZIP도 단일/10대 실행 각각 5회와 소스 manifest 246개 검사를 통과했습니다. GitHub Actions에서 별도로 빌드한 공개 EXE에는 같은 제품 소스·빌드 식별자 확인과 다운로드 후 패키지 실행 검증을 적용하며, 위 로컬 EXE의 장시간 실측과 구분합니다. 게시 상태와 상세 결과는 [최신 검증 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md), 비식별 실측 요약은 [8시간 검증 증거](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.8/stability-eight-hour.json), 최종 아카이브 해시는 함께 제공되는 `.sha256`에서 확인하십시오. 빌드 당시 pytest XML·EXE JSON은 ZIP의 validation 폴더에 있습니다. [이전 v0.3.7 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.7/BUILD_VALIDATION_KO.md)을 보존했습니다.

Windows에서 진행 파일을 읽고 교체하는 순간의 일시적인 권한 오류는 제한된 시간만 재시도합니다. 앱은 GUI를 막지 않고 다음 tick에서 다시 저장하며, 같은 진행 버전을 다시 읽어도 수집 정지로 오판하지 않습니다. 지속적인 권한 거부나 실제 진행 정지는 계속 실패 처리합니다.

여러 SSH 연결의 서버 키 사전 읽기와 저장은 같은 잠금으로 보호합니다. Windows에서 정상 키 파일을 갱신하는 순간 읽기가 거부되는 경합을 막으며, 잠금 대기 중 취소·시간 제한과 실제 손상·키 변경 차단은 유지합니다.

실제 Aruba 장비는 **실장비 검증 대기**입니다. OS의 동기 DNS 조회가 끝나지 않는 경우 취소/종료가 지연되는 제한도 남아 있습니다. 기존 설정·서버 키·이력을 보존하고 현장 운영 흐름을 확인하십시오.
