Aruba Client Live Tracker v0.3.5

Aruba의 전체 페이지 넘김 안내를 장비 행으로 오인하던 SSH 응답 정리 문제를 수정했습니다. 기존 코드는 --More--만 지워 뒤의 (q) quit (u) pageup (/) search (n) repeat가 남았습니다. 공식 문서의 안내문과 가상 장비 자료를 실제 루프백 SSH로 수집하여 보고된 출력 9행·IP 열 12자·IPv6 열 14자 오류를 정확히 재현했습니다.

전체 안내문과 인접한 화면 지우기 제어를 제거하고 실제 데이터 행과 들여쓰기를 보존합니다. 여러 페이지와 TCP 분할 수신을 지원하며 페이지당 스페이스만 전송합니다. 주소·역할·행 수 검증, 출력량/페이지 수/시간 제한, 최초 키 자동 저장·변경 키 차단과 단일/최대 10대 추적은 유지합니다. 장비 설정 변경이나 추가 명령은 없습니다.

Windows x64 ZIP 전체를 새 폴더에 압축 해제한 뒤 ArubaClientLiveTracker/ArubaClientLiveTracker.exe를 실행하십시오. 기존 프로그램은 먼저 종료합니다. Python 설치와 관리자 권한은 필요하지 않으며 코드 서명되지 않았습니다. 체크섬과 LGPL 대응 소스 ZIP을 함께 제공합니다. GitHub의 자동 Source code ZIP은 실행 배포가 아닙니다.

자동 검증 완료: Linux·Windows·태그 빌드에서 368개 테스트, SSH 페이지 처리 회귀, 실제 루프백 SSH의 일반/분리 표 6대 발견·선택 WLC 검사, 잘못된 IP와 행 수 불일치 차단, 기존 보안·파서·GUI·단일/다중 추적. Windows Server 2025 x64에서 EXE를 빌드하고 단일 5회·10대 각 5회(총 50회) 관측·SQLite 저장·정상 종료를 확인했습니다. 게시 ZIP을 직접 다운로드하여 SHA-256·CRC·Windows x64 GUI EXE·한국어 번역·라이선스·대응 소스·실행 소스 일치를 검증했습니다.

CI: https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40454672860
Release: https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40454982350

Windows ZIP SHA-256: `28d465a46e52429ec0a40c8a8edf5ce3032b3a7faa0e6aa29c4b27572b919243`

다운로드 검증 JSON: https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/validation/v0.3.5/release-verification.json

검증 기록: https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md
공식 페이지 안내: https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-snmp-trap-lst.htm

공식 안내문을 확인했으며 CR/백스페이스/분할 전송은 합성 시험입니다. 실제 Aruba 장비에서의 오류 해소와 Windows 11 실기/고배율 검증은 사용자 확인 대상입니다.
