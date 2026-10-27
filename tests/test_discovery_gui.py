import os
import threading
from dataclasses import replace
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog

from aruba_client_live_tracker.models import Credentials, Device, DeviceIdentity, Diagnostic
from aruba_client_live_tracker.ui import DeviceDialog, MainWindow, SettingsDialog
from aruba_client_live_tracker.ui_discovery import DiscoveryDialog


def result(devices, diagnostics=()):
    return SimpleNamespace(devices=devices, diagnostics=list(diagnostics), collected_at='2026-10-27T00:00:00+00:00')


class FakeDiscovery:
    instances = []
    def __init__(self, credentials, known_hosts):
        self.credentials = credentials
        self.probed = []
        self.closed = False
        self.instances.append(self)
    def discover(self, seed, cancel=None):
        assert threading.current_thread() is not threading.main_thread()
        return result([replace(seed, kind='MM_PRIMARY', origin='discovered'),
                       Device('WLC-01', '192.0.2.11', 'AUTO', origin='discovered'),
                       Device('WLC-02', '192.0.2.12', 'AUTO', origin='discovered')])
    def probe(self, devices, cancel=None):
        assert threading.current_thread() is not threading.main_thread()
        self.probed = devices
        return result([replace(d, kind='MD' if d.kind == 'AUTO' else d.kind,
                               identity=DeviceIdentity(model='Aruba7210', version='8.10.0.0', reported_role='MD' if d.kind == 'AUTO' else 'conductor')) for d in devices])
    def close(self):
        self.closed = True


def test_registration_defaults_auto_and_preserves_identity(qtbot):
    dialog = DeviceDialog()
    qtbot.addWidget(dialog)
    assert dialog.kind_edit.currentData() == 'AUTO'
    original = Device('기존', '192.0.2.1', 'MD', mappings=('switch-1',),
                      identity=DeviceIdentity(model='7210'), origin='discovered')
    edit = DeviceDialog(device=original)
    qtbot.addWidget(edit)
    assert edit.device() == original


def test_discovery_selects_seed_then_probes_only_selected_and_merges(qtbot, tmp_path):
    seed = Device('MM', '192.0.2.1', 'AUTO')
    dialog = DiscoveryDialog(seed, [], Credentials('synthetic', 'synthetic'), tmp_path / 'known_hosts',
                             service_factory=FakeDiscovery)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(lambda: dialog.grid.rowCount() == 3)
    assert dialog.grid.item(0, 0).checkState() == Qt.CheckState.Checked
    assert dialog.grid.item(1, 0).checkState() == Qt.CheckState.Unchecked
    dialog.grid.item(1, 0).setCheckState(Qt.CheckState.Checked)
    dialog.probe_selected()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    assert [d.host for d in FakeDiscovery.instances[-1].probed] == ['192.0.2.1', '192.0.2.11']
    assert dialog.grid.item(1, 4).text() == 'Aruba7210'
    dialog.register_selected()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(dialog.devices) == 2
    assert all(d.kind != 'AUTO' for d in dialog.devices)


def test_discovery_cancel_ignores_late_worker_without_gui_wait(qtbot, tmp_path):
    entered, release = threading.Event(), threading.Event()
    class Slow(FakeDiscovery):
        def discover(self, seed, cancel=None):
            entered.set()
            release.wait(2)
            return result([replace(seed, kind='MM_PRIMARY')])
    dialog = DiscoveryDialog(Device('MM', '192.0.2.1', 'AUTO'), [], Credentials('x', 'y'),
                             tmp_path / 'known_hosts', service_factory=Slow)
    qtbot.addWidget(dialog)
    dialog.show()
    qtbot.waitUntil(entered.is_set)
    dialog.reject()
    assert dialog.result() == QDialog.DialogCode.Rejected
    release.set()
    qtbot.wait(100)
    assert dialog.devices == [] and dialog.grid.rowCount() == 0
    assert Slow.instances[-1].closed


