# Aruba Client Live Tracker — Windows 11 로컬 Codex 작업지시서

작성일: 2026-10-27. 다음 로컬 Codex 세션에 이 문서를 그대로 전달한다.

## 1. 목표와 작업 원칙

이제 Codex Cloud에서 개발하지 않고 사용자의 Windows 11 x64 PC에서 기존 프로젝트를 이어간다. 반복되는 장비 발견 오류를 재현·수정하고 전반적인 예방 점검을 마무리하여, 사용자가 실행할 Windows EXE와 ZIP을 완성한다. 계획서만 작성하고 멈추지 않는다.

- 저장소: https://github.com/sebia1993/aruba-client-live-tracker- **끝의 하이픈 포함**.
- 새 프로젝트를 만들지 말고 기존 코드·설정·이력·Git 변경을 보존한다. 강제 푸시, 기존 태그 덮어쓰기, 사용자 설정/서버 키 삭제는 하지 않는다.
- 일반적인 구현·수정·테스트·로컬 빌드는 추가 승인 없이 진행한다. GitHub 반영·릴리스는 기존 요청 범위이며 실제 제공된 인증·권한 안에서 수행한다.
- 실제 Aruba 접속과 운영 검증은 사용자가 앱에서 직접 수행한다. Codex가 운영망 주소·계정·비밀번호·전체 CLI 원문을 요구하거나 장비에 임의 접속하지 않는다. 로컬 개발 전환으로 이 조건이 바뀌지 않는다.
- 단일·다중 클라이언트 모니터링을 모두 유지한다. 현재 오류와 신뢰성 보완을 우선하며 무관한 기능 확대·프레임워크 교체는 하지 않는다.

## 2. 최신 오류와 환경

사용자는 `MM에서 장비 찾기` 및 선택 장비 검사 흐름에서 오류가 계속 발생한다고 보고했다.

```text
장비 발견 / SWITCH_TABLE_PARSE_FAILED
장비 목록을 해석하지 못했습니다.
장비 표의 IP 형식이 올바르지 않습니다.
출력 9행 · IP 열 길이 0 · IPv6 열 길이 0
```

이전에는 같은 위치에서 IP 열 길이 12, IPv6 열 길이 14도 보고됐다. 최신 0/0 보고 때 실제 실행한 EXE 버전·경로는 확정되지 않았다. 사용자가 앞서 v0.3.5를 아직 확인하지 않았다고 한 뒤 오류 재발을 보고했으므로, 이를 구버전 문제로 단정하거나 v0.3.5에서 해결됐다고 주장하지 않는다.

- MM: ArubaMM-HW-10K, Primary/Standby.
- WLC: Aruba7240XM 또는 Aruba7210. ArubaOS 역할은 MD.
- ArubaOS: 사용자가 명시한 **v8.10.0.10**을 우선 대조한다.
- 사용자가 확인한 `show switches` Type: MM은 conductor 또는 standby, WLC는 MD.
- **장비 식별 표 뒤에 Status / Configuration State로 시작하는 별도 상태 표가 있음**을 사용자가 확인했다.

0/0은 파서가 해당 행의 두 주소 셀을 빈 문자열로 추출했다는 진단이다. 실제 장비 IP가 잘못됐다는 증거가 아니다. 열 위치·표 전환·줄바꿈·페이지 안내·전송 제어 문자 처리를 조사하되 원인을 미리 확정하지 않는다.

v0.3.5에서는 공식 페이지 안내 `--More-- (q) quit (u) pageup (/) search (n) repeat`를 일부만 지워 12/14 길이의 가짜 주소 셀이 생기는 문제를 합성 SSH 시험으로 재현·수정했다. 이 과거 재현은 이번 0/0의 원인이나 실장비 해결을 입증하지 않는다.

## 3. 인계 시점의 실제 코드·검증 상태

2026-10-27 GitHub 조회 기준:

| 항목 | 상태 |
|---|---|
| 공개 main | `2beb4ed00b173319ea0cc712e30ead474663a952` |
| 최신 공개 버전 | v0.3.5 |
| v0.3.5 실행 코드 태그 커밋 | `1600484cd117ebff2853628f00a78e73152de151` |
| 공개 릴리스 | https://github.com/sebia1993/aruba-client-live-tracker-/releases/tag/v0.3.5 |
| 다음 후보 버전 | v0.3.6. 아직 버전 변경·태그·릴리스하지 않음 |

