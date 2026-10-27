# v0.3.3 빌드와 검증 기록

기록일: 2026-10-27. MM의 장비 찾기에서 `SWITCH_TABLE_PARSE_FAILED`가 발생한 사용자 보고를 조사했습니다. 사용자는 장비 정보 뒤에 별도 `Status / Configuration State` 표가 표시됨을 확인했습니다. 실제 주소·장비 원문·계정은 수집하지 않았습니다.

## 원인과 수정 범위

v0.3.2의 파서는 장비 목록을 단일 표로 가정하여 두 번째 표의 머리글을 IP 행으로 해석했습니다. 합성 출력과 실제 TCP loopback SSH 서버에서 같은 오류를 재현했습니다. HPE 공식 문서에도 identity 표 뒤에 Status/Configuration State/Config Sync Time(sec)/Config ID 표가 있는 형식이 기재돼 있습니다.

첫 장비 표와 문서에 근거한 후속 표를 각각 파싱하고, 두 표 모두 `Total Switches`와 행 수가 일치해야 목록을 채택하도록 수정합니다. 잘린 표·추가 행·알 수 없는 머리글·중복 IP·잘못된 완료 건수는 계속 거부합니다. 역할은 첫 표의 명시적인 Type에 근거합니다. 기존 단일 표와 정상 0건 표도 회귀 검사합니다. 조회 명령은 기존 `show switches` 그대로이며 새로운 명령 변형이나 전체 MD 탐색은 추가하지 않습니다.

형식 오류에는 고정된 한국어 세부 사유를 표시하며 CLI 원문·셀 값은 포함하지 않습니다. 기존 단일 표, 최초 키 자동 저장과 변경 키 차단, 단일/10대 추적을 유지합니다.

## 검증 상태

로컬 전체 329개 테스트(22.66초), 실제 TCP loopback SSH의 단일/분리 표 발견 및 선택 WLC 검사, 독립 코드 리뷰를 통과했습니다. Windows CI·EXE·Release·공개 다운로드 결과는 수행 후 기록합니다. v0.3.2의 결과는 이 버전의 검증으로 대체하지 않습니다.

## 공식 근거와 한계

- [HPE show switches](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm): 여러 표로 나눈 출력 예시. 해당 문서의 필터/debug 변형을 앱에서 실행한다는 뜻이 아닙니다.
- [ArubaOS 8.10 CLI Reference PDF](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8.x-CLI-Reference-Guide.pdf): 물리 3385쪽 `show switches state complete`의 동일한 분리 표 구조.
- [이전 v0.3.2 완료 기록](validation/v0.3.2/BUILD_VALIDATION_KO.md)

검증 데이터는 합성 자료이며 실제 Aruba 장비에 접속하지 않았습니다. 최종 실장비 발견·추적과 Windows 11 실기/고배율은 사용자 검증 대상입니다. 실행 파일은 코드 서명되지 않았습니다.
