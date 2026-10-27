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
