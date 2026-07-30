from __future__ import annotations

import unittest

from multi_agent_file_analysis.hitl import (
    SafeCommandBroker,
    action_requires_explicit_warning,
)


class CommandSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.broker = SafeCommandBroker()

    def test_read_only_systemctl_is_allowed(self) -> None:
        result = self.broker.assess("systemctl status ssh.service --no-pager")
        self.assertTrue(result.approved)

    def test_shell_composition_is_rejected(self) -> None:
        result = self.broker.assess(
            "systemctl status ssh.service; rm -rf /"
        )
        self.assertFalse(result.approved)

    def test_mutating_systemctl_is_rejected(self) -> None:
        result = self.broker.assess("systemctl restart ssh.service")
        self.assertFalse(result.approved)

    def test_socket_kill_and_wildcards_are_rejected(self) -> None:
        self.assertFalse(self.broker.assess("ss -K dst 127.0.0.1").approved)
        self.assertFalse(
            self.broker.assess("systemctl status ssh*.service").approved
        )

    def test_journalctl_must_be_bounded(self) -> None:
        self.assertFalse(
            self.broker.assess("journalctl -u ssh.service").approved
        )
        self.assertTrue(
            self.broker.assess(
                "journalctl -u ssh.service -n 100 --no-pager"
            ).approved
        )

    def test_mutating_advice_requires_warning(self) -> None:
        self.assertTrue(
            action_requires_explicit_warning("systemctl restart ssh.service")
        )
        self.assertFalse(
            action_requires_explicit_warning(
                "确认业务窗口并准备回滚后，再运行 systemctl restart ssh.service"
            )
        )


if __name__ == "__main__":
    unittest.main()
