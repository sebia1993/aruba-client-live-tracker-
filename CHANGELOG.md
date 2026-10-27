# 변경 이력

## 0.3.6 — 2026-10-27

- 장비 발견에서 첫 머리글 들여쓰기와 페이지 경계 반복 머리글을 보존·검증하고, 빈 주소 셀·짧은 행·잘못된 주소를 구분
- 주소·장비 이름·CLI 원문 없이 수신/정규화 횟수, 표 종류·열 위치·행 길이·건수 구조 진단 제공
- 도움말에 앱 버전, 소스 해시 기반 빌드 식별자, 실행 경로와 수집기/파서 버전 표시
- 낮은 해상도와 높은 배율에서 처음 실행한 창을 화면 작업 영역에 맞춤
- 인계된 안정성 패치 검토: 식별·매핑, 파서의 잘린 응답, 모호한 MM 위치, 수집 취소, 세션 풀과 캐시 이력 처리 보완
- 자동 발견 endpoint 변경 시 과거 자동 별칭 정리, 사용자 매핑 보존, 손상 설정 백업 안내
- 보고서 원자 저장, 손상 이력 안내, 실행 중 DB 잠금 대기 제한과 종료 기록 저장 재시도
- 고정 해시 기반 소스 캐시 복구, 추적된 공개 경로만 SOURCE 내보내기, manifest 기반 Git 없는 재빌드 지원

자동 시험·Windows EXE·배포 상태는 [현재 검증 기록](docs/BUILD_VALIDATION_KO.md)을 확인하십시오. 9행/0/0의 실제 운영 원인은 확정하지 않았으며 실장비 검증은 대기 상태입니다.

## 0.3.5 — 2026-10-27

- 공식 [ArubaOS 8.10 CLI Reference](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8.x-CLI-Reference-Guide.pdf) 1629·3361쪽의 전체 페이저 `--More-- (q) quit (u) pageup (/) search (n) repeat`를 SSH 출력에서 완전히 제거
- 기존 정리가 `--More--`만 지워 안내 문구를 장비 주소 행으로 남기는 문제를 재현했으며, 합성 자료에서 보고된 출력 9행·IPv4 열 12자·IPv6 열 14자의 오류 구조를 확인
- 주소 파서의 엄격한 검증을 유지하고 추가 Aruba CLI 명령 없이 SSH 페이저 처리 범위만 수정
- 패키지·Windows 빌드·대응 소스 ZIP 버전을 0.3.5로 구분하며 의존성·SSH 신뢰 정책은 유지
- Linux·Windows 368개, Windows EXE 단일/10대, 공개 Release 및 실제 다운로드 검증 완료

2026-10-27 공식 [paging 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/paging.htm)에서 세션별 기본 활성화를 확인했습니다. 단편 수신·화면 지우기·여러 페이지·다음 행 보존 회귀를 추가했습니다. 자동 테스트·Windows EXE·Release와 실제 다운로드 결과는 [검증 기록](docs/BUILD_VALIDATION_KO.md)에 기록합니다. 사용자 장비에서의 해결 확인은 아직 완료하지 않았습니다.

## 0.3.4 — 2026-10-27

- 공식 ArubaOS 8.10 User Guide 861쪽에 있는 `IP Address=None`·유효 IPv6 행을 발견 파서에서 지원
- 유효 IPv4 우선 선택, 전체 행 수와 역할 근거 검증을 유지하며 잘못된 주소 행을 임의로 건너뛰지 않음
- IPv6의 압축/확장 표기를 같은 담당 MD 주소로 비교하고 중복 매핑은 계속 거부
- 이전 장비 발견 오류와 새로 실행한 선택 장비 검사 결과를 구분하고, 원문·셀 값 없이 오류의 출력 행 번호와 IP 열 길이를 안내
- 패키지·Windows 빌드·대응 소스 ZIP 버전을 0.3.4로 구분하며 의존성·SSH 신뢰 정책은 유지
- Linux·Windows 351개, Windows EXE 단일/10대, 공개 Release와 실제 다운로드 검증 완료

문서 예시에서 지원 누락을 확인했지만 사용자의 실제 출력 형태와 장애 원인은 아직 확정하지 않았습니다. 실제 장비에서의 해결 확인은 사용자가 수행합니다. 자동 테스트·Windows CI·네이티브 EXE·Release 결과는 [검증 기록](docs/BUILD_VALIDATION_KO.md)에 기록합니다.

## 0.3.3 — 2026-10-27

- MM 장비 찾기에서 `show switches`가 장비 정보와 Status/Configuration 정보를 별도 표로 출력할 때 발생하던 `SWITCH_TABLE_PARSE_FAILED` 수정
- 각 표의 행 수와 Total Switches 검증 유지, 잘림·알 수 없는 표·중복 IP·추가 행 거부
- 고정된 한국어 오류 사유 표시, CLI 원문·셀 값은 진단에 포함하지 않음
- 단일 표와 TCP loopback SSH 분리 표 발견·선택 WLC 회귀 검사 추가
- Linux·Windows 329개, 네이티브 EXE 단일/10대, Release 및 공개 다운로드 검증 완료

[검증 기록](docs/BUILD_VALIDATION_KO.md) · [실행 파일](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.3)

## 0.3.2 — 2026-10-27

