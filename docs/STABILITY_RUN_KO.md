# 안정성 검증 실행

운영 데이터가 없는 새 폴더와 합성 대상만 사용합니다. 실제 장비에는 접속하지 않으며 Windows 전원·보안 설정을 바꾸지 않습니다.

## 자동 회귀와 대용량 비교

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe scripts\benchmark_history.py --help
```

대용량 벤치마크는 전용 DB·CSV·HTML을 생성하므로 충분한 디스크 공간이 있는 별도 검증 폴더에서 실행합니다. 이전/이후 결과의 시간·메모리·GUI heartbeat·동시 저장 지연과 보고서 SHA-256을 비교합니다.

## Windows EXE 연속 검증

전체 배포 ZIP을 새 경로에 푼 뒤 다음 기록기로 실행합니다. Python은 외부 기록기에 사용하며, EXE 자식의 Python 환경 변수와 PATH는 분리합니다.

```powershell
.\.venv\Scripts\python.exe scripts\run_windows_soak.py `
  --exe 'D:\검증\ArubaClientLiveTracker\ArubaClientLiveTracker.exe' `
  --directory 'D:\검증\새 8시간 결과 폴더' --seconds 28800
```

EXE는 정상 데모 10대를 10초 주기로 수집합니다. `--directory`는 기존 폴더를 거부하며, 실행 파일 해시·빌드 식별자·PID·시작/종료 시각·자원 JSONL·진행 JSON·최종 JSON을 이 폴더에 저장합니다. 외부 전송은 없습니다. 직접 실행할 때는 `--multi-demo --soak-seconds 28800 --data-dir <새 폴더> --smoke-result <새 JSON>` 조합을 사용합니다.

`--seconds 60 --sample-interval 1`은 준비 확인용 짧은 리허설입니다. `--headless`는 offscreen 리허설이며 8시간 native GUI 성공으로 인정하지 않습니다.

판정은 종료 코드와 실제 경과 시간, 대상별 저장량·저장 시각 간격, DB 무결성·미종료 세션, 1초 GUI heartbeat 및 수집 진행을 함께 확인합니다. GUI heartbeat가 15초 넘게 멈추거나 대상 수집·저장 공백이 30초를 넘으면 실패합니다. 절전/재시작으로 끊긴 실행을 8시간 통과로 계산하지 않습니다.

자원은 10초마다 기록합니다. 준비 구간(전체 20%, 최대 10분) 이후와 종료 구간 중앙값을 비교하며 private memory가 64MiB와 25%를 모두 초과해 증가하거나 핸들 +50·스레드 +4를 넘으면 실패로 분류합니다. 이 기준은 누수 선별 기준이며 누수 부재의 수학적 증명은 아닙니다. DB 파일 크기는 기록 누적으로 증가할 수 있습니다. 시험 프로세스가 진행 보고를 60초 넘게 갱신하지 않으면 기록기는 자신이 시작한 정확한 자식만 종료하고 실패를 남깁니다.

이 연속 검증은 GUI·데모·SQLite·Windows 자원을 확인합니다. 실제 SSH는 별도의 루프백 장애 시험으로 검증하며 실제 Aruba·운영망·물리 전원 장애·OS DNS 종료 시간은 별도 경계입니다.
