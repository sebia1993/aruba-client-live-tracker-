# v0.2.0 다중 모니터링 실행 계획

승인 범위: 기존 단일 추적 유지, 최대10대, 목록+선택 상세, 개별/전체 제어, 대상별/통합 CSV·HTML. 외부 계정/장비 정보 요청 없음. 공개 원격은 sebia1993/aruba-client-live-tracker- (끝 하이픈 포함).

- [x] 공유 SSH 풀: 장비별 직렬, 전체 수집2개, 연결12개, 네트워크 실패15초 대기, 승인/취소 작업 격리
- [x] 대상별 coordinator: ID/세대/Tracker/collector/session/cancel/시각/버퍼 격리, 중복/늦은 응답/공정한 순환
- [x] 다중 GUI: 등록/붙여넣기/선택 상세, 개별/전체 시작·중지·일시정지·재개·새로고침, 승인 큐
- [x] 통합 보고서와10대 데모: 기존 DB 유지, 대상·세션 식별, 시각순, 안전한 HTML/CSV
- [x] 단일 회귀/10대 반복/동시성/GUI/보안 검증 및 독립 리뷰
- [ ] v0.2.0 문서/화면/Windows Actions 빌드/실제 EXE smoke/Release ZIP·SHA·소스

## 공통 계약
새 monitoring.py는 Qt 비의존 coordinator다. UI 주 스레드가 tick()으로 완료 큐를 처리하고 반환된 대상 ID 목록을 다시 그린다. worker는 collector.poll만 호출하며 UI/SQLite를 변경하지 않는다. 최대2개 ThreadPoolExecutor, 실제 제출 작업도2개까지. context 상태 stopped/running/paused/selection_required/duplicate. 각 context에는 id,target,tracker,collector,session_id,generation,cancel,in_flight,view,last_result,next_due,samples(240),events(500)가 있다.

MonitoringCoordinator(store,collector_factory,interval=15): contexts dict; add(text)->id; add_many(text)->(ids,errors[(line,message)]); start(id),stop(id),pause(id),resume(id),refresh(id),remove(id),select_candidate(id,mac),set_interval(seconds),tick()->list[id],close(wait=False)->bool. factory(context)->collector. busy는 실제 작업 남음, active는 stopped 이외 실행/대기 상태 존재. stop/remove는 세대를 무효화하며 완료후소유 collector만close한다. 추가/선택 변경은 다른대상을초기화하지않는다. 동일 MAC은 처음등록된활성대상을우선하고 새대상을duplicate 대기시킨다.

SharedSessionPool(credentials,known_hosts,approve_host_key,max_connections=12,cooldown=15); pool.for_owner(id) -> command_runner; pool.close(). approve callback(owner_id,device,algorithm,fingerprint,deadline,cancel)->bool. LiveCollector 기존인자+keyword command_runner=None. collector.close()는 owner만해제. 기존 단일독점동작도 유지.

HistoryStore.export_many_csv(session_ids,path,start=None,end=None),export_many_html(...): 기존export API유지, 기존스키마유지. demo에10개MAC/IP고정목록추가, 개별collector상태독립.

## 구현 판단
기본15초·공통10/15/30/60초, 완료+주기. 데모/실장비/추적방식/장비설정은전체중지후변경. 대상목록은메모리만보관, 이력은기존SQLite영구보존. 정상부재판정/서버키거부보안은v0.1그대로. 워커처리와DB저장오류도사용자에게표시하고다른대상을계속수집한다.

## 검토 반영
공유 풀의 닫힌 owner 누적 및 UI의 삭제 대상 원문 캐시 누적을 회귀 테스트로 수정했다. 한 대상의 SQLite 시작 실패는 해당 대상에만 안내하며 다른 대상은 계속 수집한다. 이전 대상의 MM/MD 상태가 새 대상에 표시되지 않도록 상세 화면을 초기화한다.
