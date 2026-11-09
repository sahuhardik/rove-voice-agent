"""`server/livekit_dev.py` must carry --node-ip, or a restart loses the mic fix."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from server import livekit_dev  # noqa: E402
from server.config import Settings  # noqa: E402


class NodeIpDerivation(unittest.TestCase):
    def test_a_public_ip_in_the_livekit_url_is_the_node_ip(self) -> None:
        settings = Settings.from_env({"ROVE_LIVEKIT_URL": "ws://3.92.152.155:7880"})
        self.assertEqual(livekit_dev.node_ip_from_settings(settings), "3.92.152.155")

    def test_loopback_has_no_node_ip(self) -> None:
        settings = Settings.from_env({})
        self.assertIsNone(livekit_dev.node_ip_from_settings(settings))

    def test_public_ip_setting_is_the_fallback_for_a_hostname_url(self) -> None:
        settings = Settings.from_env(
            {"ROVE_LIVEKIT_URL": "wss://media.example.com", "ROVE_PUBLIC_IP": "203.0.113.9"}
        )
        self.assertEqual(livekit_dev.node_ip_from_settings(settings), "203.0.113.9")


class CommandLine(unittest.TestCase):
    def test_node_ip_is_passed_to_the_binary(self) -> None:
        server = livekit_dev.DevServer(
            binary=Path("/bin/livekit-server"), bind="0.0.0.0", node_ip="3.92.152.155"
        )
        command = server.command()
        self.assertEqual(command[command.index("--node-ip") + 1], "3.92.152.155")

    def test_no_node_ip_means_no_flag(self) -> None:
        server = livekit_dev.DevServer(binary=Path("/bin/livekit-server"))
        self.assertNotIn("--node-ip", server.command())

    def test_start_launches_the_command_with_the_flag(self) -> None:
        server = livekit_dev.DevServer(
            binary=Path("/bin/livekit-server"), node_ip="198.51.100.4"
        )
        with mock.patch.object(livekit_dev.subprocess, "Popen") as popen, \
                mock.patch.object(server, "responding", return_value=True):
            popen.return_value.poll.return_value = None
            server.start()
        self.assertIn("--node-ip", popen.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
