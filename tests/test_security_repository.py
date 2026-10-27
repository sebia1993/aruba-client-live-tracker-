"""Static checks prevent accidental publication of common local data and secrets."""
import ipaddress
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {".git", ".venv", "build", "dist", "artifacts", "__pycache__", ".pytest_cache", ".ruff_cache", "LICENSES"}
NETWORKS = [ipaddress.ip_network(value) for value in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24", "127.0.0.0/8")]
# These exact test-fixture values are software version / valid and invalid masks,
# not device addresses. The exception applies only to tests, never app/config/docs.
FIXTURE_NON_ADDRESSES = {"8.10.0.0", "255.255.255.0", "255.0.255.0"}


def allowed_public_value(candidate, *, fixture=False):
    if fixture and candidate in FIXTURE_NON_ADDRESSES:
        return True
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:  # Malformed input is intentional parser test data.
        return True
    return (address.is_unspecified or address.is_multicast or candidate == "255.255.255.255"
            or any(address in network for network in NETWORKS))


def public_files():
    for path in ROOT.rglob("*"):
        relative = path.relative_to(ROOT)
        if not any(part in EXCLUDED or part.endswith(".egg-info") for part in relative.parts) and path.is_file():
            yield path


def test_no_private_keys_or_access_tokens_in_public_text():
    patterns = [
        re.compile(r"-----BEGIN " + r"(?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        re.compile(r"gh[pousr]_" + r"[A-Za-z0-9]{30,}"),
        re.compile(r"github_pat_" + r"[A-Za-z0-9_]{30,}"),
    ]
    violations = []
    for path in public_files():
        if path.suffix not in {".py", ".md", ".toml", ".txt", ".json", ".yml", ".yaml", ".ps1"}:
            continue
        content = path.read_text(encoding="utf-8")
        if any(pattern.search(content) for pattern in patterns):
            violations.append(str(path.relative_to(ROOT)))
    assert not violations, f"Potential secrets in {violations}"


def test_public_example_ipv4_addresses_are_documentation_or_loopback():
    violations = []
    for path in public_files():
        if path.suffix not in {".py", ".md", ".json", ".yml", ".yaml"}:
            continue
        for candidate in re.findall(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])", path.read_text(encoding="utf-8")):
            if not allowed_public_value(candidate, fixture=path.relative_to(ROOT).parts[0] == "tests"):
                violations.append(f"{path.relative_to(ROOT)}: {candidate}")
    assert not violations, "Use RFC 5737 synthetic addresses: " + ", ".join(violations)


def test_fixture_version_exception_cannot_allow_general_device_addresses():
    assert allowed_public_value("8.10.0.0", fixture=True)
    assert not allowed_public_value("8.10.0.0", fixture=False)
    for octets in [(10, 9, 8, 7), (172, 16, 3, 4), (192, 168, 5, 6), (8, 8, 8, 8)]:
        assert not allowed_public_value(".".join(map(str, octets)), fixture=True)
    assert allowed_public_value("192.0.2.100")


def test_local_data_patterns_are_gitignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.db", "*.log", "settings.json", "known_hosts", "credentials", "local-data/"):
        assert pattern in ignore
