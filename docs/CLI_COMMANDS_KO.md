# ArubaOS CLI 수집 근거와 검증 범위

검토일: 2026-10-27. **공식 문서의 명령 존재 확인과 실제 장비 동작 확인은 다르다.** 이 프로젝트 개발 환경에서는 Aruba 장비에 접속하지 않았다. 아래 명령의 구문·출력 의미는 HPE Aruba Networking 공식 문서를 조사했으며, ArubaOS 8.10 패치별 권한·출력·부하와 클러스터 실행 위치는 사용자의 테스트 환경에서 확인해야 한다.

## 근거 문서

- [ArubaOS 8.10 계열 CLI Reference Guide PDF](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8.x-CLI-Reference-Guide.pdf): 다운로드하여 해당 절을 직접 확인했다. 아래 PDF 페이지는 파일의 물리 페이지 번호다.
- [HPE 공식 Wi-Fi 보안 문제 해결 — AOS 8](https://arubanetworking.hpe.com/techdocs/aos/wifi-design-deploy/security/modes/troubleshooting/): `show ap association`, `show auth-tracebuf mac`의 MD 실행 예를 확인했다.
- [기존 프로젝트 검토](REFERENCE_REVIEW_KO.md): MM의 `Current switch` 파싱, SSH 키 검증, 정상 결과와 조회 실패 분리의 코드 근거다. 기존 프로젝트가 지원하는 세션 명령을 이번 제품에서 무조건 실행하지 않는다.

## 명령과 실행 위치

예시 IP는 RFC 5737, 예시 MAC/AP 이름은 가상 값이다. 실제 명령은 입력 검증 및 허용 목록을 통과해야 한다. 문서에 존재하더라도 수집 코드에 등록하지 않은 명령은 실행하지 않는다.

| 목적 | 검토한 명령 | 수집 대상 / 공식 근거 | 필터·권한·부하 및 제한 |
|---|---|---|---|
| MM 장비 목록 발견 | `show switches` | 입력한 MM. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm) | MM 자체를 포함한 관리 장비 목록. 현재 버전은 고정 명령만 사용하며 토폴로지 자동 반복 탐색을 하지 않는다. `Type` 등 역할 근거와 관리 주소를 검토한다. |
| 선택 장비 모델·버전 확인 | `show version` | 사용자가 선택한 주소. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-version.htm) | 모델과 OS 버전 근거이며 모델명만으로 Primary/Standby/MD를 확정하지 않는다. |
| 선택 장비 자기 식별 | `show switchinfo` | 사용자가 선택한 주소. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switchinfo.htm) | hostname·switch IP·역할 등 확인 가능한 필드만 사용한다. 자기 행을 확정할 수 없거나 역할 근거가 모호하면 AUTO로 남긴다. |
| IP로 단말 식별 | `show global-user-table list ip "192.0.2.100"` | MM. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-glb-usr-tab.htm), PDF 2578–2579 | IP 필터. Enable 권한 필요. `Current switch`를 등록 MD 매핑과 대조한다. 여러 MAC이면 사용자 선택이 필요하다. |
| MAC으로 현재 IP 식별 | `show global-user-table list mac-addr aa:bb:cc:dd:ee:ff` | MM. 위 global-user-table 문서 | MAC 필터. 출력의 IP·Role·Auth·AP 등의 값은 해당 시점 MM 관측이다. 필터 없는 `list`로 자동 대체하지 않는다. |
| 사용자 접속·인증 정보 | `show user-table mac aa:bb:cc:dd:ee:ff` | 담당 MD. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-user-tab.htm), PDF 3499–3505 | MAC 필터. 문서는 MM 및 MD의 Enable/Config 모드를 기재한다. 앱은 설정 모드로 진입하지 않는다. 인증 방식과 인증 성공 여부는 별도 항목이다. |
| AP 연결 상태 | `show ap association client-mac aa:bb:cc:dd:ee:ff` | 담당 MD. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-assoc.htm), PDF 1634–1637 및 위 AOS 8 문제 해결 문서 | MAC 필터. 과거 연결 행이 남을 수 있다. `A`(활성) 플래그와 `assoc` 상태를 확인해야 한다. 단순히 MAC 행이 존재한다는 이유로 현재 연결로 판정하지 않는다. |
| 클라이언트 패킷·SNR | `show ap debug client-stats client-mac aa:bb:cc:dd:ee:ff advanced` | 담당 MD에서 제한적으로 시도. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-dbg-clt-st.htm), PDF 1793–1798 | MAC 필터. `advanced`가 추가 통계를 반환한다. AP 관련 조회이므로 응답 지연·권한·출력량 확인 필요. 무필터 대체 금지. |
| 마지막 링크 속도·SNR | `show ap debug client-table ap-name DEMO-AP-01` | 현재 AP를 담당하는 MD. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-dbg-clt-tab.htm), PDF 1799–1803 | AP 단위 필터이며 단말 하나만 반환하지 않는다. 결과에서 대상 MAC만 선택한다. AP 이름을 모르면 실행하지 않는다. `bssid`는 문서상 해당 BSSID 행을 위에 표시할 수 있어 엄격한 단말 필터로 간주하면 안 된다. |
| AP 이동·해제 기록 | `show ap client trail-info aa:bb:cc:dd:ee:ff` | 담당 MD의 선택적 진단. [명령 문서](https://arubanetworking.hpe.com/techdocs/ArubaOS/oxygen/AOS-8%20Command%20Line%20Interface%20Guide/GUID-F6390631-991C-47EB-881E-B1EF083EF1DF.html), PDF 1670–1672 | MAC 인자는 선택 사항이지만 앱에서는 필수다. 제한된 과거 버퍼이며 현재 접속 근거가 아니다. |
| ClientMatch 이동 이력 | `show ap arm client-match history client-mac aa:bb:cc:dd:ee:ff` | 담당 MD의 선택적 진단. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-arm-cm-his.htm), PDF 1568–1571 | MAC 필터. ClientMatch가 기록한 이동만 포함하며 모든 로밍을 포함하지 않는다. 과거 Signal 값은 현재 RSSI가 아니다. |
| 인증 이벤트 원문 | `show auth-tracebuf mac aa:bb:cc:dd:ee:ff` | 담당 MD의 선택적 진단. [명령 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-auth-tracebuf.htm), PDF 2364–2366 및 위 AOS 8 문제 해결 문서 | MAC 필터. 인증 교환·실패 사유가 실제 기록된 경우에만 사실로 제시한다. 기록 없음은 인증 성공이나 실패를 증명하지 않는다. 설정으로 debug를 켜지 않는다. |

