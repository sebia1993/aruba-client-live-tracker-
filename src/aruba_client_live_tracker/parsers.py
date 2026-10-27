"""Conservative ArubaOS CLI parsers. Unknown output is never an empty result.

All tests use invented fixtures. Last packet PHY/SNR fields are not throughput
or continuously measured live signal. No ClientMatch measurement is consumed here.
"""
from __future__ import annotations

import re
from ipaddress import IPv4Address

from .commands import normalize_mac
from .models import Candidate, Observation, Target


class ParseError(ValueError):
    pass


class UnsupportedCommand(ParseError):
    pass


_ERROR = re.compile(r"(?im)(?:^\s*%?\s*(?:Invalid (?:input|command)|Unknown command|Error:|Permission denied|Access denied)|command not supported|not supported on this)")
_COUNT = re.compile(r"(?im)^\s*(?:Total\s+entries\s*=|Num\s+Clients\s*:)\s*(\d+)\s*$")
# Explicit address-label aliases covered by synthetic fixtures; no positional fallback.
_COLUMN_ALIASES = {"ipaddress": "ip", "macaddress": "mac"}
_MAC = r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}"
_PROMPT = re.compile(r"^\s*(?:\([^\r\n]{1,100}\)\s*)?[\^*]{0,2}\s*(?:\[[^\r\n]{1,100}\]\s*)?[A-Za-z0-9_.:^*-]*[#>]\s*$")
_ASSOCIATION_SUMMARY = re.compile(
    r"\s*Total num of (?:dual-band capable clients(?: in (?:2\.4G|5G) band)?|"
    r"clients in 6G band|single-band only clients):\s*\d+\s*"
)
# HPE show ap association, Description/Example (reviewed 2026-10-27).
# Unknown/absent flag cells cannot establish that the active flag is absent.
_ASSOCIATION_FLAGS = re.compile(r'[ABHKMRWwVPUOSEmCcpTt]{1,64}\Z')


def reject_errors(output: str) -> None:
    if len(output) > 1024 * 1024:
        raise ParseError("CLI 출력이 허용 크기를 초과했습니다.")
    if _ERROR.search(output):
        raise UnsupportedCommand("명령어가 거부되었습니다. 지원 여부와 조회 권한을 확인하십시오.")
    if not output.strip():
        raise ParseError("장비 응답이 비어 있습니다.")


def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _table(output: str, required: tuple[str, ...], *, require_count: bool = False,
           association_summary: bool = False) -> list[dict[str, str]]:
    reject_errors(output)
    lines = output.splitlines()
    header_index = None
    for i, line in enumerate(lines):
        # Header requirements must be individual labels, not the data table title.
        if all(re.search(r"(?i)(?<![A-Za-z_])" + re.escape(label) + r"(?![A-Za-z_])", line) for label in required):
            header_index = i
            break
    if header_index is None:
        raise ParseError("CLI 표 머리글을 인식하지 못했습니다. 출력 형식 변경 여부를 확인하십시오.")
    separator_index = header_index + 1
    while separator_index < len(lines) and not lines[separator_index].strip():
        separator_index += 1
    if separator_index >= len(lines) or not re.fullmatch(r"\s*-+(?:\s+-+)*\s*", lines[separator_index]):
        raise ParseError("CLI 열 구분선을 인식하지 못했습니다.")
    spans = list(re.finditer(r"-+", lines[separator_index]))
    header = lines[header_index]
    if len(spans) == 1:
        labels = list(re.finditer(r"\S(?:.*?\S)?(?=\s{2,}|$)", header))
        starts = [m.start() for m in labels]
        names = [_key(m.group()) for m in labels]
    else:
        starts = [m.start() for m in spans]
        names = [_key(header[start:starts[j + 1] if j + 1 < len(starts) else None].strip()) for j, start in enumerate(starts)]
    names = [_COLUMN_ALIASES.get(name, name) for name in names]
    if len(names) != len(set(names)) or not all(_key(x) in names for x in required):
        raise ParseError("CLI 표의 열 위치가 올바르지 않습니다.")
    rows: list[dict[str, str]] = []
    counts = list(_COUNT.finditer(output))
    if require_count and len(counts) != 1:
        raise ParseError("완료 건수가 없어 조회 결과를 확정할 수 없습니다.")
    completed = False
    for line in lines[separator_index + 1:]:
        if not line.strip():
            continue
        if _COUNT.fullmatch(line):
            completed = True
            continue
        if _PROMPT.fullmatch(line.strip()):
            continue
        if completed:
            if association_summary and _ASSOCIATION_SUMMARY.fullmatch(line):
                continue
            raise ParseError("완료 건수 뒤에 알 수 없는 데이터가 있습니다.")
        if re.match(r"\s*(?:UAPSD:|HT Flags:|VHT Flags:|HT_State|Flags:)", line):
            break
        row = {name: line[start:starts[i + 1] if i + 1 < len(starts) else None].strip() for i, (name, start) in enumerate(zip(names, starts))}
        if len(rows) >= 4096:
            raise ParseError("CLI 표가 허용 행 수를 초과했습니다.")
        rows.append(row)
    if require_count and not completed:
        raise ParseError("표 뒤의 완료 건수가 없어 조회 결과를 확정할 수 없습니다.")
    if require_count and len(rows) != int(counts[0].group(1)):
        raise ParseError("CLI 완료 건수와 실제 행 수가 달라 출력 누락이 의심됩니다.")
    return rows


