# Aruba Client Live Tracker v0.3.7

기존 작업과 운영 흐름을 유지하면서 재현된 5개 오류를 수정했습니다.

- DNS/TCP 연결 중 취소·시간 초과 후 늦게 만들어진 SSH 연결 정리
- 중복 MAC으로 멈춘 유휴 대상의 수집기·공유 SSH 소유권 해제
- 이전 발견 작업의 정리가 현재 검사 작업의 취소 연결을 지우는 경합 방지
- 저장 이력이 500건을 넘을 때 최신 세션이 화면에서 빠지는 오류 수정
- 종료 기록 저장 실패 후 선택 대상의 중지 버튼으로 재시도 가능

각 문제를 합성 자료·실제 SQLite 잠금·루프백 Paramiko·스레드 동기화로 먼저 실패 재현한 뒤 회귀 테스트를 통과시켰습니다. 설정·서버 키·기존 이력을 보존하며, Aruba 명령과 출력 파서·자동 TOFU 정책은 변경하지 않았습니다.

Windows x64 ZIP 전체를 새 폴더에 풀고 `ArubaClientLiveTracker/ArubaClientLiveTracker.exe`를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않으며 미서명입니다. `_internal` 등 폴더를 포함한 ZIP 전체와 SHA-256, 서드파티 대응 소스를 함께 보관하십시오.

실제 검사 수치·Windows 결과·공개 다운로드 검증은 [최신 검증 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md), 빌드 당시 pytest XML·EXE JSON은 실행 ZIP의 validation 폴더에서 확인할 수 있습니다. [이전 v0.3.6 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.6/BUILD_VALIDATION_KO.md)은 보존했습니다.

운영 장비에 접속하거나 원문·계정을 수집하지 않았습니다. 실제 Aruba 장비의 발견·선택 검사·재시작 후 IP/MAC 추적은 **실장비 검증 대기**입니다. DNS 응답 지연 자체의 중단 시간은 이번 변경으로 개선됐다고 주장하지 않습니다.
