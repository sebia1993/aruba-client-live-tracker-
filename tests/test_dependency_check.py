import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'check_dependencies.py'


def module():
    spec = importlib.util.spec_from_file_location('dependency_check', SCRIPT)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_pins_include_nested_files_and_markers(tmp_path):
    (tmp_path/'base.txt').write_text('example==1.2.3\n')
    path = tmp_path/'deps.txt'
    path.write_text('-r base.txt\nwindows-example==2.0; sys_platform == "win32"\n# ignored\n')
    assert module().read_pins(path) == [('example','1.2.3'),('windows-example','2.0')]


def test_advisories_are_not_silently_ignored():
    checker = module()
    def fetch(name, version):
        return {'vulnerabilities': [{'id': 'EXAMPLE-ADVISORY', 'fixed_in':['2.0']}]}
    rows = checker.audit([('example','1.0')], fetch=fetch)
    assert rows[0]['vulnerabilities'][0]['id'] == 'EXAMPLE-ADVISORY'
    with pytest.raises(OSError):
        checker.audit([('example','1.0')], fetch=lambda *_: (_ for _ in ()).throw(OSError('offline')))
