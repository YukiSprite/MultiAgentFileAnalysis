"""Deterministic safety checks for user-run diagnostic commands."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class CommandAssessment:
    approved: bool
    command: str | None
    reason: str
    risk_level: str = "low"


class SafeCommandBroker:
    """Allow only bounded, read-only diagnostic command shapes.

    This is intentionally conservative. A rejected command is omitted from the
    HITL request; the user can still be asked for the missing fact in prose.
    """

    _shell_metacharacters = re.compile(
        r"[;&|><`*?\[\]\n\r]|\$\(|\$\{"
    )
    _allowed_subcommands: dict[str, set[str] | None] = {
        "systemctl": {
            "status",
            "show",
            "cat",
            "is-active",
            "is-enabled",
            "list-units",
            "list-unit-files",
        },
        "journalctl": None,
        "sshd": {"-T", "-t"},
        "ss": None,
        "ip": {"addr", "address", "link", "route", "rule"},
        "getent": None,
        "hostnamectl": {"status"},
        "uname": None,
        "lsb_release": None,
        "stat": None,
    }
    _mutating_words = {
        "add",
        "apply",
        "delete",
        "del",
        "disable",
        "edit",
        "enable",
        "flush",
        "kill",
        "mask",
        "reload",
        "remove",
        "restart",
        "set",
        "start",
        "stop",
        "unmask",
        "write",
    }

    def assess(self, command: str | None) -> CommandAssessment:
        if command is None or not command.strip():
            return CommandAssessment(False, None, "No command was provided")
        candidate = command.strip()
        if self._shell_metacharacters.search(candidate):
            return CommandAssessment(
                False,
                None,
                "Shell composition, redirection, and substitution are not allowed",
            )

        try:
            parts = shlex.split(candidate, posix=True)
        except ValueError:
            return CommandAssessment(False, None, "Command could not be parsed")
        if not parts:
            return CommandAssessment(False, None, "Command is empty")

        executable = Path(parts[0]).name
        if executable == "sudo":
            return CommandAssessment(
                False,
                None,
                "Privilege escalation is not allowed in generated commands",
                risk_level="high",
            )
        allowed_subcommands = self._allowed_subcommands.get(executable)
        if executable not in self._allowed_subcommands:
            return CommandAssessment(
                False,
                None,
                f"Executable '{executable}' is not in the read-only allowlist",
            )

        arguments = parts[1:]
        words = {argument.casefold() for argument in arguments}
        if words & self._mutating_words:
            return CommandAssessment(
                False,
                None,
                "Command contains a mutating operation",
                risk_level="high",
            )

        if allowed_subcommands is not None:
            first_argument = arguments[0] if arguments else ""
            if first_argument not in allowed_subcommands:
                return CommandAssessment(
                    False,
                    None,
                    f"Unsupported {executable} diagnostic operation",
                )

        if executable == "journalctl" and not self._journalctl_is_bounded(arguments):
            return CommandAssessment(
                False,
                None,
                "journalctl requests must include a bounded line count (-n/--lines)",
                risk_level="medium",
            )
        if executable == "ss" and any(
            argument in {"-K", "--kill"} for argument in arguments
        ):
            return CommandAssessment(
                False,
                None,
                "Socket termination is not a read-only diagnostic operation",
                risk_level="high",
            )

        return CommandAssessment(
            True,
            candidate,
            "Command matches the read-only diagnostic allowlist",
        )

    @staticmethod
    def _journalctl_is_bounded(arguments: list[str]) -> bool:
        for index, argument in enumerate(arguments):
            if argument.startswith("--lines="):
                try:
                    return 1 <= int(argument.split("=", 1)[1]) <= 500
                except ValueError:
                    return False
            if argument in {"-n", "--lines"} and index + 1 < len(arguments):
                try:
                    return 1 <= int(arguments[index + 1]) <= 500
                except ValueError:
                    return False
            if argument.startswith("-n") and len(argument) > 2:
                try:
                    return 1 <= int(argument[2:]) <= 500
                except ValueError:
                    return False
        return False


_DANGEROUS_ACTION = re.compile(
    r"\b(?:rm|shutdown|reboot|poweroff|mkfs|dd|chmod|chown)\b"
    r"|\bsystemctl\s+(?:restart|stop|disable|mask|edit)\b"
    r"|\bsed\s+-i\b|\btee\b|\biptables\b|\bufw\s+(?:delete|disable|reset)\b",
    re.IGNORECASE,
)


def action_requires_explicit_warning(action: str) -> bool:
    """Return True for mutation-shaped advice lacking a visible warning."""
    if not _DANGEROUS_ACTION.search(action):
        return False
    warning_words = (
        "risk",
        "backup",
        "confirm",
        "rollback",
        "风险",
        "备份",
        "确认",
        "回滚",
    )
    lowered = action.casefold()
    return not any(word in lowered for word in warning_words)