클라우드의 `fix/stability-audit`에는 미커밋 예방 점검 수정이 남아 있다. 수정 작업이 중단됐으며 통합 검토가 끝나지 않았다. main clone만으로 이 변경을 가져올 수 없다.

동봉한 `stability-audit-wip.patch`는 위 main 기준 **수정 19개 파일 + 새 테스트 2개 파일**을 포함한다. 운영 설정·DB·실장비 로그·가상환경은 포함하지 않는다. 완성본으로 취급하거나 바로 배포하지 않는다.

인계 직전 검사:

- 변경 전 공개 main: Linux 전체 **368개 통과**.
- 인계 작업본: Linux **466개 통과, 8개 실패**, 오류·건너뛰기 0, 36.50초.
- 실패 8개는 아직 대응 구현이 없는 `tests/test_packaging_recovery.py`에 모여 있다.
- Ruff 오류 2개: `tests/test_commands_parsers.py`의 E731, `tests/test_startup.py`의 I001.
- 이 패치의 Windows 검사·CI·EXE·릴리스, 최신 오류의 실제 장비 검증은 수행하지 않았다.
- 근거 파일: `evidence/pytest-handoff-source.xml`, `.txt`, `ruff-handoff.json`.

검사는 `PYTHONPATH=src`를 명시해 작업본을 실행했다. 클라우드 공유 가상환경의 editable 설치가 이전 main을 가리켜 이를 생략한 최초 실행에서는 자식 프로세스가 옛 코드를 읽었다. 그 최초 결과는 최종 인계 수치로 쓰지 않는다. 로컬은 체크아웃 전용 가상환경을 새로 만들고 실제 import 경로를 확인한다.

## 4. Windows에서 이어받는 방법

Git, Python 3.12 x64, PowerShell을 사용한다. 최종 EXE 사용자에게 Python 설치를 요구하지 않는다. 기존 clone이 있으면 새 clone이나 초기화를 강제하지 말고 현재 변경·브랜치·원격부터 확인한다.

새 폴더에서 시작하는 예시:

```powershell
git clone https://github.com/sebia1993/aruba-client-live-tracker-.git
Set-Location aruba-client-live-tracker-
git status --short
git log -5 --oneline
git fetch origin --tags
Get-Content AGENTS.md -Encoding utf8
```

최신 main과 인계 기준의 차이를 확인한다. 원격이 바뀌었다면 중복 수정·충돌을 검토한다. 패치는 저장소 밖에 압축 해제한다. 기준 재현은 깨끗한 checkout의 별도 브랜치에서 수행한다. 같은 이름의 브랜치가 있으면 새 이름을 사용한다.

```powershell
git switch -c fix/windows11-discovery-audit 2beb4ed00b173319ea0cc712e30ead474663a952
$handoffDir = 'C:\Users\YOUR_NAME\Downloads\aruba-local-handoff'
git apply --check "$handoffDir\stability-audit-wip.patch"
if ($LASTEXITCODE -ne 0) { throw '패치 기준 또는 충돌을 먼저 확인하세요.' }
git apply "$handoffDir\stability-audit-wip.patch"
if ($LASTEXITCODE -ne 0) { throw '패치 적용 실패' }
git status --short
git diff --stat
```

충돌 시 `reset --hard`로 밀어붙이지 않는다. 기준 커밋의 별도 worktree에서 검토하고 필요한 변경을 최신 main에 통합한다. 인계 ZIP이 없으면 공개 main에서 시작하되 미완료 항목을 직접 재현한다. 클라우드의 `/workspace/...` 경로는 Windows에서 사용할 수 없다.

```powershell
py -3.12 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
& .\.venv\Scripts\python.exe -m pip install --no-deps -e .
& .\.venv\Scripts\python.exe -c "import sys,struct,aruba_client_live_tracker as a; print(sys.executable, struct.calcsize('P')*8, a.__file__)"
$env:PYTHONPATH = Join-Path (Get-Location).Path 'src'
$env:QT_QPA_PLATFORM = 'offscreen'
& .\.venv\Scripts\python.exe -m pytest -q --junitxml=artifacts/pytest-windows-baseline.xml
& .\.venv\Scripts\python.exe -m ruff check src tests scripts
```