def test_discovery_conflict_keeps_manual_mapping_and_shows_diagnostic(qtbot, tmp_path):
    original = Device('기존 MM', '192.0.2.1', 'MM_STANDBY', mappings=('manual-map',))
    dialog = DiscoveryDialog(Device('MM', '192.0.2.1', 'AUTO'), [original], Credentials('x', 'y'),
                             tmp_path / 'known_hosts', service_factory=FakeDiscovery)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.grid.rowCount() == 3)
    dialog.probe_selected()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    dialog.register_selected()
    assert dialog.devices[0].name == '기존 MM'
    assert dialog.devices[0].kind == 'MM_STANDBY'
    assert 'CONFIG_CONFLICT' in dialog.details.toPlainText()
    assert dialog.diagnostics[-1].message in dialog.details.toPlainText()
    assert '보존했습니다' in dialog.details.toPlainText()
    assert dialog.devices[0].mappings == ('manual-map',)


def test_common_credentials_reused_after_pool_idle_and_explicit_change(qtbot, tmp_path, monkeypatch):
    window = MainWindow(data_path=tmp_path, demo=False)
    qtbot.addWidget(window)
    prompts = []
    credentials = Credentials('synthetic', 'synthetic')
    monkeypatch.setattr(window, '_credentials', lambda: prompts.append(True) or credentials)
    assert window._shared_credentials() is credentials
    assert window._shared_credentials() is credentials
    assert prompts == [True]
    window._tick()
    assert window._credentials_value is credentials
    window.change_account()
    assert window._credentials_value is None
    assert window._shared_credentials() is credentials
    assert prompts == [True, True]
    window.close()
    assert window._credentials_value is None


def test_auto_devices_not_passed_to_monitor_collector(qtbot, tmp_path, monkeypatch):
    from aruba_client_live_tracker import collector
    window = MainWindow(data_path=tmp_path, demo=False)
    qtbot.addWidget(window)
    window.devices = [Device('MM', '192.0.2.1', 'MM_PRIMARY'), Device('미확정', '192.0.2.11', 'AUTO')]
    window.pool = SimpleNamespace(for_owner=lambda owner: 'runner', close=lambda: None)
    calls = []
    monkeypatch.setattr(collector, 'LiveCollector', lambda devices, *args, **kwargs: calls.append(devices))
    window._collector_factory(SimpleNamespace(id='one'))
    assert [d.name for d in calls[0]] == ['MM']
    window.close()


def test_diagnostic_stage_and_message_are_visible(qtbot, tmp_path, monkeypatch):
    from aruba_client_live_tracker.models import Outcome, PollResult
    window = MainWindow(data_path=tmp_path)
    qtbot.addWidget(window)
    diagnostic = Diagnostic('md_mapping', 'MD_MAPPING_MISSING', '담당 WLC 주소에 맞는 매핑이 없습니다.', 'WLC-01', '192.0.2.11:22')
    window._consume_result(PollResult(Outcome.ERROR, diagnostics=[diagnostic]))
    assert '담당 WLC 매핑' in window.status_note.text()
    assert diagnostic.message in window.status_note.text()
    texts = []
    def capture(dialog):
        from PySide6.QtWidgets import QTextEdit
        texts.extend(text.toPlainText() for text in dialog.findChildren(QTextEdit))
        return QDialog.DialogCode.Rejected
    monkeypatch.setattr(QDialog, 'exec', capture)
    window.open_diagnostics()
    assert 'MD_MAPPING_MISSING' in '\n'.join(texts)
    assert '192.0.2.11:22' in '\n'.join(texts)
    window.close()


def test_settings_seed_default_port_and_save_preserves_auto_and_mapping(qtbot, tmp_path):
    from aruba_client_live_tracker.config import load_devices
    original = Device('수동 WLC', '192.0.2.11', 'MD', port=2222, mappings=('switch-11',))
    dialog = SettingsDialog([original, Device('미확정', '192.0.2.12', 'AUTO')], tmp_path / 'settings.json')
    qtbot.addWidget(dialog)
    assert dialog.seed_port.value() == 22
    assert dialog.discover_button.text() == 'MM에서 장비 찾기'
    assert '판별 불가' in dialog.grid.item(1, 3).text()
    dialog.save()
    assert load_devices(tmp_path / 'settings.json') == dialog.devices
    assert dialog.devices[0] == original


