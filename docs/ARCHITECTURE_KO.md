# 구조와 데이터 흐름

독립 패키지 `aruba_client_live_tracker`는 UI·수집·해석·상태 비교·저장을 분리합니다. 다른 저장소의 런타임 파일을 읽지 않습니다.

IP/MAC 검증 → Primary MM(통신 실패 시 Standby) → 후보 선택 → `Current switch`의 등록 MD 매핑 → 해당 MD 읽기 전용 조회 → 파서 → 대상별 Tracker → Qt 상세/목록·SQLite → CSV/HTML 순서입니다. 미등록 MD를 전체 탐색하지 않습니다.

`models.py`는 장비/식별/대상/관측/이벤트/진단 계약, `commands.py`는 입력 정규화와 허용 명령 생성, `parsers.py`는 알려진 출력 해석을 담당합니다. 불완전한 출력을 미등록 0건으로 바꾸지 않습니다. `collector.py`는 MM→MD 라우팅과 지표 수집, `ssh.py`는 서버 키·타임아웃·출력 상한을 관리합니다.

## 장비 발견과 진단

`DiscoveryService`는 MM seed에서 `show switches`를 읽고 사용자가 선택한 장비만 `show version`·`show switchinfo`로 검사합니다. 내부 공유 SSH 풀과 최대 2개 검사 작업을 사용하며 워커는 Qt 객체에 접근하지 않습니다. 목록 발견을 자동 반복하거나 비선택 주소를 탐색하지 않습니다. `merge_discovered`는 기존 수동 유형·관리 주소·매핑을 보존하고 충돌 진단을 반환합니다.

장비의 `identity`는 hostname/switch IP/보고 역할/model/version/관측 시각/출처를 보존하며 `origin`은 수동 또는 발견입니다. `Type`의 conductor/standby/MD 등 명시적 근거로만 역할을 확정합니다. seed 자기 행이 불분명하면 Primary를 추정하지 않고 AUTO는 수집과 공유 추적 풀에서 제외합니다.

`Diagnostic`은 stage/code/message/device_name/endpoint/command/at/severity를 보존합니다. 단계는 연결·서버 키·인증·발견·식별·MM 조회·MD 매핑·MD 명령·해석·무선·저장이며 비밀번호와 예외 원문은 기록하지 않습니다. `PollResult.diagnostics`는 기본 빈 목록으로 기존 호출을 유지합니다. 사용자의 기존 MD 오류 원인은 미확정이며 새 진단의 존재를 원인 해결로 해석하지 않습니다.

## 다중 수집

`monitoring.py`의 Qt 비의존 coordinator가 최대 10개 대상 context를 관리합니다. 각 대상은 고유 ID·세대·Tracker·collector·세션·취소 신호·마지막 결과·다음 시각과 독립 버퍼를 가집니다. 상태는 중지/실행/일시 정지/후보 선택/중복 대기로 구분합니다. 중지·제거 시 세대를 무효화하여 늦게 끝난 결과가 다른 대상에 섞이지 않게 합니다.

ThreadPoolExecutor 워커와 실제 제출 작업은 전체 최대 2개입니다. 워커는 수집만 하고 완료 큐를 주 스레드의 `tick()`이 처리하여 UI와 SQLite를 갱신합니다. 대상은 공정하게 순환하고 다음 조회는 완료+공통 주기로 계산합니다. 중복 작업을 누적하지 않습니다. 한 대상의 오류·후보 대기·취소가 다른 대상의 상태를 덮어쓰지 않습니다.

`session_pool.py`는 공유 SSH 연결을 최대 12개로 제한하고 장비별 명령을 직렬화합니다. 수집기는 소유자별 runner를 사용하고 종료 시 자기 소유만 해제합니다. 네트워크 실패 뒤 15초 재시도 대기를 적용합니다. 최초 키는 질문 없이 자동 저장하고 변경된 키·알고리즘 및 신뢰 저장 실패는 인증 전에 차단합니다. 다른 MM으로 우회하지 않습니다. 신뢰 저장은 Windows msvcrt/POSIX flock의 프로세스 간 잠금과 원자적 교체를 사용하며 대기 중 취소와 기한을 지킵니다. 기존 승인 콜백 인자는 호환용으로 남을 수 있지만 호출하지 않습니다. 취소는 소유 대상에 귀속됩니다. 기존 단일 추적 경로도 유지합니다.

`tracker.py`는 정상 관측 사이의 연결/로밍/정책/품질 변화를 판정합니다. 오류이면 마지막 유효 값을 보존하고 비교 연속성을 끊습니다. 그래프는 대상별 최대 240개, 이벤트 버퍼는 500개로 제한합니다.

## 저장과 배포

설정은 장비 식별 정보와 등록 출처를 포함한 v2로 저장하고 v1도 계속 읽습니다. v1에서 누락된 kind는 기존 MD 기본값을 보존합니다. `storage.py`는 기존 SQLite에 `polls.diagnostics TEXT NOT NULL DEFAULT '[]'` 컬럼을 추가하고 단일 export API를 유지하면서 여러 세션을 대상·세션 식별 및 시각과 함께 CSV/HTML로 내보냅니다. 대상 목록은 메모리만 유지하고 수집 이력은 영구 저장합니다. 장시간 실행하면 DB 크기가 증가합니다. `demo.py`는 같은 수집 인터페이스로 대상마다 독립 가상 시나리오를 제공합니다.

공통 SSH 계정은 발견과 추적에서 앱 실행 중 재사용하고 풀 정리와 별도로 관리합니다. 종료·계정 변경 시 참조를 폐기하며 계정과 비밀번호를 파일에 저장하지 않습니다. CLI 원문은 기존처럼 메모리에만 보관하고 진단은 SQLite와 CSV/HTML에 남깁니다. 원문 CLI와 보고서는 로컬 정보이며 공개 로그나 Git에 넣지 않습니다. PyInstaller onedir 배포는 Qt DLL을 동적으로 유지하고 `SOURCE`에 새 모듈·테스트·문서·빌드 워크플로를 재귀적으로 포함합니다. Windows Actions는 pytest JUnit XML과 실제 단일/10대 EXE 스모크 결과 JSON을 보존하도록 구성합니다.
