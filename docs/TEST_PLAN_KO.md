# 테스트 계획과 검증 경계

## 자동 검증

```powershell
python -m pytest -q
python -m ruff check src tests scripts
python -m aruba_client_live_tracker.main --demo --smoke-test --data-dir smoke-single --smoke-result artifacts/source-single-smoke.json
python -m aruba_client_live_tracker.main --multi-demo --smoke-test --data-dir smoke-multi --smoke-result artifacts/source-multi-smoke.json
pwsh -File build_windows.ps1 -Version 0.2.0
```

테스트는 운영망에 연결하지 않고 합성 CLI·가짜 SSH·데모를 사용합니다. 실행 결과와 개수는 [검증 기록](BUILD_VALIDATION_KO.md)에 기록하며 아래 표는 요구되는 검증 범위입니다.

| 영역 | 실패 경계 |
|---|---|
| 기존 단일 회귀 | 입력/명령 주입·파서·MM/MD 라우팅·상태 이벤트·지표 단위·데모·SQLite |
| 다중 coordinator | 10대 등록·11대 거부·중복/후보 대기·개별/전체 제어·독립 오류/세션/시각 |
| 작업 격리 | 중지/제거/재시작 뒤 늦은 결과 폐기·취소/세대·DB/워커 오류 표시 |
| 스케줄링 | 실제 동시 제출 2개 이하·완료+주기·공정 순환·새로고침 중복 방지 |
| 공유 SSH | 같은 장비 명령 직렬·전체 연결 12개 이하·15초 재시도 대기·소유별 정리 |
| 키 승인 | 최초 승인/거절·변경 키 차단·여러 대상 승인 큐·대기 중 취소/종료 |
| 보고서 | 대상/세션 구분·기간·시각순·단일 호환·HTML escape/CSV 수식 방어 |
| GUI | 실제 창·목록/선택 상세·개별/전체 제어·전환 제한·10대 독립 데이터·종료 정리 |
| 반복 수집 | 대상별 그래프 240/이벤트 500 상한·세션/연결/메모리 정리 |
| 배포 | Windows PE x64·실제 frozen 단일/10대 스모크·JSON/종료 코드·소스/고지/ZIP/각 SHA |
| 공개 자료 | 비밀/운영 데이터 미포함·예시 주소·문서/패키지/태그 버전 일치 |

Windows 빌드는 두 EXE 스모크 모두 성공해야 ZIP을 만듭니다. Qt offscreen은 GUI 생성·수집·저장·종료 확인이며 실제 Windows 화면과 장비 부하 검증을 대체하지 않습니다.

## 사용자 실기 확인

1. 테스트용 SSH 권한과 관리자가 확인한 서버 키 지문을 준비합니다.
2. MM Primary/Standby·MD·`Current switch` 매핑을 등록합니다.
3. 알려진 단말의 IP/MAC 검색을 비교하고 명령별 실행 위치·권한·출력 의미를 ArubaOS 8.10 세부 버전에서 확인합니다.
4. AP/SSID/Role/VLAN·SNR·PHY Rate·필드 단위·Tx/Rx 방향을 같은 시각 CLI와 비교합니다.
5. 이동/로밍·SSH 경로 실패·승인된 MM 장애 전환/MD 변경을 재현하여 오판과 키 승인을 확인합니다.
6. 1대부터 10대까지 늘려 순환 간격·장비 부하·대상별 오류 격리를 확인합니다.
7. 개별/전체 일시 정지·재개·중지·제거와 대상/통합 보고서를 확인합니다.
8. Windows 11 일반 사용자, 1366×768·125%·150% 배율에서 두 화면·설정·승인·이력을 확인합니다.
9. 장시간 실행 후 메모리·연결·DB 크기와 안전한 종료를 확인합니다.

실제 장비 테스트는 사용자가 수행합니다. 계정/주소/원문 출력을 요청하거나 저장하지 않습니다. 공유 자료는 원문·주소·SSID·사용자 정보를 비식별화하십시오. Wine의 Windows EXE 실행도 Windows 11 실기를 대체하지 않습니다.
