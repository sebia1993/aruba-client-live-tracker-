# Aruba Client Live Tracker v0.3.6

장비 발견에서 첫 머리글의 들여쓰기 손실과 페이지 경계 반복 머리글 오인을 합성 SSH로 재현하고 수정했습니다. 빈 주소 셀, 짧은 행, 잘못된 주소와 표 완료 오류를 구분하고 값 없는 구조 진단을 제공합니다. 주소·중복·건수 검증을 유지하며 알 수 없는 행을 버려 성공시키지 않습니다.

인계된 안정성 변경을 보존·검토하고 다음을 보완했습니다.

- 자동 발견 장비의 주소 수정 후 과거 자동 별칭 정리, 수동 매핑 보존, 손상 설정 백업 안내
- 잘린 association Flags의 거짓 연결 해제 차단, 모호한 MM 위치·캐시 이력·취소·SSH 풀 처리
- 보고서 원자 저장, 손상 이력 안내, 실행 중 DB 잠금 대기 제한과 종료 기록 저장 재시도
- 소스 다운로드의 고정 SHA-256 검증·중단 복구, 공개 추적 파일만 SOURCE 내보내기
- 도움말에 앱 버전·소스 해시 기반 빌드 식별자·실행 경로·수집기/파서 버전 표시
- 낮은 해상도와 높은 배율에서 첫 실행 창이 화면 작업 영역을 넘지 않도록 크기 조정

Windows x64 ZIP 전체를 새 폴더에 풀고 `ArubaClientLiveTracker/ArubaClientLiveTracker.exe`를 실행하십시오. Python 설치와 관리자 권한은 필요하지 않으며 코드 서명되지 않았습니다. EXE만 복사하지 마십시오. SHA-256과 LGPL 대응 소스 ZIP을 함께 제공합니다. GitHub 자동 Source code ZIP은 실행 배포가 아닙니다.

검증 항목과 실제 수치는 [현재 검증 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md), 빌드별 pytest XML·EXE JSON은 실행 ZIP의 validation 폴더에서 확인할 수 있습니다. GUI 스모크는 대상별 5회 이상 관측·독립 MAC·SQLite 저장·정상 종료를 검증하며 종료 기록 저장 실패도 실패로 처리합니다.

사용자의 9행/0/0 실제 운영 원인은 아직 확정하지 않았습니다. 실제 Aruba 장비의 발견·선택 검사·재시작 후 IP/MAC 추적은 **실장비 검증 대기**입니다. 운영 주소·계정·CLI 원문을 수집하거나 운영 장비에 접속하지 않았습니다.