- Windows에서 최초 신뢰 키를 동시에 저장할 때 발생한 잠금 파일 초기화 경합 수정
- 잠금 전 NUL 쓰기를 제거하고 기존 비차단 잠금·취소·기한·키 변경 차단·인증 전 검사 유지
- 결정적인 Windows 분기 회귀 및 실제 프로세스 동시 저장/충돌 검사 통과
- Linux·Windows 308개 테스트, 네이티브 EXE 단일/10대 실행, Release 게시 및 공개 다운로드의 SHA-256·구성 검증 완료

[최종 검증 기록](docs/BUILD_VALIDATION_KO.md)과 [v0.3.2 실행 파일](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.2)을 제공합니다. 실제 Aruba 장비와 Windows 11 실기는 사용자 검증 대상입니다.

## 0.3.1 — 2026-10-27 (게시 완료·병렬 CI 실패 기록)

- 0.3.0의 장비 발견·진단·최초 키 자동 저장 기능을 포함하며 런타임 정책과 의존성은 변경하지 않음
- 10대 각 300회 수집의 실작업자·SQLite·공정성·버퍼 기준은 유지하고 Windows runner의 처리 속도에 좌우되는 soak 테스트 대기를 안정화
- 패키지·Windows 빌드·대응 소스 ZIP 버전을 0.3.1로 구분. v0.3.0 태그는 변경하지 않음

[Windows Release](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40439196292)는 307개 테스트와 네이티브 EXE 단일/10대 데모 검증 후 [v0.3.1](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.1)을 게시했습니다. 같은 커밋의 [병렬 CI](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40439193538)는 초기 307개 테스트를 통과했지만 빌드 재검사에서 신뢰 키 동시 저장 테스트 1개가 실패했습니다(306개 통과). Windows 잠금 파일 초기화의 실제 경합을 확인했으며 후속 0.3.2에서 수정·검증했습니다. 이를 단순 테스트 불안정으로 분류하지 않습니다.

## 0.3.0 — 2026-10-27 (태그 보존·릴리스 차단)

- MM 이름/IP에서 장비 발견, 선택 장비 역할·모델·버전 검사와 공통 SSH 계정 실행 중 재사용
- 최초 키 질문 없이 자동 저장(TOFU), 변경 키·알고리즘과 신뢰 저장 실패는 인증 전 차단
- 명시적인 역할 근거만 사용하고 불명확한 AUTO는 추적 제외. 기존 수동 유형·관리 주소·MD 매핑 보존
- 연결/키/인증/발견/식별/MM/MD 매핑/MD 명령/해석/무선/저장 단계별 진단을 화면·SQLite·CSV/HTML에 기록
- 설정 v2 및 v1 읽기 호환, 기존 SQLite 진단 컬럼 추가. 단일/최대 10대 추적과 기존 LGPL 의존성 버전 유지
- CI·Windows 빌드의 pytest JUnit XML과 단일/10대 EXE 증거 보존

v0.3.0 태그의 [Windows Release 실행](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40438268055)은 10대 각 300회 soak 테스트의 60초 wall-clock 제한에 도달하여 차단됐습니다(306개 통과, 1개 실패). 실행 ZIP 생성과 Publish 단계는 수행하지 않았으며 공개 태그는 그대로 보존합니다. 후속 0.3.1에서 테스트 안정화를 검증했습니다. 사용자의 MD 오류 실제 원인은 미확정이며 자동 등록만으로 해결됐다고 주장하지 않습니다.

## 0.2.0 — 2026-10-27

- 기존 단일 추적 유지, 최대 10대 목록·선택 상세 및 대상별/전체 제어
- 대상별 독립 수집 상태·세션·취소/세대·버퍼와 공정한 순환, 실제 수집 최대 2개
- 장비별 명령 직렬화·최대 12개 연결의 공유 SSH 풀, 실패 후 재시도 대기와 소유별 승인/정리
- 대상별/통합 CSV·HTML 및 기존 SQLite 이력 호환, 대상 목록은 메모리만 유지
- 10대 오프라인 데모와 단일/다중 Windows EXE 스모크를 포함한 Actions 빌드 구성
- 공개 저장소 `sebia1993/aruba-client-live-tracker-` 연결, v0.2.0 문서와 대응 소스/체크섬 배포 구성

당시 검증 결과와 배포 상태는 [v0.2.0 검증 기록](docs/validation/v0.2.0/BUILD_VALIDATION_KO.md)을 확인하십시오. 실제 Aruba 장비와 Windows 11 실기는 별도 확인이 필요합니다.

## 0.1.0 — 2026-10-27 (과거 버전)

- 한국어 Qt 데스크톱, IP/MAC 검색 및 MM→등록 MD 단일 추적
- 보수적인 정상/실패/미등록 판정과 변경 이벤트
- 오프라인 데모, SQLite·로컬 CSV/HTML, 서버 키 검증
- PyInstaller onedir, Windows CI/태그 릴리스 구성

당시의 저장소 생성 권한 오류와 Wine 빌드 기록은 [v0.1.0 과거 검증](docs/validation/v0.1.0/BUILD_VALIDATION_KO.md)에 보존합니다. 과거 테스트 개수를 v0.2.0 결과로 사용하지 않습니다.
