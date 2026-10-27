# v0.3.7 오류 예방 점검과 검증

2026-10-27, 기준 커밋 `5035a1de1f89f4b9ec536f783e4ea7458a31db0a`의 깨끗한 작업 트리에서 점검했습니다. 기준 Windows 전체 검사는 567개 통과(78.47초)였습니다. 기존 v0.3.6 코드·운영 데이터·태그를 보존하고 새 버전으로 구분했습니다.

## 확인한 원인과 회귀

| 재현된 결함 | 수정 | 확인 방법 |
|---|---|---|
| 취소 감시기가 SSH client를 분리한 후 Paramiko transport가 늦게 생성되어 남음 | 연결 함수가 소유한 client를 실패 시 직접 정리 | 실제 루프백 SSH와 지연 resolver; 취소/시간 초과 2개 RED → GREEN, 인증 시도 0 |
| 중복 MAC 대상이 이미 유휴이면 수집기/공유 소유권이 남음 | 진행 중 작업이 없는 중복 대상의 수집기 해제 | 결과 도착 순서 2종과 공유 풀 재시작 3개 RED → GREEN; 이력·관측 보존, 연결 종료 1회 |
| 이전 발견 작업의 finally가 새 검사 서비스 참조를 지움 | 정리 중인 서비스가 현재 참조일 때만 비움 | 스레드 경계를 고정해 취소가 현재 서비스를 닫는지 RED → GREEN |
| 이력 목록의 기본 500행 정리가 최신 세션을 제거 | 저장 세션 목록에는 전체 개수를 사용, 최신순 유지 | 실제 SQLite 501세션 전부 표시·선택·정렬 RED → GREEN |
| 종료 기록 저장 실패 후 중지 버튼이 꺼져 재시도 불가 | 종료 대기 session_id가 있으면 중지 활성화 | 실제 SQLite 쓰기 잠금 후 버튼 재시도로 미종료 세션 0, RED → GREEN |

변경된 운영 순서는 없습니다. 시작/중지·취소·조회·내보내기의 기존 경로를 복구합니다. 스키마, 인증 정보 저장, 서버 키 정책, 조회 명령과 Aruba 출력 의미는 변경하지 않았습니다. 실제 장비 동작을 합성 자료에서 확인했다고 보고하지 않습니다.

## 검증 증거