def test_edited_endpoint_discards_discovered_identity_and_role(qtbot):
    original = Device('MM', '192.0.2.1', 'MM_PRIMARY', identity=DeviceIdentity(model='MM-VA'), origin='discovered')
    dialog = DeviceDialog(device=original)
    qtbot.addWidget(dialog)
    dialog.host_edit.setText('192.0.2.11')
    assert dialog.device().identity is None
    assert dialog.device().kind == 'AUTO'


def test_edited_discovered_endpoint_removes_generated_aliases_only(qtbot):
    original = Device('WLC', '192.0.2.11', 'MD', origin='discovered',
                      identity=DeviceIdentity(switch_ip='2001:db8::11', hostname='old-wlc'),
                      mappings=('2001:0db8:0:0:0:0:0:11', 'old-wlc', 'operator-alias'))
    dialog = DeviceDialog(device=original)
    qtbot.addWidget(dialog)
    dialog.host_edit.setText('192.0.2.12')
    edited = dialog.device()
    assert edited.mappings == ('operator-alias',)
    assert edited.identity is None
    assert edited.kind == 'AUTO'


def test_edited_discovered_port_removes_old_generated_aliases(qtbot):
    original = Device('WLC', '192.0.2.11', 'MD', origin='discovered',
                      identity=DeviceIdentity(switch_ip='192.0.2.11', hostname='old-wlc'),
                      mappings=('192.0.2.11', 'old-wlc', 'operator-alias'))
    dialog = DeviceDialog(device=original)
    qtbot.addWidget(dialog)
    dialog.port_edit.setValue(2222)
    assert dialog.device().mappings == ('operator-alias',)


def test_endpoint_edit_keeps_explicit_mapping_edits(qtbot):
    original = Device('WLC', '192.0.2.11', 'MD', origin='discovered',
                      identity=DeviceIdentity(switch_ip='192.0.2.11', hostname='old-wlc'),
                      mappings=('192.0.2.11', 'old-wlc'))
    dialog = DeviceDialog(device=original)
    qtbot.addWidget(dialog)
    dialog.host_edit.setText('192.0.2.12')
    dialog.mappings_edit.setText('old-wlc, operator-alias')
    assert dialog.device().mappings == ('old-wlc', 'operator-alias')


def test_endpoint_edit_preserves_manual_device_mappings(qtbot):
    original = Device('WLC', '192.0.2.11', 'MD', origin='manual',
                      identity=DeviceIdentity(switch_ip='192.0.2.11', hostname='old-wlc'),
                      mappings=('192.0.2.11', 'old-wlc'))
    dialog = DeviceDialog(device=original)
    qtbot.addWidget(dialog)
    dialog.host_edit.setText('192.0.2.12')
    assert dialog.device().mappings == ('192.0.2.11', 'old-wlc')


def test_endpoint_edit_reprobe_save_reload_uses_new_identity_aliases(qtbot, tmp_path):
    from aruba_client_live_tracker.config import load_devices

    original = Device('WLC', '192.0.2.11', 'MD', origin='discovered',
                      identity=DeviceIdentity(switch_ip='192.0.2.11', hostname='old-wlc'),
                      mappings=('192.0.2.11', 'old-wlc', 'operator-alias'))
    editor = DeviceDialog(device=original)
    qtbot.addWidget(editor)
    editor.host_edit.setText('192.0.2.12')
    edited = editor.device()

    class FreshIdentity(FakeDiscovery):
        def probe(self, devices, cancel=None):
            return result([replace(device, kind='MD',
                                   identity=DeviceIdentity(switch_ip='192.0.2.12', hostname='new-wlc',
                                                           reported_role='MD'))
                           for device in devices])

    probe = DiscoveryDialog(edited, [edited], Credentials('x', 'y'), tmp_path / 'known_hosts',
                            service_factory=FreshIdentity, initial_devices=[edited])
    qtbot.addWidget(probe)
    qtbot.waitUntil(lambda: probe.register_button.isEnabled())
    probe.register_selected()
    settings = SettingsDialog(probe.devices, tmp_path / 'settings.json')
    qtbot.addWidget(settings)
    settings.save()
    restored = load_devices(settings.settings_path)
    assert restored[0].kind == 'MD'
    assert restored[0].mappings == ('operator-alias', '192.0.2.12', 'new-wlc')
    assert restored[0].identity.hostname == 'new-wlc'