### 발견 명령의 역할 판별 한계

2026-10-27 위 세 CLI Bank URL에 HTTP 200 응답과 문서 제목을 확인했습니다. `show switches` 문서는 MM 자체를 포함한 장비 목록을 설명하지만 일부 예시는 6.x `master` 출력이며, `show switchinfo` 예시도 `switchrole:master`를 포함합니다. 이런 과거 `master/local` 표기만으로 ArubaOS 8의 MM Primary/Standby를 확정하지 않습니다. 이름·모델이나 목록 순서로 Primary를 추정하지 않으며 명시적인 conductor/standby/MD 역할 근거와 자기 식별을 확인합니다. 불명확한 장비는 AUTO로 남겨 활성 추적에서 제외하고 기존 수동 역할·관리 주소·매핑을 보존합니다. 문서의 예시를 실장비 호환성이나 사용자의 MD 오류 해결 증거로 사용하지 않습니다.

### 공식 문서의 실행 위치 표기 차이

8.10 PDF와 CLI Bank의 개별 AP/인증 명령 상당수는 Command Information에 Mobility Conductor라고 기재한다. 반면 [show ap debug 상위 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-debug.htm)는 managed devices를 명시하고, 공식 AOS 8 문제 해결 문서는 association과 auth-tracebuf를 MD에서 실행한다. 따라서 명령 존재만으로 모든 MM/MD 구성에서 같은 출력이 나온다고 보장하지 않는다. 신규 프로그램은 요구된 MM→담당 MD 경로를 사용하며, 거부된 선택 명령은 지원하지 않음/조회 실패로 남긴다. 다른 모든 MD로 확장하거나 설정 노드를 바꾸는 명령을 임의로 추가하지 않는다.

