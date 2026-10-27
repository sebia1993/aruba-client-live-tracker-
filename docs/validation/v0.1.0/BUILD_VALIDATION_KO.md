# v0.1.0 과거 검증 기록

이 파일은 v0.1.0 당시의 기록이며 v0.2.0 검증 결과가 아닙니다. 저장소 생성 권한 오류도 당시 상태입니다.

# 빌드와 검증 기록

검증일: 2026-10-27. 실제 Aruba 장비 접속은 수행하지 않았습니다.

## 확인된 결과

| 항목 | 실제 결과 |
|---|---|
| Linux CPython 자동 테스트 | **121 passed in 7.99s**, pytest 9.1.1 |
| Windows CPython 3.12.10 x64, Wine 10 | `pytest`: **121 passed in 12.57s** |
| 정적 검사 | `ruff check .`: 통과 |
| 공개 의존성 공지 | 고정된 **25개 패키지, 영향 패키지 0개** (PyPI version advisories, 2026-10-27) |
| Windows EXE 형식 | PyInstaller 6.16.0 Windows bootloader, PE32+ GUI, x86-64 |
| Frozen EXE 데모 | **통과**, Wine 10의 Qt Windows 플랫폼에서 GUI 생성·데모 5회·SQLite 저장·정상 종료, exit 0 |
| Qt 배율 스모크 | Linux Qt offscreen 125%·150% 각각 데모 5회·SQLite·종료 코드 0 (Windows 실기와 다름) |
| 타사 고지 | Windows 설치 메타데이터에서 라이선스와 버전 manifest 수집, LGPL 해당 소스 ZIP 별도 제공 |
| 실제 프로그램 이미지 | `docs/assets/demo-dashboard-full.png`, 가상 데이터로 실행한 실제 Qt 화면 |

의존성 공지 조회는 빌드 작업에서만 수행합니다. 실행 프로그램은 외부 분석 서비스나 API에 의존하지 않습니다. PyPI 공지 확인은 Qt/OpenSSL 등 모든 내장 네이티브 라이브러리의 완전한 보안 감사를 뜻하지 않습니다.

## 배포 파일

- `ArubaClientLiveTracker_v0.1.0_windows_x64.zip`: 실행 파일과 동적 DLL, 문서, 라이선스, 애플리케이션 재빌드 소스.
- `ArubaClientLiveTracker_v0.1.0_third_party_sources.zip`: 정확한 Qtbase/Qt imageformats/Qt SVG/Qt translations/PySide/Shiboken/Paramiko의 수정하지 않은 대응 소스.
- 각 ZIP의 `.sha256` 파일. 별도 애플리케이션 소스 번들도 작업 결과에 제공합니다.

실행 ZIP은 Windows용입니다. Linux 실행 파일에 `.exe` 확장자를 붙인 것이 아닙니다. 이 환경에서는 Wine으로 Windows용 CPython과 PyInstaller를 실행해 제작했습니다. 실제 Windows 11에서의 검증과 동일하지 않습니다. **코드 서명되지 않았습니다.**

## 수행하지 못한 항목

- GitHub 신규 공개 저장소 생성: **권한 오류** — `Resource not accessible by integration (createRepository)`.
- 원격 푸시, GitHub Actions 실행, GitHub Release 게시: **미수행**. 실제 성공 URL 없음.
- Windows 11 네이티브/일반 사용자 실행, 125%·150% 배율 실기 검증: **미검증**.
- 실제 ArubaOS 8.10/7240XM/AP-535 명령 지원, 계정 권한, MM 장애 전환 및 클러스터 로밍: **미검증**.
- 장시간 실장비 부하 및 24시간 누적 실행: **미검증**. 반복 자동 테스트는 가속된 오프라인 검증입니다.
- `build_windows.ps1` 전체를 네이티브 PowerShell에서 실행한 결과는 없습니다. 같은 Windows Python 테스트·PyInstaller·EXE 스모크 단계는 Wine에서 직접 실행했습니다.

## 수정한 빌드 문제

처음 검토한 Paramiko 3.5.1과 cryptography 46.0.3 및 일부 개발 의존성에서 공개 보안 공지를 확인하여 최종 고정 버전을 업데이트했습니다. setuptools 84에서 제거된 `pkg_resources`를 altgraph 0.17.4가 사용하여 빌드가 실패했으며, altgraph 0.17.5로 수정 후 재빌드에 성공했습니다. 실패를 무시하거나 테스트를 강제 성공 처리하지 않았습니다.

GitHub 게시를 완료하는 정확한 명령은 [설치 안내](../../INSTALL_KO.md#저장소와-릴리스-게시)에 있습니다. 기존 네 저장소는 수정하지 않았습니다.