각 외부 명령의 `$LASTEXITCODE`를 확인한다. 테스트 실패를 뒤 명령의 성공으로 숨기지 않는다. 사람이 GUI를 확인할 때는 offscreen을 제거한다.

```powershell
Remove-Item Env:QT_QPA_PLATFORM -ErrorAction SilentlyContinue
& .\.venv\Scripts\python.exe -m aruba_client_live_tracker.main --demo
# 단일 모드를 종료한 다음 다중 모드를 확인한다.
& .\.venv\Scripts\python.exe -m aruba_client_live_tracker.main --multi-demo
```

## 5. Aruba 공식 문서를 항상 먼저 확인

사용자가 별도로 말하지 않아도 명령어·출력 형식 변경 전에 HPE Aruba Networking 공식 문서를 직접 확인한다. 이 상시 선호는 저장소 `AGENTS.md`에 이미 기록되어 있으므로 유지한다.

- [8.10 CLI Reference PDF](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8.x-CLI-Reference-Guide.pdf)
- [8.10 User Guide](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8%2E10%2E0%2E0-User-Guide.pdf)
- [ArubaOS v8.10.0.10 Release Notes](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/Release-Notes/810/ArubaOS-8%2E10%2E0%2E10-Release-Notes.pdf)
- [show switches](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm)
- [show switchinfo](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switchinfo.htm)
- [show version](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-version.htm)
- [paging](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/paging.htm)

인계 작성일에 `show switches`와 `paging`도 다시 열어 확인했다. 문서에는 관리 장비/MM 목록, 분리 상태 표 예시, 기본 활성화된 세션별 paging이 설명되어 있다. 특정 예시의 명령 변형을 자동 실행하라는 뜻은 아니다.

URL·확인일·페이지/절·실행 위치·인자·필드·권한·미확인 범위를 `docs/CLI_COMMANDS_KO.md`에 기록한다. HTML 공백 손실이나 PDF 출판 줄바꿈을 실제 SSH 바이트로 취급하지 않는다. 다른 버전/제품의 예시나 모델명만으로 역할을 확정하지 않는다. 공식 예시와 합성 테스트, 실제 장비 검증을 명확히 구분한다.

## 6. 최우선: 반복되는 장비 발견 오류

### 실행 버전과 실제 수집 경로

도움말/진단에서 앱 버전·빌드 식별자·실행 경로·수집/파서 버전을 확인할 수 있게 한다. 운영 주소·계정은 넣지 않는다. 오래된 바로가기·다른 EXE 실행을 식별하되 현재 원인으로 가정하지 않는다.

실제 호출 흐름을 추적한다.

`장비 찾기/선택 검사 → discovery → SSH 수신/페이지 처리 → 정규화 → parse_switches → 주소 검증 → 후보 병합/설정 저장`

우선 코드: `src/aruba_client_live_tracker/discovery_parsers.py`의 `_switch_layout`, `_switch_cells`, `_switch_address`, `parse_switches`; `ssh.py`; `discovery.py`; `ui_discovery.py`.

현재 `_switch_address`는 추출된 IPv4 문자열이 비어 있으면 주소 검증에 실패한다. **왜 빈 셀이 여기까지 도달했는지** 앞 단계부터 확인한다.

### 개인정보 없는 구조 진단

9행/0/0만으로 추측하지 말고 다음 구조 정보만 남겨 원인 단계를 구분한다.

- 수집·정규화·파싱 단계, 단계별 행 수, 실패 행 번호의 기준.
- 표 종류, 공식 열 이름과 시작/끝 위치, 실패 행 길이·선행 공백 길이.
- 셀 존재 여부·길이·유효성, 값 없는 문자 유형/공백 구간 요약.
- 페이지 안내·CR/LF·ANSI·백스페이스 처리 횟수, 프롬프트/완료 표식 검출 여부.
- 선언된 장비 수, 식별/상태 행 수, 정상 종료/시간 초과.

열 배치 오류·미완료 출력·알 수 없는 행·실제 주소 검증 실패를 서로 다른 진단으로 안내한다. 실패 시 기존 설정을 보존한다.

원문 저장이 필요하면 사용자 선택으로 로컬 파일에만 저장한다. 자동 저장/업로드는 금지한다. 원문을 Codex 컨텍스트·도구 출력·GitHub로 보내지 않는다. 필요한 경우 로컬 코드가 원문을 처리해 값 없는 구조 통계만 출력하게 한다. 사용자에게 전체 CLI 원문이나 운영 IP를 다시 요청하지 않는다.

