"""Shared test fixtures: fake runner, canned machine profiles, journal wiring."""

from __future__ import annotations

import json
import threading
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, HTTPServer
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
        stdin_text: str = "",
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


class StubHTTPServer:
    """Tiny scriptable HTTP server for provider tests (no network egress).

    Queue responses with ``queue(...)``; each POST pops one (the last repeats).
    GET always answers 200 {} (Ollama's /api/tags availability probe).
    """

    def __init__(self) -> None:
        self._queue: list[tuple[int, object]] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: object) -> None:  # silence test output
                pass

            def do_GET(self) -> None:
                self._send(200, b"{}")

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                self.rfile.read(length)
                if outer._queue:
                    status, body = outer._queue.pop(0)
                else:
                    status, body = 500, {"error": "no scripted response"}
                payload = (
                    json.dumps(body).encode("utf-8")
                    if isinstance(body, (dict, list))
                    else str(body).encode("utf-8")
                )
                self._send(status, payload)

            def _send(self, status: int, payload: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def queue(self, body: object, status: int = 200) -> None:
        self._queue.append((status, body))

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()


@pytest.fixture()
def stub_server() -> object:
    server = StubHTTPServer()
    yield server
    server.close()


class FakeProvider:
    """Scripted in-memory provider for planner/router tests (no HTTP at all)."""

    def __init__(
        self,
        replies: Sequence[str] | None = None,
        *,
        name: str = "fake",
        model: str = "fake-model",
        raise_on_complete: Exception | None = None,
    ) -> None:
        self._replies = list(replies or [])
        self.name = name
        self.model = model
        self.raise_on_complete = raise_on_complete
        self.calls: list[tuple[str, str]] = []

    def available(self) -> bool:
        return True

    def complete(self, system: str, user: str, *, timeout_s: float = 90.0) -> str:
        self.calls.append((system, user))
        if self.raise_on_complete is not None:
            raise self.raise_on_complete
        if not self._replies:
            return "{}"
        return self._replies.pop(0)


__all__ = ["FakeProvider", "StubHTTPServer", "TaskStatus", "make_profile", "make_result"]