## 각 값이 뜻하는 것

| 화면 항목 | 근거 필드 | 해석 |
|---|---|---|
| IP/MAC/담당 MD | MM의 IP, MAC, Current switch | 담당 MD 주소는 SSH 접속 주소와 다를 수 있어 명시적인 관리 주소 매핑을 사용한다. |
| Role/VLAN/인증 방식 | 사용자 테이블의 해당 이름을 가진 열/값 | 정책의 기본 Role을 실제 적용 Role로 추정하지 않는다. 알 수 없는 값은 확인 불가다. |
| 현재 AP/BSSID/SSID | 활성 association 행의 Name, bssid, essid | 과거 association 행이나 trail 기록을 현재 상태로 덮어쓰지 않는다. |
| SNR(dB) | `Last SNR` 또는 `Last_Rx_SNR` | AP가 마지막 데이터 패킷에서 관측한 SNR이다. 조회 시각에 새 RF 측정을 강제하는 값이 아니다. `Last_ACK_SNR`은 ACK의 SNR이므로 별도 의미다. |
| Tx PHY Rate(Mbps) | `Tx_Rate` | AP가 단말로 보낸 마지막 패킷의 링크 속도. 실제 다운로드 Throughput이 아니다. |
| Rx PHY Rate(Mbps) | `Rx_Rate` | AP가 단말에서 받은 마지막 패킷의 링크 속도. 실제 업로드 Throughput이 아니다. |
| 송신/수신 패킷 | `Tx_Pkts` / `Rx_Pkts` 또는 출처가 식별되는 프레임 통계 | AP 기준 방향을 사용한다. 패킷과 프레임 카운터 종류를 섞지 않는다. |
| 재전송 | `Tx_Retries`, 또는 별도 의미의 `Success With Retry` | 전자는 AP 재전송 패킷, 후자는 재시도 후 성공한 프레임 수다. 동일한 카운터로 섞어 계산하지 않는다. |
| 마지막 유효 측정 시각 | 장비의 `Rx_Timestamp`/`Tx_Timestamp`가 파싱 가능한 경우 | PC 수집 시각과 다르다. 장비 시계·시간대가 확인되지 않으면 확정 UTC 시각으로 변환하지 않는다. |
| RSSI(dBm) | 현재 관측임이 명확한 RSSI 필드만 | 위 표준 출력만으로 항상 확보되는 값이 아니다. SNR에서 잡음 값을 임의로 빼서 만들지 않는다. |

`client-stats`의 `Tx 54 Mbps`, `Rx 54 Mbps`와 같은 통계 행은 해당 속도로 처리한 **프레임 개수**다. 이를 현재 속도로 표시하거나 최대 속도를 현재 값으로 선택하면 안 된다. 채널과 대역은 장비 출력에 명시된 값만 사용한다. 8.9 이후 `phy` 표기가 2.4/5/6 GHz 형태로 바뀌었으므로 예전 a/b/g 표기만 가정하지 않는다.

## 보수적인 판정 규칙

1. 명령 거부·권한 부족·타임아웃·출력 잘림·알 수 없는 형식은 정상 0건과 다르다. 실패 시 마지막 정상 값을 보존하고 이전 조회값임을 표시한다.
2. MM 검색 결과가 하나여도 MD 매핑이 없거나 여러 장비와 매칭되면 임의 장비에 접속하지 않는다.
3. 로밍은 동일 MAC의 연속된 정상 관측에서 AP/BSSID 변화를 확인한다. 실패를 사이에 둔 변화는 로밍이 일어난 정확한 순간을 증명하지 않는다.
4. 해제는 정상적인 부재/비연결 관측이 충분히 이어질 때만 확정한다. SSH 실패는 장비 조회 실패 이벤트다.
5. 카운터 비율은 같은 MAC·AP·BSSID·MD·카운터 종류의 연속 정상 표본에서만 고려한다. 초기화, 감소, 분모 0, 수집 누락, 장비 전환이면 계산하지 않는다. 서로 다른 카운터의 분모 의미가 검증되지 않으면 확인 불가를 유지한다.
6. 과거 auth/trail/ClientMatch 기록의 장비 시각은 수집 시각과 함께 보존한다. 원인 추정은 관측 사실과 구분한다.