def parse_global_users(output: str, target: Target) -> list[Candidate]:
    rows = _table(output, ("IP", "MAC", "Current switch", "Role"), require_count=True)
    found = []
    for row in rows:
        try:
            ip, mac = str(IPv4Address(row["ip"])), normalize_mac(row["mac"])
        except (ValueError, KeyError) as exc:
            raise ParseError("MM 사용자 행의 IP/MAC 형식이 올바르지 않습니다.") from exc
        switch = row["currentswitch"]
        if not switch or len(switch) > 128 or any(ord(c) < 32 for c in switch):
            raise ParseError("담당 MD 식별 정보가 올바르지 않습니다.")
        if (target.kind == "ip" and ip != target.value) or (target.kind == "mac" and mac != normalize_mac(target.value)):
            continue
        entry = Candidate(ip, mac, switch, row.get("role") or None, row.get("apname") or None, row.get("auth") or None)
        if entry not in found:
            found.append(entry)
    return found


def _capture(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.I | re.M)
    return match.group(1).strip() if match else None


def parse_user(output: str, mac: str) -> Observation | None:
    reject_errors(output)
    mac = normalize_mac(mac)
    if re.fullmatch(r"\s*(?:No users found\.?|No matching users\.?)\s*", output, re.I):
        return None
    identity = {
        field: re.findall(r"(?:^|[,\n])[ \t]*" + label + r"[ \t]*:[ \t]*([^,\n]*)", output, re.I)
        for field, label in (("mac", r"MAC(?: Address)?"), ("ip", r"IP(?: Address)?"), ("role", "Role"))
    }
    if identity["mac"]:
        # Each detail response must identify one complete record. Never take one
        # record's identity and another record's policy or radio information.
        if any(len(values) != 1 for values in identity.values()):
            raise ParseError("MD 상세 응답의 IP/MAC/Role이 없거나 중복되어 단일 결과를 확정할 수 없습니다.")
        try:
            detail_mac = normalize_mac(identity["mac"][0].strip())
            ip = str(IPv4Address(identity["ip"][0].strip()))
        except ValueError as exc:
            raise ParseError("MD IP/MAC 주소 형식을 인식하지 못했습니다.") from exc
        if detail_mac != mac:
            raise ParseError("응답 MAC이 선택한 단말과 일치하지 않습니다.")
        role = identity["role"][0].strip()
        if not role:
            raise ParseError("MD 상세 응답에 필수 IP 또는 Role이 없어 결과를 확정할 수 없습니다.")
        auth = _capture(r"^\s*Authentication\s*:\s*([^,\n]+)", output)
        status = _capture(r"\bstatus\s*:\s*([^,\n]+)", output)
        return Observation(
            ip=ip, mac=mac,
            role=role,
            vlan=_capture(r"^\s*Vlan default:.*?\bCurrent:\s*(\d+)", output),
            auth_method=_capture(r"\bmethod\s*:\s*([^,\n]+)", output),
            auth_result=" / ".join(x for x in (auth, status) if x) or None,
            ssid=_capture(r"\bEssid:\s*([^,\n]+)", output),
            bssid=_capture(r"\bBssid:\s*(" + _MAC + ")", output),
            ap_name=_capture(r"\bAP name/group:\s*([^/\n]+)", output),
        )
    rows = _table(output, ("IP", "MAC", "Role"), require_count=True)
    try:
        for row in rows:
            row["ip"] = str(IPv4Address(row["ip"]))
            row["mac"] = normalize_mac(row["mac"])
            if not row["role"]:
                raise ValueError("missing role")
    except (KeyError, ValueError) as exc:
        raise ParseError("MD 사용자 행의 필수 IP/MAC/Role을 확인할 수 없습니다.") from exc
    matches = [r for r in rows if r["mac"] == mac]
    if not matches:
        return None
    if len(matches) != 1:
        raise ParseError("MD 사용자 결과가 중복되어 상세 정보를 확정할 수 없습니다.")
    row = matches[0]
    obs = Observation(ip=str(IPv4Address(row["ip"])), mac=mac, role=row["role"] or None,
                      ap_name=row.get("apname") or None, vlan=row.get("vlan") or None,
                      auth_method=row.get("auth") or None, ssid=row.get("essid") or None)
    combined = row.get("essidbssidphy", "")
    match = re.fullmatch(r"(.*)/(" + _MAC + r")/(.*)", combined)
    if match:
        obs.ssid, obs.bssid = match.group(1), normalize_mac(match.group(2))
    return obs