새 회귀 8개와 관련 기존 테스트를 통과했으며, 독립 검토에서 중요한 결함·회귀 지적은 없었습니다. 전체 통합과 Windows 빌드의 최종 수치는 아래에 기록하며 빌드 당시 XML·EXE JSON은 ZIP의 validation 폴더에 포함됩니다. 게시 후 검증은 [main의 최신 기록](https://github.com/sebia1993/aruba-client-live-tracker-/blob/main/docs/BUILD_VALIDATION_KO.md)을 확인하십시오.

Windows 11/Python 3.12 전체 통합 검사: **575개 통과, 실패·오류·건너뛰기 0, 69.66초**. `artifacts/audit-final-20261027.xml`에 기록했습니다. 독립 검토자는 새 회귀 8개와 기존 SSH·풀·모니터링 96개를 별도로 확인했습니다.

## 로컬 Windows EXE

Windows PowerShell 5.1로 `build_windows.ps1 -Version 0.3.7 -SkipInstall`을 실행했습니다. 빌드 재검사 **575개 통과(71.00초)**, Ruff, 고정 의존성 공지 검사, 실제 EXE 단일/10대 관측 검사가 성공했습니다. 빌드 식별자는 `0.3.7-993a9d3669e0`, 소스 SHA-256은 `993a9d3669e0d9dc936d82bfbfc6084decbc9967ef33570cbdaaa2402a95cc33`입니다.

새 한글·공백 경로에 전체 ZIP을 풀고 별도 한글 임시 폴더와 Python을 제외한 자식 PATH로 단일 5회·10대 5회를 재실행했습니다. 매번 대상별 5개 관측·독립 MAC·SQLite 저장·종료 기록을 확인해 총 275개 관측이 모두 통과했습니다. ZIP 749항목, SOURCE 231파일 해시와 `.git` 없는 재내보내기, 서드파티 소스 6개 고정 해시를 확인했습니다. 미서명 AMD64 GUI/asInvoker 배포입니다. 인터넷을 물리적으로 차단한 시험은 아닙니다.

실제 Windows 11/1920×1080·100% EXE 창에서 합성 이력 501개에 데모 세션을 추가해 502·501번 최신 세션이 목록 위에 남는 것을 확인했습니다. 별도 SQLite 연결로 쓰기 잠금을 걸어 `HISTORY_END_FAILED`를 재현했고, 중지 버튼이 활성 상태를 유지했습니다. 잠금을 해제하고 같은 버튼을 다시 누르자 오류 안내가 사라지고 502개 세션의 미종료 기록이 0개가 됐습니다. 실제 운영 DB와 디스플레이 설정은 변경하지 않았습니다. 125%·150%/낮은 해상도 검증은 [v0.3.6 기록](validation/v0.3.6/BUILD_VALIDATION_KO.md)에 있으며 이번 버전에서 새로 수행한 것으로 계산하지 않습니다.

| 로컬 파일(dist/) | 바이트 | SHA-256 |
|---|---:|---|
| ArubaClientLiveTracker_v0.3.7_windows_x64.zip | 40408736 | `f48b2a13a3fdb7f300746684236979213f91f329e35436fe4f46ea8056bca288` |
| ArubaClientLiveTracker_v0.3.7_third_party_sources.zip | 72212226 | `14392d6ea3a819d3cf751fe830432b06f1f65bad851d40b06ecb22634cd45595` |

로컬 증거: `artifacts/build-windows11-v037.txt`, `artifacts/local-package-v037.json`. 로컬 ZIP과 GitHub runner ZIP은 빌드 환경에 따라 바이트가 다르므로 각각의 체크섬을 사용합니다.

## GitHub CI

[PR #2](https://github.com/sebia1993/aruba-client-live-tracker-/pull/2)와 [CI 40478748628](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40478748628)의 대상은 `258b964c8d6bbeb0a7e4da98fd9699989dc1f753`입니다. v0.3.7 태그도 이 검증 커밋에 직접 연결했습니다. 병합 커밋 `9829932f32a7bf8413ac4b0dc548418e7430cc08`과의 파일 트리 차이는 없습니다.

- Linux: 574개 통과·Windows 전용 1개 건너뛰기, 실패·오류 0.
- Windows: 575개 통과, 실패·오류·건너뛰기 0. Windows 빌드 재검사도 575개 통과.
- 독립적으로 내려받은 XML과 소스/EXE 단일·다중 JSON 6개를 확인했습니다. 모두 성공이며 버전·빌드 식별자와 1대 5회/10대 각 5회 관측이 일치했습니다.

로컬 증거는 `artifacts/ci-v037/`와 `artifacts/native-v037-verification.json`에 보관합니다. 게시된 태그나 바이너리를 덮어쓰지 않습니다.

병합 후 [main CI 40479490407](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40479490407)는 Linux 성공, Windows 574개 통과·1개 실패였습니다. 실패는 정상 프롬프트 판별 테스트의 전체 제한 0.5초가 임시 서버 키 파일 저장 중 소진된 `HOST_KEY_TIMEOUT`입니다. 같은 사례는 PR·릴리스에서 0.194~0.206초로 통과했습니다. 정확한 runner 지연 원인이 디스크인지 스케줄링인지는 확인할 수 없습니다.

키 파일 fsync에 0.6초 지연을 주입하자 해당 4개 사례 모두 같은 오류로 실패했고, 성공 판별 테스트의 제한만 5초로 조정한 뒤 4개 모두 통과했습니다. 시간 초과·취소 전용 테스트와 제품 코드는 변경하지 않았습니다. 재현 XML은 `artifacts/slow-trust-red.xml`, `artifacts/slow-trust-green.xml`입니다. 이 테스트 수정은 태그 이후 main에 반영하며, 배포 EXE의 소스 해시에는 영향이 없습니다.

수정 커밋 `e0f991f8f75ef596496cf872cf17a15e2649456b`의 [최종 main CI 40480753769](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40480753769)는 **성공**했습니다. Linux 574개 통과·Windows 전용 1개 제외(43.500초), Windows 575개 통과(82.989초), Windows 빌드 재검사 575개 통과(77.871초)이며 실패·오류는 없습니다. 수정한 프롬프트 4개 사례는 세 검사 모두 통과했습니다. 독립 검토자가 XML과 소스/EXE 실행 JSON 6개의 성공·관측 수·빌드 식별자를 확인했습니다. 중복 XML은 해시로 확인해 중복 집계하지 않았습니다. 증거는 `artifacts/ci-followup-v037/`에 보관합니다. 최종 문서 기록만 별도 커밋하며 제품 코드와 테스트는 이 CI 검증 상태를 유지합니다.

## 공개 릴리스 재검증

[v0.3.7 정식 릴리스](https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.7)는 2026-10-27 18:19:17 KST에 게시됐습니다. [릴리스 작업 40479499367](https://github.com/sebia1993/aruba-client-live-tracker-/actions/runs/40479499367)은 태그 커밋 `258b964`에서 성공했습니다. 독립적으로 받은 검증 XML은 **575개 통과, 실패·오류·건너뛰기 0, 86.169초**이며, 실제 EXE 단일·10대 관측 JSON의 성공·관측 수·버전·빌드 식별자가 일치했습니다.

공개 다운로드 URL에서 인증 없이 ZIP·체크섬 4개를 다시 받았습니다. 새 한글 경로에 풀어 Python을 제외한 PATH와 별도 한글 임시 폴더로 단일 5회·10대 5회를 실행해 **10회 모두 성공, 275개 관측, 미종료 세션 0개**를 확인했습니다. 공개 ZIP 751항목, SOURCE 231파일 해시와 Git 없는 재내보내기, 서드파티 소스 6개 해시, AMD64 GUI/asInvoker를 다시 확인했습니다. 빌드 식별자 `0.3.7-993a9d3669e0`와 제품 소스 해시는 로컬 빌드와 같습니다.

| 공개 파일 | 바이트 | SHA-256 |
|---|---:|---|
| ArubaClientLiveTracker_v0.3.7_windows_x64.zip | 43492007 | `b34582c09dceea74d8e38b72997c2387e258dc6dfd5736b9c3f0c1bd936875ec` |
| ArubaClientLiveTracker_v0.3.7_third_party_sources.zip | 72212226 | `1b07fe48cbe0ca3d1b8133127a3a4dd9298b9ba3d12bc6a93889f56751a5a2aa` |

공개 파일은 `artifacts/published-v0.3.7/`, 실행 결과는 `artifacts/published-package-v037.json`, 독립 릴리스 검증은 `artifacts/release-v037-validation/`에 보관합니다.

## 제한과 현장 확인

운영망 연결·실제 Aruba 장비 시험은 하지 않았습니다. 기존 설정과 서버 키를 보존하고 새 EXE의 도움말 버전·빌드 식별자를 확인한 뒤, 장비 찾기 → 필요한 장비 선택 검사 → 저장 → 재실행 → IP/MAC 추적을 현장에서 확인해야 합니다. **실장비 검증 대기**입니다. DNS 호출 자체를 즉시 중단하도록 구조를 바꾼 것은 아니므로 DNS 지연 시간 개선은 주장하지 않습니다.

[이전 v0.3.6 검증](validation/v0.3.6/BUILD_VALIDATION_KO.md)과 [이전 릴리스 노트](validation/v0.3.6/RELEASE_NOTES_KO.md)를 보존했습니다.
