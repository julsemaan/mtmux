import unittest
from unittest.mock import Mock, patch

from mtmux.discovery import (
    RemotePoller,
    RemoteSnapshot,
    _bell_sessions,
    _clean_env,
    _parse_remote_snapshot,
    bell_targets,
    local_bell_sessions,
    remote_bell_sessions,
)


class DiscoveryBellTest(unittest.TestCase):
    def test_clean_env_removes_current_tmux_socket(self):
        with patch.dict("mtmux.discovery.os.environ", {"TMUX": "/tmp/tmux,1,0", "PATH": "x"}, clear=True):
            self.assertEqual(_clean_env(), {"PATH": "x"})

    def test_bell_sessions_parses_window_bell_flags(self):
        self.assertEqual(_bell_sessions("work:1\nwork:0\nmtmux:cockpit:1\nbad name:1\nchat:1"), {"work", "chat"})

    def test_local_bell_sessions_only_lists_windows(self):
        run = Mock(return_value=Mock(returncode=0, stdout="work:1:!\nidle:0:-\n"))

        with patch("mtmux.discovery.subprocess.run", run):
            self.assertEqual(local_bell_sessions(), {"work"})

        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["tmux", "list-windows", "-a"])
        self.assertNotIn("set-option", command)
        self.assertNotIn("set-window-option", command)
        run.assert_called_once()

    def test_remote_bell_sessions_only_lists_windows(self):
        run = Mock(return_value=Mock(returncode=0, stdout="work:0:!\nchat:1:-\nidle:0:-\n"))

        with patch("mtmux.discovery.subprocess.run", run):
            self.assertEqual(remote_bell_sessions("dev"), {"work", "chat"})

        remote_command = run.call_args.args[0][-1]
        self.assertIn("tmux list-windows", remote_command)
        self.assertNotIn("set-option", remote_command)
        self.assertNotIn("set-window-option", remote_command)
        run.assert_called_once()

    def test_bell_targets_includes_local_and_remote_sessions(self):
        def run(cmd, **kwargs):
            class Proc:
                returncode = 0
                stdout = "work:1:!\nidle:0:-\n"

            return Proc()

        with (
            patch("mtmux.discovery.subprocess.run", side_effect=run),
            patch("mtmux.discovery.load_hosts", return_value=["dev"]),
        ):
            self.assertEqual(bell_targets(), {"local:work", "ssh:dev:work"})



class RemoteSnapshotTest(unittest.TestCase):
    def test_combined_output_deduplicates_valid_sessions_and_collects_bells(self):
        snapshot = _parse_remote_snapshot(
            "work:0:-\nwork:1:-\nchat:!:-\nbad name:1:!\nmtmux:1:!\n"
        )

        self.assertEqual(snapshot, RemoteSnapshot(True, ("work", "chat"), frozenset({"work", "chat"})))

    def test_empty_output_is_available(self):
        self.assertEqual(_parse_remote_snapshot(""), RemoteSnapshot(True, (), frozenset()))

    def test_malformed_lines_are_ignored(self):
        self.assertEqual(_parse_remote_snapshot("broken\n:1:!\n"), RemoteSnapshot(True, (), frozenset()))


class FakeProcess:
    def __init__(self, returncode=None, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.terminated = False
        self.communicated = False

    def poll(self):
        return self.returncode

    def communicate(self):
        self.communicated = True
        return self.stdout, ""

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self):
        return self.returncode


class RemotePollerTest(unittest.TestCase):
    def test_pending_process_does_not_duplicate_or_block(self):
        process = FakeProcess()
        popen = Mock(return_value=process)
        poller = RemotePoller(["dev"], popen=popen, clock=Mock(return_value=0))

        self.assertFalse(poller.tick())
        poller.refresh()
        self.assertFalse(poller.tick())
        self.assertEqual(popen.call_count, 1)
        self.assertIsNone(poller.snapshots["dev"])

    def test_completed_and_failed_processes_update_snapshots(self):
        healthy = FakeProcess(0, "work:1:!\n")
        failed = FakeProcess(255)
        poller = RemotePoller(["dev", "off"], popen=Mock(side_effect=[healthy, failed]), clock=Mock(return_value=0))

        self.assertTrue(poller.tick())
        self.assertEqual(poller.snapshots["dev"], RemoteSnapshot(True, ("work",), frozenset({"work"})))
        self.assertEqual(poller.snapshots["off"], RemoteSnapshot(False, (), frozenset()))
        self.assertTrue(healthy.communicated)

    def test_timeout_isolated_from_completed_host(self):
        clock = Mock(side_effect=[0, 11])
        slow = FakeProcess()
        healthy = FakeProcess(0, "work:0:-\n")
        poller = RemotePoller(["slow", "dev"], popen=Mock(side_effect=[slow, healthy, FakeProcess()]), clock=clock)

        poller.tick()
        self.assertTrue(poller.tick())
        self.assertTrue(slow.terminated)
        self.assertFalse(poller.snapshots["slow"].available)
        self.assertTrue(poller.snapshots["dev"].available)

    def test_close_terminates_and_reaps_active_process(self):
        process = FakeProcess()
        poller = RemotePoller(["dev"], popen=Mock(return_value=process), clock=Mock(return_value=0))
        poller.tick()

        poller.close()

        self.assertTrue(process.terminated)
        self.assertTrue(process.communicated)


if __name__ == "__main__":
    unittest.main()