def parse_association(output: str, mac: str) -> dict:
    rows = _table(output, ("Name", "bssid", "mac", "assoc", "Flags"),
                  require_count=True, association_summary=True)
    mac = normalize_mac(mac)
    try:
        matches = [row for row in rows if normalize_mac(row["mac"]) == mac]
        for row in matches:
            row["bssid"] = normalize_mac(row["bssid"])
            row["assoc"] = row["assoc"].lower()
            if not row["name"] or not row["name"].isprintable() or row["assoc"] not in ("y", "n"):
                raise ValueError("incomplete association identity or state")
            if not _ASSOCIATION_FLAGS.fullmatch(row['flags']):
                raise ValueError('missing or unsupported association flags')
            if row["assoc"] == "n" and "A" in row["flags"]:
                raise ValueError("conflicting association state")
    except (KeyError, ValueError) as exc:
        raise ParseError("AP 연결 행의 MAC/BSSID/이름 또는 연결 상태를 확인할 수 없습니다.") from exc
    active = [row for row in matches if row["assoc"] == "y" and "A" in row["flags"]]
    if len(active) > 1:
        raise ParseError("여러 AP가 활성 연결을 보고하여 현재 AP를 확정할 수 없습니다.")
    if not active:
        return {"connected": False}
    row = active[0]
    fields = {"connected": True, "ap_name": row["name"], "bssid": row["bssid"]}
    for source, destination in [("essid", "ssid"), ("vlanid", "vlan"), ("channel", "channel")]:
        if row.get(source):
            fields[destination] = row[source]
    phy = row.get("phy", "")
    for text, band in [("2.4GHz", "2.4 GHz"), ("5GHz", "5 GHz"), ("6GHz", "6 GHz")]:
        if text.lower() in phy.lower():
            fields["band"] = band
    return fields


def _number(value: str, *, integer: bool = False) -> float | int | None:
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:Mbps|dB)?\s*", value, re.I)
    if not match:
        return None
    number = float(match.group(1))
    return int(number) if integer and number.is_integer() else (None if integer else number)


def parse_client_stats(output: str) -> dict:
    reject_errors(output)
    fields = {}
    for label, field, integer in [("Last SNR", "snr", False), ("Frames Transmitted", "tx_packets", True), ("Frames Received", "rx_packets", True)]:
        value = _capture(r"^\s*" + re.escape(label) + r"\s*:?\s+(\d+(?:\.\d+)?)\s*$", output)
        if value is not None:
            fields[field] = _number(value, integer=integer)
    if not fields:
        raise ParseError("지원되는 무선 통계 필드를 찾지 못했습니다.")
    return fields


def parse_client_table(output: str, mac: str, *, expected_bssid: str | None = None) -> dict:
    rows = _table(output, ("MAC", "ESSID", "BSSID", "Tx_Rate", "Rx_Rate"))
    mac = normalize_mac(mac)
    matches = [r for r in rows if normalize_mac(r["mac"]) == mac]
    if len(matches) != 1:
        raise ParseError("AP 표에서 선택한 MAC의 단일 행을 찾지 못했습니다.")
    row = matches[0]
    if row.get("assocstate", "").lower() != "associated":
        raise ParseError("AP 표의 단말이 현재 연결 상태가 아니므로 무선 통계를 사용하지 않습니다.")
    try:
        observed_bssid = normalize_mac(row.get("bssid", ""))
    except ValueError as exc:
        raise ParseError("AP 표의 BSSID를 확인할 수 없습니다.") from exc
    if expected_bssid is not None and observed_bssid != normalize_mac(expected_bssid):
        raise ParseError("AP 표 BSSID가 현재 활성 연결과 다릅니다. 이전 AP 통계는 사용하지 않습니다.")
    fields = {}
    for label, field, integer in [("txrate", "tx_rate", False), ("rxrate", "rx_rate", False),
                                  ("lastRxSnr".lower(), "snr", False), ("txpkts", "tx_packets", True),
                                  ("rxpkts", "rx_packets", True), ("txretries", "retries", True)]:
        number = _number(row.get(label, ""), integer=integer)
        if number is not None:
            fields[field] = number
    if not fields:
        raise ParseError("AP 표의 무선 통계를 인식하지 못했습니다.")
    for label, field in [("txtimestamp", "tx_sample_time"), ("rxtimestamp", "rx_sample_time")]:
        if row.get(label):
            fields[field] = row[label]
    return fields
