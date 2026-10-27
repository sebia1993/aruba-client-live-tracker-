Aruba Client Live Tracker v0.3.4

공식 ArubaOS 8.10 User Guide 861쪽에 있는 show switches의 IP Address=None·유효 IPv6 장비 행을 지원합니다. IPv4가 있으면 기존 우선순위를 유지하며, 잘못된 주소·중복 IP·불완전한 표는 계속 거부합니다. IPv6의 확장/압축 표기를 같은 담당 MD 주소로 비교하고 중복 매핑은 차단합니다.

MM 목록 조회와 선택 장비 검사 결과를 현재/이전 작업으로 나눠 표시합니다. 이전 MM 오류를 숨기지 않으며, 새 검사 완료가 목록 조회 복구를 뜻하지 않음을 안내합니다. IP 파싱 오류에는 실제 셀 값 대신 출력 행 번호와 열 길이를 표시합니다.

문서의 지원 누락을 재현해 수정했지만 사용자 장비의 실제 출력과 장애 원인은 확인되지 않았습니다. 모델명만으로 역할을 추측하거나 확인되지 않은 명령을 추가하지 않았습니다. 최초 서버 키 자동 저장·변경 키 차단, 단일/최대 10대 추적, 기존 설정과 SQLite 이력은 유지합니다.

Windows x64 실행 ZIP 전체를 새 폴더에 압축 해제한 뒤 ArubaClientLiveTracker/ArubaClientLiveTracker.exe를 실행하십시오. 기존 프로그램은 먼저 종료합니다. Python 설치와 관리자 권한은 필요하지 않으며 코드 서명되지 않았습니다. 체크섬 및 LGPL 대응 소스 ZIP을 함께 제공합니다. GitHub의 자동 Source code ZIP은 실행 배포가 아닙니다.

자동 검증 완료: Linux·Windows·태그 빌드에서 351개 테스트, 합성 IPv4/IPv6 단일·분리 표의 TCP loopback SSH, 선택 WLC 검사, GUI 작업 이력, 읽기 전용 명령/키 검증/보안 회귀. Windows Server 2025 x64에서 EXE를 빌드하고 단일 5회·10대 각 5회(총 50회) 관측·SQLite 저장·정상 종료를 확인했습니다. 게시 ZIP을 실제 다운로드하여 SHA-256·CRC·Windows x64 GUI EXE·한국어 번역·라이선스·대응 소스·실행 코드 일치도 검증했습니다.

CI: https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40446346316
Release: https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40446692668

Windows ZIP SHA-256: `621f9048232dc216b5a3293686e7f974c63bbddbfcbfad9816df95e6e5e47563`

다운로드 검증 JSON: https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.4/release-verification.json

검증 기록: https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md

실제 ArubaMM-HW-10K, Aruba7240XM/7210 접속·발견·추적과 Windows 11 실기/고배율 검증은 사용자 확인 대상입니다. 자동 검사는 가상 자료와 loopback SSH, Qt offscreen이며 실제 IPv6 네트워크나 운영망 검증을 대체하지 않습니다.

저장소: https://github.com/sebia1993/aruba-client-live-tracker-