def test_settings_recovery_save_shows_backup_path(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from aruba_client_live_tracker.config import load_devices
    path = tmp_path / 'settings.json'
    original = b'{broken settings'
    path.write_bytes(original)
    dialog = SettingsDialog([Device('WLC', '192.0.2.11', 'MD')], path)
    qtbot.addWidget(dialog)
    messages = []
    monkeypatch.setattr(QMessageBox, 'information', lambda _parent, title, body: messages.append((title, body)))
    dialog.save()
    backups = list(tmp_path.glob('settings.json.recovery-*.bak'))
    assert len(backups) == 1 and backups[0].read_bytes() == original
    assert load_devices(path) == dialog.devices
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert len(messages) == 1
    assert '백업' in messages[0][1] and str(backups[0]) in messages[0][1]


def test_settings_recovery_backup_failure_preserves_original_and_stays_open(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from aruba_client_live_tracker import config
    path = tmp_path / 'settings.json'
    original = b'{broken settings'
    path.write_bytes(original)
    dialog = SettingsDialog([Device('WLC', '192.0.2.11', 'MD')], path)
    qtbot.addWidget(dialog)
    messages = []
    monkeypatch.setattr(QMessageBox, 'warning', lambda _parent, title, body: messages.append((title, body)))
    def fail_copy(*args):
        raise OSError('backup write failed')
    monkeypatch.setattr(config.shutil, 'copyfileobj', fail_copy)
    dialog.save()
    assert path.read_bytes() == original
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert len(messages) == 1
    assert list(tmp_path.glob('settings.json.recovery-*.bak')) == []


def test_direct_probe_promotes_manual_auto_and_preserves_mapping(qtbot, tmp_path):
    original = Device('개별 장비', '192.0.2.11', 'AUTO', mappings=('manual-11',))
    dialog = DiscoveryDialog(original, [original], Credentials('x', 'y'), tmp_path / 'known_hosts',
                             service_factory=FakeDiscovery, initial_devices=[original])
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    dialog.register_selected()
    assert dialog.devices[0].kind == 'MD'
    assert dialog.devices[0].mappings == ('manual-11',)
    assert dialog.devices[0].name == '개별 장비'


def test_select_all_and_changed_selection_require_new_probe(qtbot, tmp_path):
    dialog = DiscoveryDialog(Device('MM', '192.0.2.1', 'AUTO'), [], Credentials('x', 'y'),
                             tmp_path / 'known_hosts', service_factory=FakeDiscovery)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.grid.rowCount() == 3)
    dialog.all_selected.setChecked(True)
    assert len(dialog.selected_devices()) == 3
    dialog.probe_selected()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    dialog.grid.item(1, 0).setCheckState(Qt.CheckState.Unchecked)
    assert not dialog.register_button.isEnabled()
    dialog.reject()


def test_settings_discovery_and_tracking_share_one_credential_prompt(qtbot, tmp_path, monkeypatch):
    from aruba_client_live_tracker import ui_discovery
    window = MainWindow(data_path=tmp_path, demo=False)
    qtbot.addWidget(window)
    prompts, received = [], []
    credentials = Credentials('synthetic', 'synthetic')
    monkeypatch.setattr(window, '_credentials', lambda: prompts.append(True) or credentials)
    class AcceptedDiscovery:
        diagnostics = []
        devices = [Device('MM', '192.0.2.1', 'MM_PRIMARY')]
        def __init__(self, seed, existing, credentials, known_hosts, parent=None):
            received.append(credentials)
        def exec(self):
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(ui_discovery, 'DiscoveryDialog', AcceptedDiscovery)
    settings = SettingsDialog([], tmp_path / 'settings.json', credentials_provider=window._shared_credentials)
    qtbot.addWidget(settings)
    settings.seed_name.setText('MM')
    settings.seed_host.setText('192.0.2.1')
    settings.discover_devices()
    assert settings.devices == AcceptedDiscovery.devices
    settings.discover_devices()
    window.devices = settings.devices
    assert window._ensure_run()
    assert window.pool.credentials is credentials
    assert received == [credentials, credentials] and prompts == [True]
    window.close()


def test_account_cannot_change_while_monitoring(qtbot, tmp_path):
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    credentials = Credentials('synthetic', 'synthetic')
    window._credentials_value = credentials
    window.start_tracking()
    assert not window.account_button.isEnabled()
    window.change_account()
    assert window._credentials_value is credentials
    window.stop_all()
    qtbot.waitUntil(lambda: not window.coordinator.busy)
    window.close()


def test_manual_edit_marks_discovered_settings_as_manual(qtbot):
    original = Device('WLC', '192.0.2.11', 'MD', origin='discovered', identity=DeviceIdentity(model='7210'))
    dialog = DeviceDialog(device=original)
    qtbot.addWidget(dialog)
    dialog.enabled_edit.setChecked(False)
    assert dialog.device().origin == 'manual'
    assert not dialog.device().enabled
    assert dialog.device().identity == original.identity


def test_credential_dialog_clears_secret_widgets_before_return(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    window = MainWindow(data_path=tmp_path, demo=False)
    qtbot.addWidget(window)
    edits = []
    def accepted(dialog):
        fields = dialog.findChildren(QLineEdit)
        fields[0].setText('synthetic-user')
        fields[1].setText('synthetic-secret')
        edits.extend(fields)
        return QDialog.DialogCode.Accepted
    monkeypatch.setattr(QDialog, 'exec', accepted)
    credentials = window._credentials()
    assert credentials == Credentials('synthetic-user', 'synthetic-secret')
    assert all(edit.text() == '' for edit in edits)
    window.close()


def test_settings_501_devices_preserve_edit_probe_delete_row_indices(qtbot, tmp_path, monkeypatch):
    from aruba_client_live_tracker import ui, ui_discovery
    devices = [Device(f'WLC-{i:03d}', f'192.0.{i // 250}.{i % 250 + 1}', 'MD') for i in range(501)]
    dialog = SettingsDialog(devices, tmp_path / 'settings.json',
                              credentials_provider=lambda: Credentials('x', 'y'))
    qtbot.addWidget(dialog)
    assert dialog.grid.rowCount() == 501
    assert dialog.grid.item(0, 0).text() == devices[0].name
    assert dialog.grid.item(500, 0).text() == devices[500].name
    class EditedDevice:
        def __init__(self, parent, device):
            assert device is devices[0]
            self.original = device
        def exec(self):
            return QDialog.DialogCode.Accepted
        def device(self):
            return replace(self.original, name='첫 장비 수정')
    monkeypatch.setattr(ui, 'DeviceDialog', EditedDevice)
    dialog.grid.selectRow(0)
    dialog.edit_device()
    assert dialog.devices[0].name == '첫 장비 수정'
    assert dialog.grid.item(0, 0).text() == '첫 장비 수정'
    probed = []
    class ProbeDialog:
        def __init__(self, seed, existing, credentials, known_hosts, parent, initial_devices):
            probed.extend(initial_devices)
            assert seed is devices[500]
        def exec(self):
            return QDialog.DialogCode.Rejected
    monkeypatch.setattr(ui_discovery, 'DiscoveryDialog', ProbeDialog)
    dialog.grid.selectRow(500)
    dialog.probe_device()
    assert probed == [devices[500]]
    dialog.delete_device()
    assert dialog.grid.rowCount() == 500
    assert dialog.devices[-1] is devices[499]
    assert dialog.devices[0].name == '첫 장비 수정'


def test_discovery_501_devices_preserve_seed_and_last_selection(qtbot, tmp_path):
    seed = Device('MM', '192.0.2.1', 'AUTO')
    class ManyDiscovery(FakeDiscovery):
        def discover(self, seed, cancel=None):
            return result([replace(seed, kind='MM_PRIMARY', origin='discovered')] + [
                Device(f'WLC-{i:03d}', f'198.51.{i // 250}.{i % 250 + 1}', 'AUTO', origin='discovered')
                for i in range(500)])
    dialog = DiscoveryDialog(seed, [], Credentials('x', 'y'), tmp_path / 'known_hosts',
                             service_factory=ManyDiscovery)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.grid.rowCount() > 0)
    assert dialog.grid.rowCount() == 501
    assert dialog.grid.item(0, 1).text() == 'MM'
    assert dialog.grid.item(500, 1).text() == 'WLC-499'
    dialog.grid.item(500, 0).setCheckState(Qt.CheckState.Checked)
    assert [device.name for device in dialog.selected_devices()] == ['MM', 'WLC-499']
    dialog.probe_selected()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    assert [device.name for device in ManyDiscovery.instances[-1].probed] == ['MM', 'WLC-499']
    dialog.register_selected()
    assert [device.name for device in dialog.devices] == ['MM', 'WLC-499']


def test_initial_dialog_sizes_fit_small_available_screen(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QPoint, QRect
    from PySide6.QtGui import QScreen
    from PySide6.QtWidgets import QPushButton
    monkeypatch.setattr(QScreen, 'availableGeometry', lambda self: QRect(0, 0, 910, 512))
    settings = SettingsDialog([], tmp_path / 'settings.json')
    discovery = DiscoveryDialog(Device('가상 MM', '192.0.2.1', 'AUTO'), [], Credentials('x', 'y'),
                                tmp_path / 'known_hosts', service_factory=FakeDiscovery)
    for dialog in (settings, discovery):
        qtbot.addWidget(dialog)
        dialog.show()
    qtbot.waitUntil(lambda: discovery.grid.rowCount() == 3)
    for dialog in (settings, discovery):
        assert dialog.width() <= 910 - 32
        assert dialog.height() <= 512 - 64
        for button in dialog.findChildren(QPushButton):
            top_left = button.mapTo(dialog, QPoint(0, 0))
            assert dialog.rect().contains(QRect(top_left, button.size()))
            assert top_left.y() + button.height() <= 512 - 64
        dialog.reject()


def test_initial_dialog_defaults_preserved_on_large_screen(qtbot, tmp_path, monkeypatch):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QScreen
    monkeypatch.setattr(QScreen, 'availableGeometry', lambda self: QRect(0, 0, 1920, 1080))
    settings = SettingsDialog([], tmp_path / 'settings.json')
    discovery = DiscoveryDialog(Device('가상 MM', '192.0.2.1', 'AUTO'), [], Credentials('x', 'y'),
                                tmp_path / 'known_hosts', service_factory=FakeDiscovery)
    qtbot.addWidget(settings)
    qtbot.addWidget(discovery)
    assert (settings.width(), settings.height()) == (1080, 640)
    assert (discovery.width(), discovery.height()) == (1120, 650)
    settings.reject()
    discovery.reject()


def test_failed_list_lookup_remains_previous_operation_after_successful_probe(qtbot, tmp_path):
    lookup_error = Diagnostic('discovery', 'SWITCH_TABLE_PARSE_FAILED', 'MM 목록 형식을 해석하지 못했습니다.',
                              command='show switches')
    class FailedLookup(FakeDiscovery):
        def discover(self, seed, cancel=None):
            return result([replace(seed, kind='MM_PRIMARY', origin='discovered')], [lookup_error])
    dialog = DiscoveryDialog(Device('MM', '192.0.2.1', 'AUTO'), [], Credentials('x', 'y'),
                             tmp_path / 'known_hosts', service_factory=FailedLookup)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.grid.rowCount() == 1)
    assert 'MM 목록 조회' in dialog.notice.text() and '오류 1건' in dialog.notice.text()
    assert '발견 1대' not in dialog.notice.text()
    dialog.probe_selected()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    text = dialog.details.toPlainText()
    assert '현재 작업 · 선택 장비 검사 1회 · 완료 · 진단 없음' in text
    assert '이전 작업 · MM 목록 조회 · 완료 · 오류 1건' in text
    assert text.index('이전 작업 · MM 목록 조회') < text.index('SWITCH_TABLE_PARSE_FAILED')
    assert lookup_error.message in text
    assert '이전 MM 목록 조회 오류' in dialog.notice.text()
    assert dialog.diagnostics == [lookup_error]
    dialog.reject()


def test_failed_probe_is_current_operation_and_keeps_lookup_error(qtbot, tmp_path):
    lookup_error = Diagnostic('discovery', 'SWITCH_TABLE_PARSE_FAILED', 'MM 목록 형식을 해석하지 못했습니다.')
    class FailedProbe(FakeDiscovery):
        def discover(self, seed, cancel=None):
            return result([replace(seed, kind='MM_PRIMARY')], [lookup_error])
        def probe(self, devices, cancel=None):
            raise RuntimeError('raw exception must not be exposed')
    dialog = DiscoveryDialog(Device('MM', '192.0.2.1', 'AUTO'), [], Credentials('x', 'y'),
                             tmp_path / 'known_hosts', service_factory=FailedProbe)
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.grid.rowCount() == 1)
    dialog.probe_selected()
    qtbot.waitUntil(lambda: not dialog._busy)
    text = dialog.details.toPlainText()
    assert '현재 작업 · 선택 장비 검사 1회 · 실패' in text
    assert '이전 작업 · MM 목록 조회 · 완료 · 오류 1건' in text
    assert 'DISCOVERY_FAILED' in text and 'SWITCH_TABLE_PARSE_FAILED' in text
    assert '선택 장비 검사 1회 실패' in dialog.notice.text()
    assert 'raw exception' not in text
    assert not dialog.register_button.isEnabled()
    assert dialog.diagnostics[0] is lookup_error
    assert len(dialog.diagnostics) == 2
    dialog.reject()


