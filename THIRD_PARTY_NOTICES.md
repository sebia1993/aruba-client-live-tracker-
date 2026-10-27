# 타사 소프트웨어 고지

Aruba Client Live Tracker의 자체 코드는 MIT License입니다. 제품명 Aruba 및 HPE는 각 권리자의 상표이며 이 프로젝트는 HPE의 공식 제품이 아닙니다. 실제 장비와의 호환성을 보증하지 않습니다.

## Qt / PySide6 / Shiboken

- PySide6 Essentials 및 Shiboken 6.8.3: Copyright (C) The Qt Company Ltd. 및 기여자. LGPL v3 옵션으로 사용합니다. Qt 6.8.3 Core/Gui/Widgets와 기본 플랫폼 플러그인을 동적 라이브러리로 포함합니다.
- `LICENSES`에 LGPL-3.0-only, GPL-3.0-only, Qt GPL exception 및 관련 고지 전문을 포함합니다. LGPL은 GPL 본문을 참조하므로 두 문서를 함께 제공합니다.
- LGPL 적용 라이브러리를 수정하지 않았습니다. `onedir` 배포의 `_internal` 아래 Qt/PySide DLL 및 Python 확장 모듈을 호환 가능한 수정 버전으로 교체할 수 있습니다. 라이브러리 수정 및 그 수정 사항 디버깅에 필요한 역공학을 제한하지 않습니다. 재결합을 위한 애플리케이션 소스와 PyInstaller 빌드 명령을 제공합니다.
- Qt 소스 6.8.3: https://download.qt.io/archive/qt/6.8/6.8.3/single/qt-everywhere-src-6.8.3.tar.xz
- PySide/Shiboken 소스 6.8.3: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/pyside-setup-everywhere-src-6.8.3.tar.xz
- 소스 저장소 태그: https://code.qt.io/cgit/pyside/pyside-setup.git/tag/?h=v6.8.3
- Qt 내장 제3자 코드(FreeType, HarfBuzz, libpng, zlib, PCRE2, Unicode 등) 고지는 동봉 `LICENSES/Qt-third-party`와 Qt 공식 문서 https://doc.qt.io/qt-6/licenses-used-in-qt.html 에서 확인합니다.

같은 배포에 `ArubaClientLiveTracker_v0.2.0_third_party_sources.zip`을 제공합니다. 정확한 Qtbase, Qt imageformats/SVG/translations, PySide/Shiboken, Paramiko 소스와 SHA-256을 포함합니다. 실행 ZIP의 `SOURCE`에는 애플리케이션 코드와 재빌드 스크립트가 있습니다. 이 소스 ZIP을 실행 ZIP과 함께 보관·재배포하십시오.

Microsoft Visual C++ Runtime DLL은 CPython/Qt 바이너리의 실행 의존성으로 포함될 수 있습니다. Microsoft Visual Studio 재배포 조건이 적용되며 고지 원문은 `LICENSES/upstream/Microsoft-Visual-Cpp-Runtime.txt`에 포함합니다.

## Python 및 SSH/암호화

실제 ZIP의 `LICENSES/manifest.json`이 포함 버전과 고지 파일을 기록합니다.

| 구성 요소 | 라이선스 | 소스 |
|---|---|---|
| CPython 3.12 | PSF License | https://www.python.org/downloads/source/ |
| Paramiko 5.0.0 | LGPL 2.1 | https://github.com/paramiko/paramiko/tree/5.0.0 |
| cryptography 50.0.0 | Apache 2.0 / BSD | https://github.com/pyca/cryptography/tree/50.0.0 |
| bcrypt 5.0.0 | Apache 2.0 | https://github.com/pyca/bcrypt/tree/5.0.0 |
| PyNaCl 1.6.2 / libsodium | Apache 2.0 / ISC | https://github.com/pyca/pynacl/tree/1.6.2 |
| cffi 2.0.0 / pycparser 2.23 | MIT / BSD | https://github.com/python-cffi/cffi / https://github.com/eliben/pycparser |
| Invoke 3.0.3 | BSD | https://github.com/pyinvoke/invoke |
| platformdirs 4.3.7 | MIT | https://github.com/tox-dev/platformdirs/tree/4.3.7 |
| OpenSSL (cryptography wheel 내부) | Apache 2.0 | https://github.com/openssl/openssl |
| PyInstaller 6.16.0 bootloader | GPL 2.0 + bootloader exception | https://github.com/pyinstaller/pyinstaller/tree/v6.16.0 |

Paramiko 모듈은 동봉 소스/업스트림 소스와 빌드 스크립트로 수정·재빌드할 수 있습니다. PyInstaller 예외는 생성된 실행 파일에 별도 라이선스를 적용하는 것을 허용합니다. 타사 라이선스의 저작권 고지 및 조건은 이 프로젝트 MIT와 별개로 계속 적용됩니다.

## 기존 프로젝트 검토

sebia1993의 Aruba Session Tracker, Aruba Cluster Health Dashboard, Aruba Wireless Policy Mapper, Multi Target Ping Monitor는 MIT입니다. 검토 커밋과 재사용 범위는 `docs/REFERENCE_REVIEW_KO.md`에 기록합니다. 직접 가져온 코드가 있으면 해당 파일에 원 저작권을 유지합니다. 기존 저장소의 런타임 파일에 의존하지 않습니다.
