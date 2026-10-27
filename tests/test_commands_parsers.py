"""All fixtures below are synthetic, never collected from a network."""
import pytest

from aruba_client_live_tracker.commands import (
    association_command,
    client_table_command,
    global_user_command,
    normalize_mac,
    parse_target,
    stats_command,
    user_command,
    validate_command,
)
from aruba_client_live_tracker.parsers import (
    ParseError,
    parse_association,
    parse_client_stats,
    parse_client_table,
    parse_global_users,
    parse_user,
)

MAC = "02:00:00:00:00:01"


def table(headers, rows, footer="Total entries = {count}"):
    widths = [max(len(h), *(len(str(r[i])) for r in rows), 3) + 3 for i, h in enumerate(headers)]
    def line(cells):
        return "".join(str(v).ljust(w) for v, w in zip(cells, widths)).rstrip()
    return "\n".join([line(headers), line(["-" * (w - 3) for w in widths]),
                      *(line(r) for r in rows), footer.format(count=len(rows))])


def global_output(rows=None):
    if rows is None:
        rows = [["192.0.2.100", MAC, "", "192.0.2.20", "lab-role", "802.1X", "LAB-AP-A"]]
    return table(["IP", "MAC", "Name", "Current switch", "Role", "Auth", "AP name"], rows)


@pytest.mark.parametrize("text", ["AA:BB:CC:DD:EE:FF", "aa-bb-cc-dd-ee-ff", "aabb.ccdd.eeff"])
def test_mac_normalized(text):
    assert normalize_mac(text) == "aa:bb:cc:dd:ee:ff"
    assert parse_target(text).kind == "mac"


@pytest.mark.parametrize("text", ["999.1.1.1", "192.0.2.001", "192.0.2.1;reload", "aa:bb:cc:dd:ee", "", "::1", "aabbccddeeff", "02:00:00:00:00:01\nreload"])
def test_invalid_target(text):
    with pytest.raises(ValueError):
        parse_target(text)


def test_command_allowlist():
    assert global_user_command(parse_target("192.0.2.100")) == 'show global-user-table list ip "192.0.2.100"'
    for cmd in [global_user_command(parse_target(MAC)), user_command(MAC), association_command(MAC), stats_command(MAC), client_table_command("LAB-AP-A")]:
        assert validate_command(cmd) == cmd
    for cmd in ["show user-table", "show running-config", "reload", "show user-table mac " + MAC + "\nreload", "show ap debug client-table ap-name AP;foo"]:
        with pytest.raises(ValueError):
            validate_command(cmd)
    for name in ["AP\nshow user-table", "AP;reload", 'AP"bad', "../AP"]:
        with pytest.raises(ValueError):
            client_table_command(name)


def test_global_complete_duplicate_and_blank_name():
    found = parse_global_users(global_output(), parse_target("192.0.2.100"))
    assert found[0].current_switch == "192.0.2.20"
    assert found[0].mac == MAC
    assert found[0].ap_name == "LAB-AP-A"
    assert parse_global_users(global_output([]), parse_target(MAC)) == []
    duplicate = global_output([["192.0.2.100", MAC, "", "192.0.2.20", "r", "", "A"],
                               ["192.0.2.100", "02:00:00:00:00:02", "", "192.0.2.20", "r", "", "A"]])
    assert len(parse_global_users(duplicate, parse_target("192.0.2.100"))) == 2


@pytest.mark.parametrize("output", ["", "New layout", "Total entries = 0", "% Invalid input", global_output().replace("Total entries = 1", "Total entries = 2"), global_output().split("Total entries")[0]])
def test_global_unrecognized_or_truncated_is_not_absence(output):
    with pytest.raises(ParseError):
        parse_global_users(output, parse_target(MAC))


def test_user_detail_official_shape_synthetic_values():
    output = f'''Name: synthetic, IP: 192.0.2.100, MAC: {MAC}, Role: lab-role,
Authentication: Yes, status: started, method: 802.1X, protocol: EAP, server: LAB
Vlan default: 3, Assigned: 5, Current: 5 vlan-how: 0 DP assigned vlan:0
Essid: LAB-WIFI, Bssid: 02:00:00:00:10:01 AP name/group: LAB-AP-A/lab Phy-type: a-HE
'''
    obs = parse_user(output, MAC)
    assert obs.ip == "192.0.2.100"
    assert (obs.vlan, obs.role, obs.ssid, obs.ap_name) == ("5", "lab-role", "LAB-WIFI", "LAB-AP-A")
    assert obs.auth_method == "802.1X"
    assert obs.auth_result == "Yes / started"


def test_user_different_mac_rejected():
    with pytest.raises(ParseError):
        parse_user("IP: 192.0.2.100, MAC: 02:00:00:00:00:02, Role: lab", MAC)