def test_repeated_probe_history_distinguishes_results_and_in_flight_operation(qtbot, tmp_path):
    entered, release = threading.Event(), threading.Event()
    auth_error = Diagnostic('auth', 'AUTH_FAILED', 'SSH 인증에 실패했습니다.')
    class RepeatedProbe(FakeDiscovery):
        calls = 0
        def probe(self, devices, cancel=None):
            type(self).calls += 1
            if self.calls == 1:
                return result(devices, [auth_error])
            if self.calls == 3:
                entered.set()
                release.wait(2)
            return result(devices)
    device = Device('MM', '192.0.2.1', 'MM_PRIMARY')
    dialog = DiscoveryDialog(device, [], Credentials('x', 'y'), tmp_path / 'known_hosts',
                             service_factory=RepeatedProbe, initial_devices=[device])
    qtbot.addWidget(dialog)
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    assert '현재 작업 · 선택 장비 검사 1회 · 완료 · 오류 1건' in dialog.details.toPlainText()
    dialog.probe_selected()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    text = dialog.details.toPlainText()
    assert '현재 작업 · 선택 장비 검사 2회 · 완료 · 진단 없음' in text
    assert '이전 작업 · 선택 장비 검사 1회 · 완료 · 오류 1건' in text
    assert 'MM 목록 조회' not in text
    dialog.probe_selected()
    qtbot.waitUntil(entered.is_set)
    text = dialog.details.toPlainText()
    assert '현재 작업 · 선택 장비 검사 3회 · 진행 중' in text
    assert '이전 작업 · 선택 장비 검사 2회 · 완료 · 진단 없음' in text
    assert not dialog.register_button.isEnabled()
    release.set()
    qtbot.waitUntil(lambda: dialog.register_button.isEnabled())
    text = dialog.details.toPlainText()
    assert text.count('현재 작업') == 1 and text.count('이전 작업') == 2
    assert '현재 작업 · 선택 장비 검사 3회 · 완료 · 진단 없음' in text
    assert 'AUTH_FAILED' in text
    assert dialog.diagnostics == [auth_error]
    dialog.reject()