### 실패 재현 → 수정

공식 형식의 가상 표로 다음을 시험한다.

- 단일 표·식별/상태 분리 표, IPv4/IPv6, 문서의 `None` 표기.
- 주소 열보다 짧은 행, 앞쪽 셀이 비고 뒤쪽만 있는 행, 열 위치 차이. 특히 9행·0/0.
- 페이지 경계의 반복 머리글, 구분선·상태 표·완료 표식·프롬프트 오인.
- 전체/짧은 페이지 안내, TCP 분할, CR/LF·백스페이스·ANSI, 다음 데이터 행의 들여쓰기 보존.
- 터미널 폭·줄바꿈 차이. 문서상 지원 형식과 합성 장애 입력을 구분한다.
- 정상 장비 누락 방지, 잘못된 주소·잘린 출력·중복·건수 불일치의 계속 차단.

파서 단위 검사뿐 아니라 루프백 SSH → 발견 서비스 → 후보 표시/선택 검사 통합 검사를 만든다. 합성 입력을 실장비 캡처라고 부르지 않는다.

표 상태·경계를 명시적으로 구분하고 근거가 있는 차이만 지원한다. 첫 IP를 아무 행에서나 정규식으로 찾거나 모든 행을 단순 공백 분할하지 않는다. 들여쓰기를 무조건 제거하지 않는다. IP가 없는 행을 전부 버리거나 주소·건수 검사를 제거해서 성공시키지 않는다. 명확한 제목·구분선·공식 페이지 안내만 구조적으로 처리한다.

불완전한 결과로 기존 장비를 삭제/덮어쓰거나 새 장비를 자동 활성화하지 않는다. 검증된 조회 전용 명령 allowlist를 유지한다. 임의 명령 변형, 전체 MD 스캔, 설정 모드 진입, paging 설정 변경을 해결책으로 추가하지 않는다.

## 7. 예방 점검 미완료 패치 검토·완성

다음은 작업본의 의도이지 최종 보증이 아니다. 직접 검토하고 Windows에서도 재검증한다. 발견 오류 수정과 다른 보완은 논리적인 커밋으로 분리한다.

| 영역 | 작업본 변경 의도 |
|---|---|
| 발견·매핑 | 자동 hostname 별칭 갱신, IPv6 정규화 충돌 검사, 빈 식별 응답의 허위 관측 시각 방지, 선언된 상태 열 검증 |
| 클라이언트 파서 | 잘못된 association/Flags의 거짓 해제 방지, detail 레코드 혼합 차단, 표 뒤 완료 표식 요구 |
| 수집 | 같은 MAC의 MM 위치 충돌을 `MM_LOCATION_AMBIGUOUS`로 유지, 부분 counter 집합 혼합 방지 |
| 모니터링 | 중복으로 멈춘 대상의 MAC 소유권 점유 방지, 캐시 이력의 거짓 실패/복구 이벤트 방지 |
| SSH·풀 | 인증 취소/시간 초과 분류, 공식 프롬프트 기호 변화, transport 종료·풀 잠금/예외 안전성 |
| 설정 | mappings JSON 배열 검사, 읽을 수 없는 기존 설정의 저장 전 백업 |
| 시작·스모크 | 데이터 폴더/DB 오류 한국어 안내, 결과/스크린샷 저장 실패 시 종료 |

아직 끝나지 않은 항목:

1. **소스 다운로드 복구:** `scripts/bundle_sources.py`를 임시 파일 다운로드 → 고정 SHA-256 검증 → 원자적 캐시 반영으로 바꾼다. 손상 캐시는 재다운로드하고 중단/검증 실패 바이트는 정상 캐시로 남기지 않는다. 해시 검사를 제거하지 않는다. 현재 신규 테스트 3개 실패.
2. **안전한 SOURCE 내보내기:** `scripts/export_sources.py`는 아직 없다. Git에서는 공개 허용 경로의 추적 파일만 내보내고 설정·DB·로그·키·경로 탈출/심볼릭 링크 우회를 제외한다. 새 SOURCE에는 `source-manifest.json`을 기록해 `.git` 없는 재빌드도 지원한다. 현재 관련 테스트 5개 실패. 구버전 SOURCE는 기존 빌드 방식이 유지되며 새 exporter에서 manifest 없는 입력은 안전한 제한 경로나 명확한 오류로 처리한다. 무제한 재귀 복사를 대체 경로로 쓰지 않는다.
3. `build_windows.ps1`의 재귀 SOURCE 복사를 exporter로 교체한다. 새 파일의 Git 추적 여부를 확인한다. ZIP 내용까지 검사하고 .gitignore만 믿지 않는다.
4. CI 소스 단일/다중 GUI 스모크에 각각 `timeout-minutes: 2`를 지정하고, 로컬 자식 프로세스도 시간 제한·정리를 적용한다.
5. `THIRD_PARTY_NOTICES.md`의 v0.3.0 하드코딩을 고친다. 실행 ZIP과 대응 LGPL 소스를 함께 배포한다.
6. `save_devices(path, devices) -> Path | None`의 백업 반환값을 설정 GUI에 연결해 한국어로 안내한다. `settings.json.recovery-*.bak`를 Git·배포에서 제외한다. 백업 실패 시 원본을 보존한다.
7. **자동 발견 장비의 관리 endpoint 편집 시 과거 IP/hostname 별칭이 남는 GUI 경로**를 고친다. 매핑을 편집하지 않았다면 이전 식별 정보에서 자동 생성한 별칭만 제거하고 사용자 추가 별칭은 유지한다. 수동 등록·명시적 매핑 편집은 보존한다. 재검사 후 새 식별 정보로 필요한 매핑을 구성한다.
8. Ruff 2건 수정. 실패 테스트 삭제·skip·강제 성공으로 해결하지 않는다.

추가 조사할 항목: SQLite 쓰기 잠금의 GUI 지연, 종료 DB 기록 실패 복구, 손상된 이력 JSON/DB의 화면 안내, 보고서 쓰기 실패 시 기존 파일 보존. 아직 수정 완료가 아니다. 실패를 재현한 항목부터 고치고 필요성 없이 저장 구조 전체를 바꾸지 않는다.

## 8. 유지할 사용자 선택과 제품 동작

- 한국어 다크 GUI, IP/MAC 정규화·모호한 결과 선택, MM Primary/Standby → 등록 매핑의 담당 MD 추적 유지.
- 장비명/IP 입력 후 자동 식별 유지. 역할은 conductor/standby/MD 등 근거로 판단하고 WLC(MD)를 명확히 안내한다. 판단 불가이면 미확인 상태와 수동 지정 경로 제공.
- **최초 연결에도 질문하지 않는 자동 TOFU**가 사용자의 최신 선택이다. 최초 키는 로컬 저장하고 재접속 시 검증한다. 변경 키·저장 실패는 차단한다. 키 검증 자체를 끄거나 변경 키를 자동 승인하지 않는다.
- 계정·비밀번호는 실행 중 입력하며 파일/로그 저장 금지. 텔레메트리·자동 업로드 금지.
- 단일/다중 시작·중지·일시 정지·새로고침·주기 변경·대상 전환 유지. 기본 15초, 10/15/30/60초 선택. 10대 데모와 기존 동시 수집/연결 상한 검증.
- SSH/파싱 실패를 연결 해제·로밍으로 기록하지 않는다. 마지막 유효 값·시각과 이전 값 표시를 유지한다. 캐시 이력을 신규 사건으로 만들지 않는다.
- RSSI/SNR·PHY Rate·Throughput·과거 ClientMatch 신호를 구분한다. 카운터 초기화·AP 전환·수집 누락에서 계산 불가 재전송률을 만들지 않는다.
- 클러스터의 사용자 소유 MD와 AP 담당 MD가 다를 수 있다. Current switch가 모든 AP 정보를 반드시 갖는다고 가정하거나 다른 MD를 전수 조회하지 않는다. 부분 조회·미지원 상태 표시.
- 공개 fixture는 RFC 5737 IPv4, 문서용 IPv6와 가상 MAC만 사용한다. 설정·원문·보고서·운영 화면은 공개하지 않는다. 보안 검사 오탐은 정확한 문맥만 보완하며 검사 전체를 완화하지 않는다.

## 9. 검증과 실제 Windows EXE