## 부하·권한·명령 안전성

기본 주기는 15초이며 10/15/30/60초를 선택한다. 한 차례 수집이 끝나기 전에 다음 수집을 쌓지 않는다. MAC 필터 명령이더라도 AP와 MD에서 처리 비용이 발생한다. AP별 client-table은 AP 사용자 수에 따라 길어지므로 출력 크기와 응답 시간을 제한해야 한다. 과거 이력과 인증 버퍼는 정규 빠른 조회와 분리한 선택적 진단으로 다룬다.

공식 명령 표의 Base operating system은 기능 라이선스 정보다. 해당 SSH 계정이 명령 실행 권한을 갖는다는 뜻은 아니다. 관리자가 대상 조회 명령을 허용한 계정을 사용해야 하며, 앱은 권한을 올리기 위해 설정 변경·debug 활성화·세션 삭제·재부팅을 실행하지 않는다.

입력 IP는 IPv4 객체로 검사하고 MAC은 정확한 6바이트 형식으로 정규화한다. AP 이름은 허용 문자와 길이를 제한한다. 줄바꿈, 세미콜론, 파이프 및 추가 CLI 토큰은 거부한다. 거부된 명령을 무필터 전체 사용자/세션 명령으로 대체하지 않는다. 버전 변형은 문서와 테스트 근거가 있는 고정된 후보만 허용할 수 있으며, 이번 릴리스가 모든 변형을 지원한다는 뜻은 아니다.

## 장비 목록의 분리 표

`show switches` 출력은 장비 식별 열과 Status/Configuration 열이 별도 표로 나뉠 수 있습니다. v0.3.3은 첫 표의 IP·Name·Type을 읽고 후속 표의 구조와 행 수를 검증합니다. 두 표 모두 마지막 `Total Switches`와 일치해야 합니다. 한 표로 출력되는 형식도 유지하며, 알 수 없는 표를 무조건 무시하지 않습니다. 공식 문서의 `state complete`/`debug` 예시는 출력 구조의 근거일 뿐 앱에서 해당 명령 변형을 자동 실행하지 않습니다.

## IPv4가 없는 장비 행

[ArubaOS 8.10 User Guide](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/810/ArubaOS-8%2E10%2E0%2E0-User-Guide.pdf)의 861쪽은 `show switches`에서 `IP Address`가 `None`이고 `IPv6 Address`가 있는 MM 행을 보여 줍니다. v0.3.4는 이 경우 IPv6 주소를 검사하여 사용합니다. IPv4가 있으면 기존 선택을 유지하고, 잘못된 IPv4를 IPv6로 덮어쓰거나 주소 없는 행을 버리지 않습니다. 주소·행 수·중복·역할 검증은 유지합니다. 장비 관리 주소의 IPv6 지원이며 클라이언트 검색 범위(IPv4/MAC)는 바뀌지 않습니다.

문서의 해당 예시는 표시된 행 수와 `Total Switches`가 달라 완전한 CLI 응답으로 사용할 수 없습니다. 자동 검사는 같은 열 구조의 RFC 5737/RFC 3849 가상 주소와 완전한 행 수로 수행합니다. 이 형식의 지원 누락은 확인했지만 사용자가 보고한 오류의 실제 원인이 IPv6인지는 확인되지 않았습니다. [해당 패치 릴리스 노트](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/Release-Notes/810/ArubaOS-8%2E10%2E0%2E10-Release-Notes.pdf)에서도 이 앱의 파싱 오류를 장비 결함으로 설명하는 근거는 확인하지 못했습니다.

