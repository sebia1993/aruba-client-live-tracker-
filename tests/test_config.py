import json

import pytest

from aruba_client_live_tracker.config import load_devices, save_devices
from aruba_client_live_tracker.models import Device


def test_settings_roundtrip_no_credentials(tmp_path):
    path = tmp_path / 'settings.json'
    devices = [Device('실습 MM', '192.0.2.10', 'MM_PRIMARY'), Device('실습 MD', '192.0.2.20', mappings=('192.0.2.21', 'LAB-MD'))]
    save_devices(path, devices)
    assert load_devices(path) == devices
    assert 'password' not in path.read_text()


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
