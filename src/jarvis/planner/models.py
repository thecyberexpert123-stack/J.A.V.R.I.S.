"""Typed plan artifacts (pipeline stage PLAN output, consumed by APPROVE/EXECUTE)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum

from jarvis.safety.tiers import Tier


class TaskStatus(str, Enum):
    REFUSED = "refused"
    RUNNING = "running"
    DRY_RUN = "dry_run"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNDONE = "undone"


class UndoStatus(str, Enum):
    NONE_NEEDED = "none_needed"
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class PlannedStep:
    """One concrete, guarded command within a plan."""

    description: str
    argv: tuple[str, ...]
    tier: Tier
    requires_root: bool = False
    timeout_s: float = 300.0
    optional: bool = False
    extra_env: Mapping[str, str] | None = None


@dataclass(frozen=True)
class CheckSpec:
    """A post-condition probe: argv must (or must not) exit zero."""

    name: str
    argv: tuple[str, ...]
    expect_zero: bool = True


@dataclass(frozen=True)
class Verification:
    """Aggregated post-condition result (pipeline stage VERIFY)."""

    ok: bool
    detail: str
    checks: tuple[tuple[str, bool, str], ...] = ()  # (name, passed, detail)


@dataclass(frozen=True)
class UndoPlan:
    """Reverse path for a mutating task, built BEFORE execution (never after)."""

    status: UndoStatus
    reason: str = ""
    steps: tuple[PlannedStep, ...] = ()
    verify_checks: tuple[CheckSpec, ...] = ()
    params: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Refusal:
    """A request refused before execution (no journal-less refusals exist)."""

    reason: str
    hint: str = ""