def test_association_ignores_historical_ap():
    output = table(["Name", "bssid", "mac", "auth", "assoc", "essid", "vlan-id", "Flags"], [
        ["LAB-OLD", "02:00:00:00:10:01", MAC, "y", "n", "LAB-WIFI", "10", "W"],
        ["LAB-NEW", "02:00:00:00:10:02", MAC, "y", "y", "LAB-WIFI", "20", "WA"]], "Num Clients:{count}")
    parsed = parse_association(output, MAC)
    assert parsed["ap_name"] == "LAB-NEW"
    assert parsed["connected"] is True


def test_client_stats_rate_bucket_is_not_phy_rate_and_no_fake_rssi():
    fields = parse_client_stats("Station Stats\nFrames Transmitted   120\nFrames Received 90\nSuccess With Retry 8\nLast SNR 27\nTx 54 Mbps 123\nRx 48 Mbps 321")
    assert fields["snr"] == 27
    assert fields["tx_packets"] == 120
    assert "tx_rate" not in fields and "rx_rate" not in fields and "rssi" not in fields
    assert "retries" not in fields


def test_client_table_exact_mac_phy_rates_and_counters():
    output = table(["MAC", "ESSID", "BSSID", "Assoc_State", "Tx_Pkts", "Rx_Pkts", "Tx_Retries", "Tx_Rate", "Rx_Rate", "Last_Rx_SNR"], [
        [MAC, "LAB-WIFI", "02:00:00:00:10:01", "Associated", "1000", "800", "40", "866.7", "780", "35"]], "")
    fields = parse_client_table(output, MAC)
    assert fields["tx_rate"] == 866.7 and fields["rx_rate"] == 780
    assert fields["retries"] == 40 and fields["snr"] == 35


def test_incomplete_user_detail_cannot_claim_presence():
    with pytest.raises(ParseError):
        parse_user(f"MAC: {MAC}", MAC)


def test_global_table_common_hierarchy_prompt():
    output = global_output() + "\n(LAB-MM) ^*[mynode] #"
    assert parse_global_users(output, parse_target(MAC))[0].mac == MAC


@pytest.mark.parametrize("state, bssid", [("Disconnected", "02:00:00:00:10:01"), ("Associated", "02:00:00:00:10:02")])
def test_client_table_rejects_inactive_or_other_ap(state, bssid):
    output = table(["MAC", "ESSID", "BSSID", "Assoc_State", "Tx_Rate", "Rx_Rate"], [
        [MAC, "LAB-WIFI", bssid, state, "100", "100"]], "")
    with pytest.raises(ParseError):
        parse_client_table(output, MAC, expected_bssid="02:00:00:00:10:01")


@pytest.mark.parametrize("ip_label", ["IP", "IP Address"])
@pytest.mark.parametrize("mac_label", ["MAC", "MAC Address"])
def test_explicit_address_header_aliases(ip_label, mac_label):
    # Synthetic variant: only these exact labels are aliases; required fields remain.
    output = table([ip_label, mac_label, "Current switch", "Role"],
                   [["192.0.2.100", MAC, "192.0.2.20", "lab-role"]])
    assert parse_global_users(output, parse_target(MAC))[0].mac == MAC
    user = table([ip_label, mac_label, "Role"], [["192.0.2.100", MAC, "lab-role"]])
    assert parse_user(user, MAC).ip == "192.0.2.100"
    detail = f"{ip_label}: 192.0.2.100, {mac_label}: {MAC}, Role: lab-role"
    assert parse_user(detail, MAC).role == "lab-role"


@pytest.mark.parametrize("parser", ["global", "user"])
@pytest.mark.parametrize("fault", ["truncated", "count", "duplicate_columns", "missing_role", "bad_ip", "bad_mac"])
def test_address_aliases_remain_fail_closed(parser, fault):
    headers = ["IP Address", "MAC Address", "Role"]
    rows = [["192.0.2.100", MAC, "lab-role"]]
    if parser == "global":
        headers.append("Current switch")
        rows[0].append("192.0.2.20")
    if fault == "duplicate_columns":
        headers.append("IP")
        rows[0].append("192.0.2.101")
    elif fault == "missing_role":
        headers[2] = "Other"
    elif fault == "bad_ip":
        rows[0][0] = "999.0.2.1"
    elif fault == "bad_mac":
        rows[0][1] = "02:bad"
    output = table(headers, rows)
    if fault == "truncated":
        output = output.split("Total entries")[0]
    elif fault == "count":
        output = output.replace("Total entries = 1", "Total entries = 2")
    with pytest.raises(ParseError):
        if parser == "global":
            parse_global_users(output, parse_target(MAC))
        else:
            parse_user(output, MAC)


def test_address_alias_does_not_hide_duplicate_md_rows():
    row = ["192.0.2.100", MAC, "lab-role"]
    output = table(["IP Address", "MAC Address", "Role"], [row, row])
    with pytest.raises(ParseError):
        parse_user(output, MAC)


