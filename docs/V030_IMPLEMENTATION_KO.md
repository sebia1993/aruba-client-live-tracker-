# v0.3.0 실행 계획 및 진행 기록

기준: e304190. 사용자 승인: MM 이름/IP에서 장비 목록 발견, 공통 SSH 계정, 최초 연결부터 서버 키 질문 없음, 변경 키 차단. 기존 단일/10대 모니터링 유지. 실제 장비 접속/운영 데이터 요청 없음. 원격 sebia1993/aruba-client-live-tracker-에 검증 후 Windows Release v0.3.0 게시.

## 작업
- [x] 최초 키 자동 저장, 변경 차단, 프로세스 간 저장 잠금 및 SSH 테스트
- [x] MM 발견 서비스, 역할/모델/주소 해석, 선택 장비 검사 및 설정 v2 호환
- [x] 수집 단계별 진단, IP Address 헤더 호환성, 파서·수집 테스트
- [x] SQLite 진단 컬럼 업그레이드와 CSV/HTML 진단
- [x] 한국어 간편 설정/발견 화면, 승인 UI 제거, 계정 재사용, GUI 검증
- [x] 통합 테스트·독립 리뷰·Windows 빌드·Release·다운로드 검증

## 공통 인터페이스와 소유 경계

모델은 root 소유. Device는 기존 인자 순서를 유지하고 identity: DeviceIdentity|None, origin='manual'을 추가한다. 내부 생성자의 kind 기본 MD는 기존 호출과 호환하고 새 GUI 등록은 AUTO를 명시한다. DeviceIdentity는 hostname/switch_ip/reported_role/model/version/observed_at/source 문자열이다. origin은 manual 또는 discovered. 기존 수동 유형·주소·매핑은 발견 결과로 덮어쓰지 않는다. AUTO는 실제 추적/공유 풀에 전달하지 않는다.

Diagnostic(stage,code,message,device_name='',endpoint='',command='',at=utc_now(),severity='오류')와 DIAGNOSTIC_STAGE_LABELS를 models에서 제공한다. 단계 키: connect,host_key,auth,discovery,identity,mm_lookup,md_mapping,md_command,parse,wireless,storage. PollResult.diagnostics는 list[Diagnostic], 기본 빈 목록. 비밀번호나 raw 예외 문자열을 진단에 넣지 않는다.

DiscoveryService(credentials,known_hosts) / discover(seed:Device,cancel=None)->DiscoveryResult / probe(devices:list[Device],cancel=None)->DiscoveryResult / close(). DiscoveryResult는 devices:list[Device],diagnostics:list[Diagnostic],collected_at:str. 서비스는 발견 전용 SSHSession과 최대 2개 probe 작업을 사용하며 각 검사 후 연결을 닫는다. 추적용 SharedSessionPool의 AUTO 제외 규칙을 유지한다. 작업자에서 Qt 호출 없음. merge_discovered(existing,discovered)->tuple[list[Device],list[Diagnostic]]를 제공한다. GUI는 저장 전 merge 및 충돌을 보여준다. 명령 추가는 discovery 담당이 commands.py에 고정 show switches/show version/show switchinfo만 허용한다. topology 반복 자동 폴링 없음. seed와 선택한 장비만 연결하며 미확정·비선택 장비를 임의 탐색하지 않는다.

SSHSession과 SharedSessionPool은 기존 approval 콜백 인자를 선택 인자로 유지할 수 있지만 절대 호출하지 않는다. 최초 키 자동 저장은 모든 앱 연결의 기본 동작이며 opt-in UI 없음. 기존 known_hosts 유지. 저장 실패·키/알고리즘 변경은 인증 전 차단하고 다른 MM으로 우회하지 않는다. 잠금 대기에도 취소/시간 제한 적용. 새 외부 런타임 의존성 없이 Windows msvcrt / POSIX flock 사용.

GUI SettingsDialog 확장은 별도 ui_discovery.py로 분리 가능. MainWindow의 credential cache는 장비 발견과 추적에서 앱 실행 중 재사용하며 pool 정리와 분리한다. 종료/계정 변경 시 참조 폐기. 기존 설정은 전체 추적 중지 후 변경한다. 목록의 seed 기본 선택, 나머지는 체크 선택과 전체 선택. 비밀정보 저장 없음.

설정 v2는 Device 확장 필드를 저장하고 v1도 읽는다. 기존 v1의 누락 kind는 MD로 보존. 모델/역할이 불명확한 AUTO는 판별 불가로 남기고 활성 추적에서 제외한다. MM self identity가 어느 행인지 확정되지 않으면 Primary 추정 금지. Type conductor/standby/MD만 자동 확정하며 모델명/사용자 표시 이름으로 역할을 추정하지 않는다.

SQLite는 polls.diagnostics TEXT NOT NULL DEFAULT '[]'를 추가한다. 원문은 기존대로 메모리에만 둔다. 기존 DB 및 보고서 API 유지, 새 보고서에 단계/코드/장비/명령/메시지 포함. 현재 MD 실패의 실제 원인은 안내 문구 미제공으로 미확정이며 자동 등록만으로 해결 완료를 주장하지 않는다.

## 판단 기록
- 서로 다른 파일의 독립 작업을 병렬 진행한다. 공유 모델은 root가 먼저 고정하며 파일 소유 경계를 지킨다.
- 기존 배포/테스트 데이터와 신뢰 키를 보존한다. 버전별 검증 기록은 이전 결과를 새 결과로 재사용하지 않고 분리한다.
- 기존 동작의 178개 테스트를 기준으로 검증하고 의미가 바뀐 최초 승인 테스트만 새 요구사항으로 갱신한다.

- 발견·설정 목록은 1,000대 경계에서도 화면 행과 장비 식별을 보존하도록 검증한다.
- 공개 데이터 검사는 테스트의 정확한 ArubaOS 버전·netmask 문자열만 주소 검사에서 구분하며 일반 IP 예외를 넓히지 않는다.

최종 배포는 v0.3.2다. v0.3.0 반복 테스트의 처리 속도 의존성과 v0.3.1 Windows 동시 최초 키 저장 경합을 수정했다. 실패/재현/검증/배포 내역은 BUILD_VALIDATION_KO.md 및 버전별 validation에 보존한다.
