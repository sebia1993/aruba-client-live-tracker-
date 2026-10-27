import json

import pytest

from aruba_client_live_tracker.config import load_devices, save_devices
from aruba_client_live_tracker.models import Device


def test_settings_roundtrip_no_credentials(tmp_path):
    path = tmp_path / 'settings.json'
    devices = [Device('실습 MM', '192.0.2.10', 'MM_PRIMARY'), Device('실습 MD', '192.0.2.20', mappings=('192.0.2.21', 'LAB-MD'))]
    save_devices(path, devices)
    assert load_devices(path) == devices
    assert 'password' not in path.read_text(encoding="utf-8")


@pytest.mark.parametrize('device', [Device('x','host;reboot'), Device('x','192.0.2.1',port=0), Device('x','192.0.2.1',kind='bad'), Device('x','192.0.2.1',mappings=('bad\nshow x',))])
def test_reject_bad_settings(tmp_path, device):
    with pytest.raises(ValueError):
        save_devices(tmp_path / 'settings.json', [device])


def test_reject_secret_and_duplicate_primary(tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps({'devices': [], 'password': 'example-placeholder'}))
    with pytest.raises(ValueError):
        load_devices(path)
    with pytest.raises(ValueError):
        save_devices(path, [Device('a','192.0.2.1','MM_PRIMARY'), Device('b','192.0.2.2','MM_PRIMARY')])


def test_v1_load_preserves_manual_defaults(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'version': 1, 'devices': [{'name': 'LAB', 'host': '192.0.2.1'}]}))
    assert load_devices(path) == [Device('LAB', '192.0.2.1')]


def test_v2_identity_roundtrip(tmp_path):
    from aruba_client_live_tracker.models import DeviceIdentity
    path = tmp_path / 'settings.json'
    devices = [Device('LAB', '192.0.2.1', 'AUTO', identity=DeviceIdentity(
        hostname='LAB-MM', switch_ip='192.0.2.10', reported_role='master',
        model='ArubaMM-VA', version='8.10.0.0', observed_at='2026-10-27T00:00:00+00:00',
        source='show switchinfo'), origin='discovered')]
    save_devices(path, devices)
    assert json.loads(path.read_text())['version'] == 2
    assert load_devices(path) == devices


@pytest.mark.parametrize('extra', [
    {'origin': 'unknown'}, {'identity': {'password': 'synthetic-secret'}},
    {'identity': {'switch_ip': 'bad-ip'}}, {'identity': {'hostname': 'bad\nname'}},
    {'identity': {'version': 'x' * 257}}, {'identity': 'bad'},
    {'username': 'synthetic-user'}, {'kind': 'AUTO', 'enabled': 1},
])
def test_v2_metadata_validation(tmp_path, extra):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'version': 2, 'devices': [{'name': 'LAB', 'host': '192.0.2.1', **extra}]}))
    with pytest.raises(ValueError):
        load_devices(path)


def test_multiple_auto_entries_allowed(tmp_path):
    devices = [Device('a', '192.0.2.1', 'AUTO'), Device('b', '192.0.2.2', 'AUTO')]
    save_devices(tmp_path / 'settings.json', devices)
    assert load_devices(tmp_path / 'settings.json') == devices


@pytest.mark.parametrize('mappings', ['LAB-MD', {'LAB-MD': True}, None, 1])
def test_json_mappings_must_be_an_array(tmp_path, mappings):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'version': 2, 'devices': [
        {'name': 'LAB', 'host': '192.0.2.1', 'mappings': mappings},
    ]}), encoding='utf-8')
    with pytest.raises(ValueError):
        load_devices(path)


@pytest.mark.parametrize('original', [
    b'{invalid', b'\xff\xfeinvalid',
    b'{"version": 999, "devices": [{"name": "LAB", "host": "192.0.2.1"}]}',
])
def test_recovery_save_preserves_exact_original_bytes(tmp_path, original):
    path = tmp_path / 'settings.json'
    path.write_bytes(original)
    previous = tmp_path / 'settings.json.recovery-previous.bak'
    previous.write_bytes(b'previous recovery')
    backup = save_devices(path, [Device('LAB', '192.0.2.1')])
    assert backup is not None and backup.parent == tmp_path
    assert backup.name.startswith('settings.json.recovery-') and backup.suffix == '.bak'
    assert backup.read_bytes() == original
    assert previous.read_bytes() == b'previous recovery'
    assert load_devices(path) == [Device('LAB', '192.0.2.1')]


def test_valid_settings_save_needs_no_recovery_backup(tmp_path):
    path = tmp_path / 'settings.json'
    save_devices(path, [Device('LAB', '192.0.2.1')])
    assert save_devices(path, [Device('LAB', '192.0.2.2')]) is None
    assert not list(tmp_path.glob('settings.json.recovery-*.bak'))
    assert load_devices(path)[0].host == '192.0.2.2'


def test_failed_recovery_backup_cannot_replace_original(tmp_path, monkeypatch):
    from aruba_client_live_tracker import config
    path = tmp_path / 'settings.json'
    original = b'{invalid but recoverable content'
    path.write_bytes(original)
    mkstemp = config.tempfile.mkstemp

    def deny_backup(*args, **kwargs):
        if kwargs.get('prefix', '').startswith('settings.json.recovery-'):
            raise PermissionError('synthetic backup failure')
        return mkstemp(*args, **kwargs)

    monkeypatch.setattr(config.tempfile, 'mkstemp', deny_backup)
    with pytest.raises(OSError):
        save_devices(path, [])
    assert path.read_bytes() == original
    assert not list(tmp_path.glob('settings.json.recovery-*.bak'))