@pytest.mark.parametrize("fault", ["missing_flags", "unknown_assoc", "blank_assoc", "missing_name", "bad_bssid", "conflicting_flags"])
def test_association_incomplete_target_evidence_is_not_connection_or_absence(fault):
    headers = ["Name", "bssid", "mac", "assoc", "Flags"]
    row = ["LAB-AP", "02:00:00:00:10:01", MAC, "y", "WA"]
    if fault == "missing_flags":
        headers.pop()
        row.pop()
    elif fault == "unknown_assoc":
        row[3] = "unknown"
    elif fault == "blank_assoc":
        row[3] = ""
    elif fault == "missing_name":
        row[0] = ""
    elif fault == "bad_bssid":
        row[1], row[3], row[4] = "invalid", "n", "W"
    else:
        row[3] = "n"
    with pytest.raises(ParseError):
        parse_association(table(headers, [row], "Num Clients:{count}"), MAC)


def test_association_validates_inactive_target_rows_before_using_active_row():
    output = table(["Name", "bssid", "mac", "assoc", "Flags"], [
        ["LAB-AP", "02:00:00:00:10:01", MAC, "y", "WA"],
        ["LAB-OLD", "invalid", MAC, "n", "W"],
    ], "Num Clients:{count}")
    with pytest.raises(ParseError):
        parse_association(output, MAC)


@pytest.mark.parametrize("rows", [[], [["LAB-OLD", "02:00:00:00:10:01", MAC, "n", "W"]]])
def test_association_complete_empty_or_historical_table_remains_absent(rows):
    output = table(["Name", "bssid", "mac", "assoc", "Flags"], rows, "Num Clients:{count}")
    assert parse_association(output, MAC) == {"connected": False}


def test_documented_inactive_association_flags_keep_case_and_remain_inactive():
    output = table(['Name', 'bssid', 'mac', 'assoc', 'Flags'], [
        ['LAB-OLD', '02:00:00:00:10:01', MAC, 'n', 'BHKMRWwVPUOSEmCcpTt'],
    ], 'Num Clients:{count}')
    assert parse_association(output, MAC) == {'connected': False}


@pytest.mark.parametrize("other_mac", [MAC, "02:00:00:00:00:02", "invalid"])
@pytest.mark.parametrize("first_complete", [False, True])
def test_user_detail_multiple_records_cannot_merge_or_select_first(other_mac, first_complete):
    first = f"IP: 192.0.2.100, MAC: {MAC}" + (", Role: first" if first_complete else "")
    second = f"IP: 192.0.2.101, MAC: {other_mac}, Role: second\nEssid: OTHER, Bssid: 02:00:00:00:20:01 AP name/group: OTHER-AP/lab"
    with pytest.raises(ParseError):
        parse_user(first + "\n" + second, MAC)


@pytest.mark.parametrize("duplicate", ["IP: 192.0.2.101", "Role: other"])
def test_user_detail_repeated_identity_fields_are_ambiguous(duplicate):
    with pytest.raises(ParseError):
        parse_user(f"IP: 192.0.2.100, MAC: {MAC}, Role: first\n{duplicate}", MAC)


@pytest.mark.parametrize("parser", ["global", "user", "association"])
@pytest.mark.parametrize("populated", [False, True])
def test_completed_table_requires_its_count_after_rows(parser, populated):
    if parser == "association":
        rows = [["LAB-AP", "02:00:00:00:10:01", MAC, "y", "WA"]] if populated else []
        output = table(["Name", "bssid", "mac", "assoc", "Flags"], rows, "Num Clients:{count}")
        def parse(out):
            return parse_association(out, MAC)
    else:
        output = global_output() if populated else global_output([])
        parse = (lambda out: parse_global_users(out, parse_target(MAC))) if parser == "global" else (lambda out: parse_user(out, MAC))
    body, count = output.rsplit("\n", 1)
    with pytest.raises(ParseError):
        parse(count + "\n" + body)


@pytest.mark.parametrize("trailer", ["Total num of arbitrary text", "Total num of dual-band capable clients:unknown"])
def test_completed_table_rejects_unknown_summary_trailers(trailer):
    output = table(["Name", "bssid", "mac", "assoc", "Flags"], [], "Num Clients:{count}")
    with pytest.raises(ParseError):
        parse_association(output + "\n" + trailer, MAC)
    with pytest.raises(ParseError):
        parse_global_users(global_output([]) + "\n" + trailer, parse_target(MAC))


def test_association_accepts_documented_numeric_summary_trailers():
    output = table(["Name", "bssid", "mac", "assoc", "Flags"], [], "Num Clients:{count}")
    output += "\n" + "\n".join([
        "Total num of dual-band capable clients:0",
        "Total num of dual-band capable clients in 2.4G band:0",
        "Total num of dual-band capable clients in 5G band:0",
        "Total num of clients in 6G band:0",
        "Total num of single-band only clients:0",
        "(LAB-MD) [mynode] #",
    ])
    assert parse_association(output, MAC) == {"connected": False}
    with pytest.raises(ParseError):
        parse_global_users(global_output([]) + "\nTotal num of dual-band capable clients:0", parse_target(MAC))
