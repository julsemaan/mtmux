import subprocess
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
    remote_snapshot,
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
        run = Mock(return_value=Mock(returncode=0, stdout="work:0:!\nchat:1:-\nidle:0:-\n", stderr=""))

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

    def test_remote_snapshot_rejects_oversized_output_with_bounded_stderr(self):
        def run(command, **kwargs):
            kwargs["stdout"].write(b"x" * (1024 * 1024 + 1))
            kwargs["stderr"].write(b"diagnostic")
            return Mock(returncode=0)

        with patch("mtmux.discovery.subprocess.run", side_effect=run):
            self.assertEqual(remote_snapshot("dev").error, "output exceeded 1 MiB")

    def test_remote_snapshot_distinguishes_no_server_from_tmux_failure(self):
        no_server = Mock(returncode=1, stdout="", stderr="no server running on /tmp/tmux-1000/default\n")
        failure = Mock(returncode=1, stdout="", stderr="tmux: permission denied\n")

        with patch("mtmux.discovery.subprocess.run", side_effect=[no_server, failure]):
            self.assertEqual(remote_snapshot("dev"), RemoteSnapshot(True, (), frozenset()))
            self.assertEqual(remote_snapshot("dev").error, "tmux: permission denied")

    def test_malformed_lines_are_ignored(self):
        self.assertEqual(_parse_remote_snapshot("broken\n:1:!\n"), RemoteSnapshot(True, (), frozenset()))


class FakeProcess:
    def __init__(self, returncode=None, stdout=""):
        self.returncode = returncode
        self.stdout = stdout
        self.terminated = False
        self.communicated = False
        self.killed = False
        self.wait_timeouts = []

    def poll(self):
        return self.returncode

    def communicate(self):
        self.communicated = True
        return self.stdout, ""

    def terminate(self):
        self.terminated = True
        self.returncode = -15

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


class TerminateIgnoringProcess(FakeProcess):
    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        self.wait_timeouts.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired("ssh", timeout)
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
        poller.close()

    def test_completed_and_failed_processes_update_snapshots(self):
        healthy = FakeProcess(0, "work:1:!\n")
        failed = FakeProcess(255)
        poller = RemotePoller(["dev", "off"], popen=Mock(side_effect=[healthy, failed]), clock=Mock(return_value=0))

        self.assertTrue(poller.tick())
        self.assertEqual(poller.snapshots["dev"], RemoteSnapshot(True, ("work",), frozenset({"work"})))
        self.assertEqual(poller.snapshots["off"].error, "remote command exited 255")
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
        poller.close()

    def test_oversized_output_is_rejected_and_stderr_is_bounded(self):
        def popen(command, **kwargs):
            kwargs["stdout"].write(b"x" * (1024 * 1024 + 1))
            kwargs["stderr"].write(b"diagnostic")
            return FakeProcess(0)

        poller = RemotePoller(["dev"], popen=popen, clock=Mock(return_value=0))

        self.assertTrue(poller.tick())
        self.assertEqual(poller.snapshots["dev"].error, "output exceeded 1 MiB")

    def test_poller_distinguishes_no_server_from_tmux_failure(self):
        def popen(command, **kwargs):
            process = FakeProcess(1)
            kwargs["stderr"].write(
                b"no server running on /tmp/tmux-1000/default\n"
                if command[-2] == "empty"
                else b"tmux: permission denied\n"
            )
            return process

        poller = RemotePoller(["empty", "broken"], popen=popen, clock=Mock(return_value=0))

        self.assertTrue(poller.tick())
        self.assertEqual(poller.snapshots["empty"], RemoteSnapshot(True, (), frozenset()))
        self.assertEqual(poller.snapshots["broken"].error, "tmux: permission denied")

    def test_success_uses_slower_interval_and_resets_failure_backoff(self):
        clock = Mock(side_effect=[0, 2])
        popen = Mock(side_effect=[FakeProcess(255), FakeProcess(0)])
        poller = RemotePoller(["dev"], popen=popen, clock=clock, random=Mock(return_value=1))

        poller.tick()
        poller.tick()

        self.assertEqual(popen.call_count, 2)
        self.assertEqual(poller._next["dev"], 12)
        self.assertEqual(poller._failures["dev"], 0)

    def test_failures_use_capped_exponential_backoff_with_jitter(self):
        clock = Mock(side_effect=[0, 2, 6, 14, 30, 62, 122, 182])
        popen = Mock(side_effect=[FakeProcess(255) for _ in range(8)])
        poller = RemotePoller(["dev"], popen=popen, clock=clock, random=Mock(return_value=1))

        for _ in range(8):
            poller.tick()

        self.assertEqual(poller._next["dev"], 242)

    def test_failure_backoff_jitter_is_deterministic(self):
        poller = RemotePoller(
            ["dev"], popen=Mock(return_value=FakeProcess(255)),
            clock=Mock(return_value=0), random=Mock(return_value=0),
        )

        poller.tick()

        self.assertEqual(poller._next["dev"], 1)

    def test_refresh_retries_immediately_during_backoff(self):
        clock = Mock(side_effect=[0, 1, 1])
        popen = Mock(side_effect=[FakeProcess(255), FakeProcess(0)])
        poller = RemotePoller(["dev"], popen=popen, clock=clock, random=Mock(return_value=1))

        poller.tick()
        poller.refresh()
        poller.tick()

        self.assertEqual(popen.call_count, 2)

    def test_timeout_kills_and_reaps_process_that_ignores_terminate(self):
        process = TerminateIgnoringProcess()
        poller = RemotePoller(["dev"], popen=Mock(return_value=process), clock=Mock(side_effect=[0, 11]))
        poller.tick()

        self.assertTrue(poller.tick())

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.wait_timeouts, [1, None])

    def test_close_terminates_and_reaps_active_process(self):
        process = FakeProcess()
        poller = RemotePoller(["dev"], popen=Mock(return_value=process), clock=Mock(return_value=0))
        poller.tick()

        poller.close()

        self.assertTrue(process.terminated)
        self.assertTrue(process.communicated)


if __name__ == "__main__":
    unittest.main()
