# v0.3.4 빌드와 검증 기록

기록일: 2026-10-27. 사용자는 MM 장비 찾기/선택 장비 검사 화면에서 IP 형식 관련 `SWITCH_TABLE_PARSE_FAILED`를 보고했고 원문 공유 대신 HPE 공식 문서 확인을 요청했습니다. 실제 주소·장비 원문·계정은 수집하지 않았습니다.

## 확인한 사실과 수정 범위

공식 ArubaOS 8.10 User Guide 861쪽은 `show switches`의 `IP Address=None`·유효 IPv6 행을 보여 줍니다. 이전 파서가 이 값에서 동일한 IP 오류를 발생시키는 것을 재현했습니다. IPv4가 명시적으로 None일 때만 유효 IPv6를 사용하고, IPv4가 있으면 기존 우선순위를 유지합니다. 잘못된 주소, 중복 IP, 행 누락과 잘못된 완료 건수는 계속 거부합니다. IPv6의 확장/압축 표기 차이는 담당 MD 매핑에서 같은 주소로 비교하며 중복 매핑은 거부합니다. 장비 SSH 관리 주소 지원이며 단말 검색은 기존 IPv4/MAC 범위입니다.

선택 장비 검사는 `show switchinfo`/`show version`만 실행합니다. 이 단계 뒤에 남아 있는 MM 목록 조회 오류를 새 검사 실패로 오해하지 않도록 현재/이전 작업과 검사 회차를 나눴습니다. 이전 MM 오류는 그대로 보존하고 현재 안내에도 남아 있음을 표시합니다. 파싱 실패는 원문 대신 출력 행 번호와 IP 열 길이를 안내합니다.

공식 CLI Bank의 기존 단일/분리 표는 종전 파서에서도 통과했습니다. 추가 공백·열 폭 문제는 확인되지 않았습니다. 공식 문서에서 지원 누락을 확인한 것이며 사용자의 실제 원인이 IPv6라고 확정한 것이 아닙니다. 모델명으로 역할을 추측하거나 무필터/추가 발견 명령을 실행하지 않습니다.

## 검증 상태

공식 구조를 참고한 RFC 5737/RFC 3849 가상 자료를 사용합니다. 문서의 IPv6 예시는 일부 행을 생략하여 Total Switches와 표시 행 수가 다르므로 완전한 응답 fixture로 복제하지 않았습니다. 새 단일/분리 표 TCP loopback SSH 회귀는 이전 파서에서 2건 실패, 수정 파서에서 통과했습니다. 실제 IPv6 네트워크 접속을 검증했다는 뜻은 아닙니다. GUI 회귀는 이전 발견 오류·현재 성공/실패·반복 검사를 확인합니다.

로컬 전체 351개 테스트(25.28초), Ruff, 보안 검사와 독립 리뷰를 통과했습니다. 소스 GUI는 단일 5회·10대 각 5회 수집과 SQLite 저장·정상 종료를 확인했습니다. 고정 의존성 25개의 공개 공지에서 영향 패키지는 0개였습니다. Windows CI·EXE·공개 다운로드 검증 결과는 실행 후 이 문서에 기록합니다. 이전 증거는 [v0.3.3 기록](validation/v0.3.3/BUILD_VALIDATION_KO.md)에 보존하며 이번 버전의 증거로 대체하지 않습니다.

## 공식 근거와 한계

- [ArubaOS 8.10 User Guide](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8%2E10%2E0%2E0-User-Guide.pdf): 861쪽 Viewing peer controller details, IPv4 부재/IPv6 장비 행.
- [HPE show switches](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm): 단일/분리 표 출력과 명령 설명.
- [해당 패치 릴리스 노트](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/Release-Notes/810/ArubaOS-8%2E10%2E0%2E10-Release-Notes.pdf): 이 앱의 파싱 오류를 장비 결함으로 단정할 근거는 확인하지 못했습니다.

ArubaMM-HW-10K, Aruba7240XM/7210의 실제 연결·발견·추적, Windows 11 실기와 고배율 검증은 사용자 확인 대상입니다. 실행 파일은 코드 서명되지 않았습니다.
