# 테스트 계획과 검증 경계

## 자동 검증

```powershell
python -m pytest -q --junitxml=artifacts/pytest-local.xml
python -m ruff check src tests scripts
python -m aruba_client_live_tracker.main --demo --smoke-test --data-dir smoke-single --smoke-result artifacts/source-single-smoke.json
python -m aruba_client_live_tracker.main --multi-demo --smoke-test --data-dir smoke-multi --smoke-result artifacts/source-multi-smoke.json
pwsh -File build_windows.ps1 -Version 0.3.0
```

테스트는 운영망에 연결하지 않고 합성 CLI·가짜 SSH·데모를 사용합니다. 실행 결과와 개수는 [검증 기록](BUILD_VALIDATION_KO.md)에 기록하며 아래 표는 요구되는 검증 범위입니다.

| 영역 | 실패 경계 |
|---|---|
| 기존 단일 회귀 | 입력/명령 주입·파서·MM/MD 라우팅·상태 이벤트·지표 단위·데모·SQLite |
| 다중 coordinator | 10대 등록·11대 거부·중복/후보 대기·개별/전체 제어·독립 오류/세션/시각 |
| 작업 격리 | 중지/제거/재시작 뒤 늦은 결과 폐기·취소/세대·DB/워커 오류 표시 |
| 스케줄링 | 실제 동시 제출 2개 이하·완료+주기·공정 순환·새로고침 중복 방지 |
| 공유 SSH | 같은 장비 명령 직렬·전체 연결 12개 이하·15초 재시도 대기·소유별 정리 |
| 서버 키 TOFU | 최초 질문/opt-in 없이 저장·기존 키 재사용·키/알고리즘 변경 인증 전 차단·저장 실패·다른 MM 우회 없음 |
| 신뢰 파일 동시성 | Windows/POSIX 프로세스 간 잠금·동시 새 키 보존·잠금 대기 중 취소/기한·원자적 저장 |
| 장비 발견 | 고정 allowlist·합성 switches/version/switchinfo·seed 기본 선택·선택 장비만 검사·최대 2개·중지/종료 |
| 역할/설정 | 명시적 Type 근거·self 식별 모호성·master/local 추정 금지·AUTO 제외·수동 유형/주소/매핑 보존·충돌 |
| 자격 증명 | 발견/추적 실행 중 재사용·계정 변경/종료 참조 폐기·설정/DB/보고서 미포함 |
| 진단/마이그레이션 | 단계/코드/장비/명령·오류와 부재 구분·IP Address 헤더·설정 v1 읽기/v2 저장·기존 DB 진단 컬럼 추가 |
| 보고서 | 대상/세션 구분·기간·시각순·단일 호환·단계별 진단·HTML escape/CSV 수식 방어 |
| GUI | 실제 창·목록/선택 상세·개별/전체 제어·전환 제한·10대 독립 데이터·종료 정리 |
| 반복 수집 | 대상별 그래프 240/이벤트 500 상한·세션/연결/메모리 정리 |
| 배포 | Windows PE x64·실제 frozen 단일/10대 스모크·JSON/종료 코드·소스/고지/ZIP/각 SHA |
| 공개 자료 | 비밀/운영 데이터 미포함·예시 주소·문서/패키지/태그 버전 일치 |

pytest JUnit XML과 스모크 JSON을 CI 아티팩트로 보존합니다. Windows 빌드는 두 EXE 스모크 모두 성공해야 ZIP을 만듭니다. Qt offscreen은 GUI 생성·수집·저장·종료 확인이며 실제 Windows 화면과 장비 부하 검증을 대체하지 않습니다.

## 사용자 실기 확인

1. 테스트용 읽기 전용 SSH 권한과 MM 관리 주소를 준비합니다. 최초 키는 질문 없이 자동 저장되며 변경 키는 차단되는 동작을 확인합니다.
2. MM 이름/IP로 발견하고 선택 장비를 검사합니다. 역할·모델·버전·진단과 MM Primary/Standby·MD·`Current switch` 매핑을 검토하고 기존 수동 설정 보존을 확인합니다.
3. 알려진 단말의 IP/MAC 검색을 비교하고 명령별 실행 위치·권한·출력 의미를 ArubaOS 8.10 세부 버전에서 확인합니다.
4. AP/SSID/Role/VLAN·SNR·PHY Rate·필드 단위·Tx/Rx 방향을 같은 시각 CLI와 비교합니다.
5. 이동/로밍·SSH 경로 실패·MM 장애 전환/MD 변경을 재현하여 오판 방지·키 변경 차단·단계별 진단을 확인합니다.
6. 1대부터 10대까지 늘려 순환 간격·장비 부하·대상별 오류 격리를 확인합니다.
7. 개별/전체 일시 정지·재개·중지·제거와 대상/통합 보고서를 확인합니다.
8. Windows 11 일반 사용자, 1366×768·125%·150% 배율에서 두 화면·간편 설정·발견·진단·이력을 확인합니다.
9. 장시간 실행 후 메모리·연결·DB 크기와 안전한 종료를 확인합니다.

실제 장비 테스트는 사용자가 수행합니다. 계정/주소/원문 출력을 요청하거나 저장하지 않습니다. 공유 자료는 원문·주소·SSID·사용자 정보를 비식별화하십시오. Wine의 Windows EXE 실행도 Windows 11 실기를 대체하지 않습니다.
