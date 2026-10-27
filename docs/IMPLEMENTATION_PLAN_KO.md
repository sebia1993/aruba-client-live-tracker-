# Aruba Client Live Tracker 구현 계획
> v0.1.0 과거 구현 기록입니다. 현재 v0.3.0 계획은 [V030_IMPLEMENTATION_KO.md](V030_IMPLEMENTATION_KO.md), 현재 검증은 [BUILD_VALIDATION_KO.md](BUILD_VALIDATION_KO.md)를 따릅니다. 아래 승인 UI와 당시 배포 상태는 과거 동작입니다.

사용자의 상세 명세와 자율 구현 지시에 따라 Python 3.12+, PySide6 Essentials, Paramiko, SQLite, PyInstaller onedir를 선택한다. 외부 서비스 없이 동작한다.

- [x] 기존 4개 저장소의 라이선스·구조·공식 CLI 근거 검토
- [x] models.py 공통 계약, commands.py 입력/조회 전용 allowlist, parsers.py 엄격한 파서
- [x] ssh.py 키 승인/변경 차단/출력 제한, collector.py MM→MD 라우팅
- [x] tracker.py 정상 연속 관측 기반 변경 이벤트/실패 보존/카운터 차분
- [x] storage.py SQLite 세션/관측/이벤트와 CSV/HTML, demo.py 재현 시나리오
- [x] ui.py 한국어 Qt 대시보드/설정/키 승인/이력/진단, main.py 스모크 진입점
- [x] 보안·모니터링·GUI·지속 수집 테스트 및 정적 검사
- [ ] Windows 빌드·라이선스 수집·ZIP/SHA256·Actions·문서·검증 기록

## 검토 초점
출력 잘림과 0건 구분, 중복 검색 선택, SSH 키 교체, 중지 중 늦게 도착한 응답, AP/MD 변경과 카운터 리셋, 실패 전후 로밍 오판, CSV 수식/HTML 삽입 방지.

GitHub 저장소 생성은 2026-10-27 integration 권한 오류로 거부됨. 실제 장비 접근은 수행하지 않는다. Linux/Wine 검증과 Windows 11 검증을 구분한다.

## 독립 리뷰 및 검증 반영

연결 해제 관측의 저장 상태, 일부 지표의 이전 값/시각, SSH 키 승인 시간 초과의 비재시도 분류, 현재 BSSID와 다른 AP 통계 거부를 회귀 테스트로 검증했다. 최종 검증 수치와 배포 권한 제한은 BUILD_VALIDATION_KO.md를 따른다.
