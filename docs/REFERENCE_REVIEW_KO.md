# 기존 프로젝트 검토 및 재사용 판단

검토일: 2026-10-27. 원본 저장소는 읽기 전용으로 검토했다. 이 문서는 신규 프로그램의 설계 근거이며, 기존 프로젝트의 테스트 통과나 실제 장비 검증을 신규 프로그램의 검증 결과로 대신하지 않는다.

## 검토 대상과 라이선스

| 우선순위 | 저장소 | 검토한 커밋 | 라이선스 |
|---|---|---|---|
| 1 | [Aruba Session Tracker](https://github.com/sebia1993/aruba-session-tracker-1) | `e5835b946f88a43cbd237c5a5a930780dbcb3d1c` | MIT, Copyright (c) 2026 sebia1993 |
| 2 | [Aruba Cluster Health Dashboard](https://github.com/sebia1993/aruba-cluster-health-dashboard) | `093da81d55b2c8bc1e260177c55aaa3bb74b2530` | MIT, Copyright (c) 2026 sebia1993 |
| 3 | [Aruba Wireless Policy Mapper](https://github.com/sebia1993/aruba-wireless-policy-mapper) | `57960fbc08a981a9e7f2892244c8658024b4288b` | MIT, Copyright (c) 2026 sebia1993 |
| 4 | [Multi Target Ping Monitor](https://github.com/sebia1993/multi-target-ping-monitor) | `9eeabc1fc6e9fd2ef488bc9a3647f4ca7eea075d` | MIT, Copyright (c) 2026 sebia1993 |

네 프로젝트의 LICENSE를 직접 확인했다. 코드를 복사하거나 상당 부분을 수정해 사용하면 원저작권 및 MIT 허가 고지를 보존해야 한다. 아래 추천은 구조와 동작 원리의 재사용에 관한 것이며, 이 검토 작업 자체는 기존 소스 코드를 신규 프로젝트에 복사하지 않았다. 실제 재사용 파일은 배포용 서드파티 고지와 함께 검토한다.

## 1. Aruba Session Tracker

### 우선 검토 파일

- `src/aruba_session_tracker/collectors/ssh.py`: 연결 전 서버 키 승인, SHA-256 지문, 엄격한 known_hosts 검증, 취소 토큰, 조회 전체 제한 시간, 출력 크기 및 연결 개수 제한을 갖춘 읽기 전용 수집 계층이다. 비밀번호를 일반 진단 문자열에 포함하지 않는 오류 분류와 안전한 실패 전환이 유용하다.
- `src/aruba_session_tracker/parsers/global_users.py`: MM의 `Current switch`를 고정 폭 헤더/구분선으로 해석한다. 정상적인 0건과 출력 잘림·알 수 없는 형식을 구분하고, 하나 이상의 후보를 구조화한다. 공백으로 무조건 분리하면 AP/사용자 이름과 열 경계가 깨질 수 있다는 점을 확인했다.
- `src/aruba_session_tracker/services/tracker.py`: MM 탐색 결과를 등록 MD로 연결하고, 매핑 누락·중복을 오류로 처리한다. 정상 근거 여부를 `authoritative`로 전달한다. 기존 프로젝트의 선택적 전체 MD 탐색은 이번 요구사항과 맞지 않아 채택하지 않는다.
- `src/aruba_session_tracker/services/monitoring.py`: 수집 성공과 실제 세션 누락을 분리하고, 정상 관측의 연속 누락으로 종료를 판단한다. 조회 실패 때 수명 상태를 변화시키지 않는 원칙과 시작·취소·중지 상태 분리가 적합하다. 기존 것은 네트워크 세션 추적이므로 무선 클라이언트의 AP 로밍 규칙으로 그대로 사용할 수 없다.
- `src/aruba_session_tracker/ui/`: `main_window.py`의 Qt 백그라운드 작업, `shutdown.py`의 종료 절차, `theme.py`의 맑은 고딕·고대비 처리, `noc_console.py`의 정보 밀도 높은 배치를 검토했다. 신규 UI에는 클라이언트 상태와 무선 품질 중심의 별도 화면을 구성한다.
- `src/aruba_session_tracker/storage/`: SQLite 이력 저장, 스트리밍 조회, 원자적 CSV 쓰기, HTML 생성과 디스크 오류 처리를 검토했다. `csv_export.py`의 수식 주입 방지와 UTF-8 BOM은 로컬 보고서에 적합하다. 대용량 세션·원문 번들·삭제 복구 구조 전체를 이식할 필요는 없다.
- `build_windows.ps1`, `.github/workflows/ci.yml`, `release.yml`, `continuous.yml`, `nightly.yml`, `docs-screenshots.yml`: Windows에서 실제 실행 파일을 만들고 검사하며, 소스 ZIP과 실행 ZIP을 구분하는 배포 구조를 확인했다. 깨끗한 커밋, 버전/태그 일치, 의존성 고정, 라이선스 수집, GUI 실행 시험, 태그 릴리스에 대한 원칙을 참고한다.

### 신규 구현에 반영할 판단

MM에서 클라이언트 정체성을 확정하고 담당 MD 한 대만 조회한다. IP에 여러 MAC이 매칭되면 선택을 요구한다. 선택한 MAC을 추적 정체성으로 유지해야 IP 변경이나 IP 재사용 때 다른 사용자를 추적하는 실수를 피할 수 있다. 서버 키 변경·인증 거부는 단순 네트워크 불통과 구분한다. 실패한 조회는 연결 해제나 로밍 근거로 사용하지 않는다.

## 2. Aruba Cluster Health Dashboard

`src/aruba_mini_dashboard/models.py`는 `UNKNOWN`, `MISSING`, `DOWN`을 구분하고 파싱 완성도를 `COMPLETE/PARTIAL/FAILED`로 관리한다. `services/poll_coordinator.py`는 Qt 작업 스레드와 조회 중 상태를 조정하고, 중복 수집을 방지하며 다음 조회 시각을 계산한다. 장비 연결 상태와 관측값 품질을 구분하는 표시 및 사용자에게 보이는 진행 상태가 재사용할 만하다.

기존 대시보드에는 `remediation/` 아래 장비 조치 기능도 존재한다. 이번 프로그램은 모든 네트워크 동작이 조회 전용이어야 하므로 해당 계층과 SSH 설정 변경/운영 조치 기능은 재사용 대상에서 제외한다.

## 3. Aruba Wireless Policy Mapper

`hostkeys.py`, `ssh_connection.py`에서 자격 증명 전 서버 키 확인, 앱별 known_hosts, 키 변경 차단과 키 알고리즘 검증을 확인했다. `collection_health.py`는 선택 명령 일부 실패를 전체 성공으로 표현하지 않고 영향 범위와 한국어 안내를 제공한다. `diagnostic_codes.py`의 사용자 조치 중심 안내와 `redaction.py`의 민감 정보 처리 원칙이 유용하다.

`aos8_parser.py`는 SSID→Virtual AP→AAA Profile→Role 정책 관계 및 사용자 테이블의 관측 Role을 다룬다. 구성상의 기본 Role은 클라이언트에게 실제 적용된 Role과 다를 수 있다. 신규 프로그램은 현재 사용자 조회 결과에서 실제 Role을 읽고, 정책 설정만으로 사용자의 인증 성공이나 권한을 단정하지 않는다. 전체 설정과 전체 사용자 테이블 수집은 신규 프로그램에 도입하지 않는다.

## 4. Multi Target Ping Monitor

`app/ui/main_window.py`에서 QThread/QTimer, 중지 이후 늦게 도착한 결과의 요청 ID 검사, 그래프 이력 캐시를 확인했다. `tests/test_worker.py`, `tests/test_soak_test.py`, `tests/test_main_window.py`, `scripts/soak_test.py` 및 `scripts/run_stability_soak_suite.py`는 반복 실행과 종료 검증의 참고 자료다. `build_windows_exe.ps1`과 `scripts/verify_release.py`, `verify_release_assets.py`는 실행 파일과 배포 자산의 구분·검증을 참고할 수 있다.

ICMP 실패는 무선 연결 해제의 직접 증거가 아니므로 Ping 판정 로직을 Aruba 무선 상태 판정으로 복사하지 않는다. SSH 실패 이후 이전 데이터가 새 데이터처럼 표시되지 않도록 수집 시각과 마지막 정상 시각을 따로 유지한다.

## 재사용 경계와 남는 위험

| 항목 | 결정 | 이유 |
|---|---|---|
| 원본 런타임 파일 의존 | 사용하지 않음 | 신규 프로젝트를 독립 실행·배포하기 위함 |
| 서버 키 지문 승인·키 변경 차단 | 동작 원칙 반영 | 최초 연결 신뢰 확인 및 위장 서버 차단 |
| 전체 MD 자동 탐색 | 사용하지 않음 | 사용자가 금지한 동작이며 장비 부하 증가 가능 |
| 장비 설정 변경·복구 명령 | 사용하지 않음 | 조회 전용 요구사항 |
| 수집 실패를 연결 해제로 판정 | 사용하지 않음 | 관측 불가와 실제 장애의 혼동 방지 |
| 기존 출력 테스트 자료 | 구조 참고, 가상 값 사용 | 공개 저장소에 운영 정보 혼입 방지 |
| 기존 프로그램의 인증·Role 정책 해석 | 의미 참고 | 정책 구성과 실제 적용 결과를 구분 |
| Qt/SSH/암호 라이브러리 배포 | 각 라이선스 별도 준수 | 프로젝트 MIT가 의존성의 LGPL/기타 의무를 대체하지 않음 |

기존 코드와 공식 문서가 있어도 ArubaOS 패치 버전, 클러스터 UAC/AAC 위치, CLI 권한, 화면 폭 및 출력 형식의 차이가 남는다. 실장비 접속은 수행하지 않았으며, 자동 테스트 자료는 실제 장비 출력이 아니라 비식별 가상 자료다.