실패 재현 → 수정 → 관련 회귀 → 전체 테스트 → 정적/보안 검사 → 소스 GUI → Windows EXE 순으로 검증한다. 소스 스모크는 EXE 검증을 대신하지 않는다.

필수 검증:

- 9행·0/0 및 이전 12/14, 정상 단일/분리 표, IPv4/IPv6, 잘림·중복·건수 불일치.
- 장비 찾기 → 선택 검사 → 저장 → 앱 재시작 → IP/MAC 검색 → 담당 MD 추적. 실패 시 기존 설정/매핑 보존.
- MM/Standby·MD 오류/변경, 잘못된 인증·취소·시간 초과, 서버 키 자동 등록·변경 차단.
- 단일/10대 데모 각 5회 이상과 대상별 SQLite, 시작/중지/재시작·중복 MAC, 1,000회 반복 자원 상한.
- 실제 해제/재연결과 수집 실패 구분, AP/Role/VLAN·SNR/속도·카운터·캐시 이력.
- 설정 손상/백업 실패·DB 오류·보고서 쓰기 실패·스모크 저장 실패·소스 캐시 중단 복구.
- Windows 11 일반 사용자, 한글/공백 경로, 콘솔 없는 GUI, 1366×768 및 실제 125%/150% 배율, 종료/재실행. 환경 변수 모의 검사를 실제 디스플레이 확인으로 보고하지 않는다.

테스트 데이터 폴더는 실제 사용자 데이터와 분리한다. README에는 데모 화면만 사용한다.

빌드 스크립트의 `python`이 가상환경 Python인지 확인한다. 실행 정책을 시스템 전체에 영구 완화하지 않는다. 검증 후 미사용 버전을 선택한다. v0.3.6이 여전히 미사용이면 사용하고 pyproject·패키지·빌드 기본값·문서·소스 ZIP 버전을 일치시킨다.

```powershell
$env:PATH = "$(Join-Path (Get-Location).Path '.venv\Scripts');$env:PATH"
python -c "import sys; print(sys.executable)"
# 버전 파일을 일치시킨 다음 실행한다.
.\build_windows.ps1 -Version 0.3.6 -SkipInstall
```

최종 산출물은 `ArubaClientLiveTracker.exe`를 포함한 onedir ZIP, SHA-256, 대응 서드파티 소스 ZIP/고지, 한국어 가이드다. dist ZIP을 새 폴더에 전체 압축 해제해 EXE를 실행한다. 서명하지 않았으면 미서명이라고 표시한다. GitHub 기본 소스 ZIP을 실행 파일로 안내하지 않는다.

GitHub 권한이 있으면 검토·커밋·반영 후 Linux/Windows CI와 정확한 커밋 SHA를 확인하고 같은 코드에 새 태그를 만든다. 현재 CI는 main push/PR/workflow_dispatch이므로 작업 브랜치 push만으로 검사됐다고 가정하지 않는다. Release 성공 후 공개 ZIP을 재다운로드해 체크섬·구성·실행을 확인한다. 권한이 없으면 로컬 ZIP을 완성하고 푸시/태그 절차를 남긴다.

## 10. 완료 판정과 보고

다음 네 가지를 분리해 보고한다.

1. 공식/합성 형식 기반 오류 재현과 회귀 수정.
2. Windows 11 로컬 테스트·GUI·실제 EXE 성공.
3. GitHub CI·배포 파일 검증.
4. 사용자의 실제 Aruba 장비에서 발견·선택 검사·추적 성공.

4번이 아직이면 **실장비 검증 대기**다. 자동 테스트만으로 사용자 장애가 해결됐다고 하지 않는다. 원인을 아직 특정하지 못했다면 확인된 수정·남은 진단·시험 가능한 로컬 빌드를 구분한다.

최종 보고에 원인/근거, 변경·미완료 범위, 실제 테스트 통과/실패 수, Windows 실행 결과, 커밋/CI URL, 로컬 ZIP 경로·SHA-256, 실제 게시된 다운로드 URL과 운영 검증 항목을 남긴다. 재발이 절대 없다고 보장하지 않는다.

첫 작업은 최신 원격·로컬 변경·인계 패치를 확인하고 **반복 오류의 수신→정규화→표 파싱 경로부터 조사**하는 것이다. 운영 자료를 재요청하거나 일반적인 승인 질문을 반복하지 말고 진행 가능한 구현·검증을 끝까지 수행한다.
