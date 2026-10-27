# 변경 이력

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