## SSH 페이지 넘김 안내

2026-10-27 [공식 paging 문서](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/paging.htm)에서 페이지 넘김이 기본 활성화되고 SSH 세션별로 적용됨을 확인했습니다. 큰 터미널 크기를 요청했다고 페이지 안내가 없어지는 것으로 가정하지 않습니다.

ArubaOS 8.10 CLI Reference PDF 물리 1629·3361쪽과 공식 [show ap arm status](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-arm-status.htm), [show snmp trap-list](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-snmp-trap-lst.htm) 예시는 `--More-- (q) quit (u) pageup (/) search (n) repeat` 전체 안내문을 보여 줍니다. 이 두 명령은 페이지 안내 형식을 확인한 문서이며 앱에서 새로 실행하지 않습니다.

v0.3.5는 SSH 응답에서 전체 안내문과 인접한 화면 지우기 제어를 제거한 뒤 기존 파서에 전달합니다. 기존 코드는 `--More--`만 제거하여 `(q) quit (u)` 12자와 `pageup (/) sea` 14자를 IP/IPv6 셀로 읽을 수 있었습니다. 페이지당 스페이스 한 번으로 다음 출력을 받고, 페이지 수·전체 수신 크기·시간 제한과 취소를 유지합니다. `no paging`이나 다른 설정 명령을 추가하지 않습니다. 공식 문서의 안내 문자열은 확인됐지만 화면 지우기 바이트·TCP 분할의 시험은 합성 전송 자료이며 실장비 캡처가 아닙니다.

## 사용자 장비에서 확인할 항목

2026-10-27 예방 점검 중 [show ap association 공식 Description/Example](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-assoc.htm)을 다시 대조했다. `A`는 현재 활성 연결이고 다른 대소문자 플래그는 단말 기능을 나타낸다. 헤더가 있어도 대상 행의 Flags 셀이 비거나 문서에 없는 값을 포함하면 해제로 확정하지 않고 조회 실패/연결 확인 불가로 처리한다. 문서에 나온 `W` 같은 비활성 행은 그대로 지원한다. 새 플래그·빈 셀의 실장비 의미는 공식 근거 없이 추정하지 않는다. 합성 collector→Tracker 회귀는 빈 값·기호·알 수 없는 텍스트가 해제/재연결/로밍 이벤트를 만들지 않는지 확인한다.

### 2026-10-27 Windows 발견 오류 재현과 구조 진단

