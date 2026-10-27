"""Strictly filtered, read-only ArubaOS 8 CLI commands.

Syntax source: HPE ArubaOS 8.10 CLI Reference Guide; see docs/CLI_COMMANDS_KO.md.
"""
from __future__ import annotations

import re
from ipaddress import IPv4Address

from .models import Target

_MAC_PATTERNS = (
    re.compile(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}\Z"),
    re.compile(r"(?:[0-9a-fA-F]{2}-){5}[0-9a-fA-F]{2}\Z"),
    re.compile(r"(?:[0-9a-fA-F]{4}\.){2}[0-9a-fA-F]{4}\Z"),
)
_SAFE_AP = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")


def normalize_mac(value: str) -> str:
    if not isinstance(value, str) or not any(p.fullmatch(value) for p in _MAC_PATTERNS):
        raise ValueError("MAC 주소 형식을 확인하십시오. 예: aa:bb:cc:dd:ee:ff")
    compact = re.sub(r"[:-]|\.", "", value).lower()
    return ":".join(compact[i:i + 2] for i in range(0, 12, 2))


def parse_target(value: str) -> Target:
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        raise ValueError("IP 또는 MAC에는 제어 문자를 사용할 수 없습니다.")
    value = value.strip()
    try:
        return Target("ip", str(IPv4Address(value)))
    except ValueError:
        return Target("mac", normalize_mac(value))


def global_user_command(target: Target) -> str:
    if target.kind == "ip":
        return f'show global-user-table list ip "{IPv4Address(target.value)}"'
    if target.kind == "mac":
        return f"show global-user-table list mac-addr {normalize_mac(target.value)}"
    raise ValueError("지원하지 않는 검색 형식입니다.")


def user_command(mac: str) -> str:
    return f"show user-table mac {normalize_mac(mac)}"


def association_command(mac: str) -> str:
    return f"show ap association client-mac {normalize_mac(mac)}"


def stats_command(mac: str) -> str:
    return f"show ap debug client-stats client-mac {normalize_mac(mac)} advanced"


def client_table_command(ap_name: str) -> str:
    if not _SAFE_AP.fullmatch(ap_name):
        raise ValueError("AP 이름은 영문·숫자·점·밑줄·콜론·하이픈으로 128자까지 허용합니다.")
    return f"show ap debug client-table ap-name {ap_name}"


def history_commands(mac: str) -> tuple[str, ...]:
    mac = normalize_mac(mac)
    return (
        f"show ap client trail-info {mac}",
        f"show ap arm client-match history client-mac {mac}",
        f"show auth-tracebuf mac {mac}",
    )


def validate_command(command: str) -> str:
    """Reject everything except exact generated command forms, including line endings."""
    if not isinstance(command, str) or any(ord(c) < 32 for c in command):
        raise ValueError("조회 전용 명령어만 허용합니다.")
    ip = re.fullmatch(r'show global-user-table list ip "([0-9.]+)"', command)
    if ip and command == global_user_command(Target("ip", ip.group(1))):
        return command
    prefixes = (
        "show global-user-table list mac-addr ", "show user-table mac ",
        "show ap association client-mac ", "show ap client trail-info ",
        "show ap arm client-match history client-mac ", "show auth-tracebuf mac ",
    )
    for prefix in prefixes:
        if command.startswith(prefix):
            mac = command[len(prefix):]
            if normalize_mac(mac) == mac:
                return command
    prefix = "show ap debug client-stats client-mac "
    if command.startswith(prefix) and command.endswith(" advanced"):
        mac = command[len(prefix):-9]
        if normalize_mac(mac) == mac:
            return command
    prefix = "show ap debug client-table ap-name "
    if command.startswith(prefix) and client_table_command(command[len(prefix):]) == command:
        return command
    raise ValueError("허용되지 않은 명령어입니다. 전체 테이블과 설정 변경 명령은 사용할 수 없습니다.")
