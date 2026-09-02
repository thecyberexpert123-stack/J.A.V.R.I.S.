"""Shared test fixtures: fake runner, canned machine profiles, journal wiring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from jarvis.core.fingerprint import MachineProfile
from jarvis.execution.runner import ExecResult, Runner
from jarvis.journal.sqlite import Journal
from jarvis.planner.models import TaskStatus
from jarvis.safety.approval import ApprovalPolicy
from jarvis.system.models import PackageManager


class FakeRunner(Runner):
    """Scripted runner: maps argv prefixes to results in first-match order.

    Entries may be ExecResult instances or Exception instances (raised when the
    prefix matches). Unmatched argv returns a benign success.
    """

    def __init__(
        self,
        script: Sequence[tuple[Sequence[str], ExecResult | Exception]] | None = None,
        default_exit: int = 0,
        default_stdout: str = "",
    ) -> None:
        self._script = [(tuple(prefix), value) for prefix, value in (script or [])]
        self._default_exit = default_exit
        self._default_stdout = default_stdout
        self.calls: list[tuple[tuple[str, ...], bool, Mapping[str, str] | None]] = []
        self.terminated = False

    def run(
        self,
        argv: Sequence[str],
        *,
        requires_root: bool = False,
        timeout_s: float = 300.0,
        extra_env: Mapping[str, str] | None = None,
        echo: bool = True,
    ) -> ExecResult:
        key = tuple(argv)
        self.calls.append((key, requires_root, extra_env))
        for prefix, value in self._script:
            if key[: len(prefix)] == prefix:
                if isinstance(value, Exception):
                    raise value
                return value
        return ExecResult(self._default_exit, self._default_stdout, "", False)

    def terminate_current(self) -> None:
        self.terminated = True

    def argv_of(self, index: int) -> tuple[str, ...]:
        return self.calls[index][0]


def make_profile(
    pm: PackageManager | None = PackageManager.APT,
    init: str = "systemd",
    is_root: bool = True,
    sudo: bool = True,
    distro_id: str = "debian",
) -> MachineProfile:
    return MachineProfile(
        distro_id=distro_id,
        distro_name="Debian GNU/Linux 12 (bookworm)",
        version_id="12",
        init_system=init,
        package_manager=pm,
        session_type=None,
        is_root=is_root,
        sudo_available=sudo,
        python_version="3.11.2",
    )


@pytest.fixture()
def debian_profile() -> MachineProfile:
    return make_profile()


@pytest.fixture()
def arch_profile() -> MachineProfile:
    return make_profile(pm=PackageManager.PACMAN, distro_id="arch")


@pytest.fixture()
def journal(tmp_path: Path) -> Journal:
    return Journal(tmp_path / "journal.db")


@pytest.fixture()
def yes_policy() -> ApprovalPolicy:
    return ApprovalPolicy(yes=True)


def make_result(
    exit_code: int = 0, stdout: str = "", stderr: str = "", timed_out: bool = False
) -> ExecResult:
    return ExecResult(
        exit_code=exit_code, stdout_tail=stdout, stderr_tail=stderr, timed_out=timed_out
    )


__all__ = [
    "FakeRunner",
    "TaskStatus",
    "make_profile",
    "make_result",
]