이번 로컬 작업에서 공식 [show switches](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-switches.htm)의 Description, Example, Command Information과 [paging](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/paging.htm)의 Description을 직접 다시 확인했다. 식별 표 뒤에 상태 표가 이어지는 열 구성, Mobility Conductor 실행 위치와 세션별 기본 paging을 대조했다. [show ap arm status 예시](https://arubanetworking.hpe.com/techdocs/CLI-Bank/Content/aos8/sh-ap-arm-status.htm)의 전체 페이지 안내문도 다시 확인했으며 이 명령을 수집 allowlist에 추가하지 않았다. [ArubaOS v8.10.0.10 Release Notes](https://arubanetworking.hpe.com/techdocs/ArubaOS-8.x-Books/Release-Notes/810/ArubaOS-8%2E10%2E0%2E10-Release-Notes.pdf) 8–9쪽의 SSH 변경 사항과 Conductor/7210/7240XM 지원 범위를 확인했다. CLI Reference와 User Guide PDF는 이번 재조회에서 도구 크기 제한 또는 사이트 접근 거부로 전체를 다시 읽지 못했으므로 앞 절의 PDF 페이지 근거는 이전 검토 기록이다. CLI Bank의 과거 버전 예시를 8.10.0.10의 실제 SSH 바이트와 동일시하지 않는다.

최신 `출력 9행 · IP 열 길이 0 · IPv6 열 길이 0`과 같은 문구는 합성 행의 주소 두 셀을 비워 재현했다. 이는 빈 셀도 종전 코드가 IP 형식 오류로 묶어 안내한다는 증거이며, 사용자의 실장비에서 두 셀이 비어진 원인을 입증하지 않는다. 이번 파서는 `ADDRESS_CELL_EMPTY`, `ROW_TOO_SHORT`, `ADDRESS_INVALID`, `TABLE_LAYOUT`, `OUTPUT_INCOMPLETE`, `COUNT_MISMATCH`, `UNKNOWN_TABLE`, `UNKNOWN_ROW`로 확인된 실패 유형을 구분한다. 빈 주소 행을 삭제하거나 잘못된 IPv4를 IPv6로 덮어쓰지 않는다.

별도 합성 SSH 시험에서 첫 줄부터 들여쓰기된 표를 받을 때 `strip()`이 첫 머리글의 공백만 제거하여 구분선과 열 시작 위치가 달라지는 문제를 확인했다. 빈 줄만 제거하도록 수정해 각 행의 들여쓰기를 유지한다. 현재 표와 같은 열 구성의 반복 머리글은 바로 다음 구분선을 검증한 뒤 동일 표를 계속 읽으며, 누적 행 수·중복 주소·완료 건수 검사는 유지한다. 반복 머리글과 페이지 위치는 가상 장애 경계이며 공식 문서가 해당 모델의 실제 반복 방식을 보증한 것은 아니다.

오류 상세의 구조 진단에는 수집기/파서 버전, 수신·정규화·파싱 행 수, 실패 행의 길이·선행 공백·공백 구간 수, 문자/숫자/기타 문자 개수, 공식 열 이름과 0부터 시작하는 `[시작:끝)` 위치, 선언/식별/상태 건수, 반복 머리글과 완료 표식 개수가 들어간다. 실패 행 번호는 명령 에코와 SSH 프롬프트를 제거한 정규화 출력의 첫 행을 1로 센다. 전체 표 검증에서 아직 특정 행을 선택하지 못했으면 0으로 표시한다. 수신 통계는 에코/프롬프트를 포함하고, CR/LF/ANSI/백스페이스/페이지 안내/계속 요청 개수와 프롬프트·종료 상태를 기록한다. 중단된 수신의 정규화 행 수 0은 완성된 파서 입력이 없다는 뜻이다. 원문, 주소 셀 값, 장비명, 계정, 비밀번호는 이 구조 메시지에 넣지 않으며 자동 파일 저장이나 업로드도 하지 않는다. 화면의 기존 장비명/endpoint는 로컬 연결 대상을 구별하기 위한 별도 항목이므로 공유 시에는 구조 메시지만 사용한다.

회귀 검사는 RFC 5737/3849 가상 자료를 사용한다. 실제 Paramiko SSH를 루프백에만 연결하여 머리글/구분선 사이 페이지 경계, 식별·상태 머리글 반복, 후보 목록, 사용자가 명시적으로 선택한 MD의 자기 식별과 매핑 갱신까지 검증한다. 발견된 운영 주소로 자동 접속하거나 새 명령 변형·설정 변경을 실행하지 않는다. **사용자의 최신 오류 원인과 Aruba 실장비 발견·선택 검사 성공은 검증 대기다.**

발견 시 seed와 선택한 장비의 읽기 전용 명령 권한·역할·주소를 먼저 확인합니다. 처음에는 60초 주기로 대상 MAC 하나를 조회하여 MM Primary/Standby, Current switch 매핑, MD 사용자 결과와 AP 소유 관계를 확인한다. 각 명령의 거부 여부·필터 결과·필드 단위와 수집 시간을 확인한 후 15초로 낮춘다. AP-535 및 7240XM의 실제 카운터 의미, 클러스터 UAC/AAC 차이, 시계/시간대, dormant/비활성 행, 읽기 권한, 출력 폭·페이지 처리, 절전 단말의 오래된 마지막 패킷 값은 운영 환경에서 검증해야 한다. 실제 출력 원문을 공개 이슈나 저장소에 첨부하지 않는다.
