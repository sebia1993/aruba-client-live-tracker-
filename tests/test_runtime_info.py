"""Runtime identity stays useful without Git, the network, or operational data."""
import json
import sys


def test_source_fingerprint_tracks_source_changes_not_runtime_data(tmp_path):
    from aruba_client_live_tracker.runtime_info import source_fingerprint
    (tmp_path / '__init__.py').write_text('version = 1\n', encoding='utf-8')
    first = source_fingerprint(tmp_path)
    (tmp_path / 'settings.json').write_text('private runtime settings', encoding='utf-8')
    assert source_fingerprint(tmp_path) == first
    (tmp_path / '__init__.py').write_text('version = 2\n', encoding='utf-8')
    assert source_fingerprint(tmp_path) != first


def test_frozen_identity_uses_packaged_build_metadata(tmp_path, monkeypatch):
    from aruba_client_live_tracker import runtime_info
    metadata = {'source_sha256': 'a' * 64}
    (tmp_path / 'runtime-build.json').write_text(json.dumps(metadata), encoding='utf-8')
    monkeypatch.setattr(runtime_info, '__file__', str(tmp_path / 'runtime_info.py'))
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    info = runtime_info.runtime_identity()
    assert info['build_id'].endswith('a' * 12)
    assert info['mode'] == 'frozen'
    assert 'executable_path' not in info
    assert runtime_info.runtime_identity(include_path=True)['executable_path'] == sys.executable


def test_help_displays_build_and_parser_identity(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog, QTextEdit

    from aruba_client_live_tracker import __version__
    from aruba_client_live_tracker.ui import MainWindow
    window = MainWindow(data_path=tmp_path, demo=True)
    qtbot.addWidget(window)
    shown = []
    monkeypatch.setattr(QDialog, 'exec', lambda dialog: shown.extend(
        item.toPlainText() for item in dialog.findChildren(QTextEdit)))
    window.open_help()
    text = '\n'.join(shown)
    assert __version__ in text and '빌드 식별자' in text
    assert '수집기' in text and '장비 표 파서' in text and sys.executable in text
    window.close()
