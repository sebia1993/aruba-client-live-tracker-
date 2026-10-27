"""Accelerated synthetic collector stability, including repeated MD changes."""
import gc
import tracemalloc
import weakref

from test_collector import MAC, MD, MM, FakeSSH, global_output

from aruba_client_live_tracker.collector import LiveCollector
from aruba_client_live_tracker.commands import parse_target
from aruba_client_live_tracker.models import Credentials, Device, Outcome


def test_2000_live_pipeline_polls_bound_memory_and_release_md_sessions(monkeypatch, tmp_path):
    class CountingSSH:
        instances = weakref.WeakSet()
        created = 0
        closed = 0
        switch = '192.0.2.20'
        failures = {}

        def __init__(self, device, *_):
            self.device = device
            self.is_closed = False
            self.instances.add(self)
            type(self).created += 1

        def run(self, command, **kwargs):
            if 'global-user-table' in command:
                return global_output().replace('192.0.2.20', self.switch)
            # Reuse the synthetic fixture producer without its growing command log.
            self.commands = []
            output = FakeSSH.run(self, command, **kwargs)
            self.commands.clear()
            return output

        def close(self):
            if not self.is_closed:
                self.is_closed = True
                type(self).closed += 1

    monkeypatch.setattr('aruba_client_live_tracker.collector.SSHSession', CountingSSH)
    second_md = Device('LAB-MD-B', '198.51.100.21', mappings=('192.0.2.21',))
    collector = LiveCollector([MM, MD, second_md], Credentials('synthetic', 'not-a-real-secret'), tmp_path/'known_hosts')
    tracemalloc.start()
    try:
        for step in range(2100):
            CountingSSH.switch = '192.0.2.20' if step % 2 else '192.0.2.21'
            result = collector.poll(parse_target(MAC))
            assert result.outcome == Outcome.OK
            assert len(collector._sessions) == 2
            assert len(CountingSSH.instances) == 2
            if step == 99:
                gc.collect()
                baseline = tracemalloc.get_traced_memory()[0]
        gc.collect()
        assert tracemalloc.get_traced_memory()[0] - baseline < 2_000_000
        assert len(collector._history_at) <= 1
        collector.close()
        gc.collect()
        assert not CountingSSH.instances
        assert CountingSSH.created == CountingSSH.closed
    finally:
        collector.close()
        tracemalloc.stop()
