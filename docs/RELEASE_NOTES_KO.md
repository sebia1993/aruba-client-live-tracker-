# Aruba Client Live Tracker v0.3.8

대용량 이력에서 전체 관측을 한 번에 읽고 GUI 스레드에서 보고서를 만들던 경로를 개선했습니다. 미리보기는 최근 표시 범위만 읽으며, CSV/HTML은 독립 읽기 연결에서 순차 기록합니다. 기존 파일 형식·이력 선택·기간 조건은 유지하고, 내보내기 중 창을 닫으면 취소합니다.

합성 100만 건 기준 미리보기 21.716초 → 0.120초, HTML 내보내기 프로세스 최대 private memory 약 6.18GB → 75MB였습니다. 개선 후 내보내기 중에도 GUI heartbeat와 모니터링 저장이 진행됐고, 시험 데이터의 CSV/HTML은 기존 결과와 SHA-256이 일치했습니다. 실행 환경에 따라 시간·메모리는 달라집니다.

실제 SQLite 용량 제한·시험용 프로세스 강제 종료·손상 DB 원본 보존과 실제 Paramiko 루프백 반복 연결 단절/복구를 검증했습니다. 물리 전원 차단이나 운영망 장비 검증을 대신하지 않습니다. 설정·서버 키·이력을 보존하며 Aruba 명령·출력 파서·자동 TOFU 정책은 유지합니다.

Windows x64 ZIP 전체를 새 폴더에 풀고 `ArubaClientLiveTracker/ArubaClientLiveTracker.exe`를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않으며 미서명입니다. `_internal` 등 폴더를 포함한 ZIP 전체와 SHA-256, 서드파티 대응 소스를 함께 보관하십시오.

장시간 진단은 새 합성 데이터 폴더만 사용하며 수집 정체·저장 공백·GUI 정지·리소스 증가를 별도로 확인합니다. 짧은 리허설이나 가속 반복을 8시간 완료로 표시하지 않습니다. 게시와 최종 결과는 [최신 검증 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md), 빌드 당시 pytest XML·EXE JSON은 ZIP의 validation 폴더에서 확인하십시오. [이전 v0.3.7 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.7/BUILD_VALIDATION_KO.md)을 보존했습니다.

실제 Aruba 장비는 **실장비 검증 대기**입니다. OS의 동기 DNS 조회가 끝나지 않는 경우 취소/종료가 지연되는 제한도 남아 있습니다. 기존 설정·서버 키·이력을 보존하고 현장 운영 흐름을 확인하십시오.
