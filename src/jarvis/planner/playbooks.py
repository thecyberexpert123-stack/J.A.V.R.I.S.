"""Deterministic playbook engine (pipeline stages GROUND/PLAN, no LLM).

A playbook maps a normalized natural-language intent to exact steps for the
detected backend, plus post-conditions (VERIFY) and a reverse path (undo)
built *before* execution. Matching is anchored and strict: anything the
engine cannot map unambiguously is refused — never guessed (owner point 6).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from jarvis.execution.runner import ExecResult, Runner
from jarvis.planner.fileops import _build_append, _match_append, _undo_append, _verify_append
from jarvis.planner.models import CheckSpec, PlannedStep, UndoPlan, UndoStatus, Verification
from jarvis.safety.tiers import (
    SafetyRefusal,
    Tier,
    check_removal_allowed,
    validate_package_name,
    validate_search_query,
    validate_unit_name,
)
from jarvis.system.models import (
    InvalidInputError,
    MachineProfile,
    PackageManager,
    UnsupportedError,
)
from jarvis.system.packages import PMAdapter, get_adapter, installed_check_ok

Params = dict[str, object]

_SPLIT_NAMES = re.compile(r"\s*(?:,|\band\b)\s*|\s+")

_MATCH_INSTALL = re.compile(r"^install\s+(?:the\s+)?(?:packages?\s+)?(?P<rest>.+)$")
_MATCH_REMOVE = re.compile(r"^(?:remove|uninstall)\s+(?:the\s+)?(?:packages?\s+)?(?P<rest>.+)$")
_MATCH_SEARCH = re.compile(r"^(?:search|find)(?:\s+for)?(?:\s+packages?)?\s+(?P<query>.+)$")
_MATCH_INFO = re.compile(r"^(?:info|details|show)\s+(?:about\s+|for\s+)?(?P<name>\S+)$")
_MATCH_REFRESH = re.compile(r"^update(?:\s+(?:the\s+)?(?:package\s+)?(?:cache|index|lists))?$")
_MATCH_UPGRADE = re.compile(
    r"^(?:(?:upgrade|update)\s+(?:the\s+)?(?:whole\s+)?system|upgrades?|update\s+(?:everything|all))$"
)
_MATCH_SVC_STATUS = re.compile(
    r"^(?:what'?s\s+)?(?:the\s+)?status\s+of\s+(?:the\s+)?(?P<unit>[A-Za-z0-9][\w:@.-]*)"
    r"(?:\s+(?:service|unit))?$"
)
_MATCH_SVC_START = re.compile(
    r"^start\s+(?:the\s+)?(?P<unit>[A-Za-z0-9][\w:@.-]*)(?:\s+(?:service|unit))?$"
)
_MATCH_SVC_ENABLE = re.compile(
    r"^enable\s+(?:the\s+)?(?P<unit>[A-Za-z0-9][\w:@.-]*)(?:\s+(?:service|unit))?$"
)
_MATCH_SYSINFO = re.compile(r"^(?:system|machine)\s+(?:info|summary|status)$")


class _Build(Protocol):
    def __call__(self, params: Params, profile: MachineProfile) -> list[PlannedStep]: ...


class _Verify(Protocol):
    def __call__(
        self,
        params: Params,
        profile: MachineProfile,
        runner: Runner,
        step_results: Sequence[ExecResult | None] | None,
    ) -> Verification: ...


class _Undo(Protocol):
    def __call__(self, params: Params, profile: MachineProfile) -> UndoPlan: ...


@dataclass(frozen=True)
class Playbook:
    id: str
    description: str
    tier: Tier
    match: Callable[[str], Params | None]
    build: _Build
    verify: _Verify
    undo: _Undo


# --------------------------------------------------------------------------
# shared helpers
# --------------------------------------------------------------------------


def _adapter(profile: MachineProfile) -> PMAdapter:
    if profile.package_manager is None:
        raise UnsupportedError(
            "no supported package manager found on this machine "
            "(expected one of: apt, dnf, pacman, zypper, apk)"
        )
    return get_adapter(profile.package_manager)


def _require_systemd(profile: MachineProfile) -> None:
    if profile.init_system != "systemd":
        raise UnsupportedError(
            f"systemd is required for service operations, but this machine reports "
            f"init system {profile.init_system!r}"
        )


def _extract_names(rest: str) -> list[str]:
    raw = [tok for tok in _SPLIT_NAMES.split(rest.strip()) if tok]
    if not raw:
        raise ValueError("no package names given")
    seen: list[str] = []
    for token in raw:
        name = validate_package_name(token)
        if name not in seen:
            seen.append(name)
    return seen


def _installed_probe(profile: MachineProfile, runner: Runner, name: str) -> tuple[bool, str]:
    adapter = _adapter(profile)
    res = runner.run(
        adapter.installed_check_argv(name), requires_root=False, timeout_s=60, echo=False
    )
    ok = installed_check_ok(res.stdout_tail, res.exit_code, adapter.pm)
    state = "installed" if ok else "not installed"
    return ok, f"{name}: {state}"


def _run_probe(runner: Runner, argv: Sequence[str]) -> ExecResult:
    return runner.run(list(argv), requires_root=False, timeout_s=60, echo=False)


def _no_undo(reason: str, status: UndoStatus = UndoStatus.NONE_NEEDED) -> UndoPlan:
    return UndoPlan(status=status, reason=reason)


# --------------------------------------------------------------------------
# playbook: pkg.install
# --------------------------------------------------------------------------


def _match_install(text: str) -> Params | None:
    m = _MATCH_INSTALL.match(text)
    if not m:
        return None
    return {"names": _extract_names(m.group("rest"))}


def _build_install(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    adapter = _adapter(profile)
    names: list[str] = params["names"]  # type: ignore[assignment]
    return [
        PlannedStep(
            description=f"install package(s): {', '.join(names)}",
            argv=tuple(adapter.install_argv(names)),
            tier=Tier.T1,
            requires_root=True,
            timeout_s=1800.0,
            extra_env=adapter.mutating_env,
        )
    ]


def _verify_install(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    names: list[str] = params["names"]  # type: ignore[assignment]
    checks = []
    for name in names:
        ok, detail = _installed_probe(profile, runner, name)
        checks.append((f"installed:{name}", ok, detail))
    all_ok = all(passed for _, passed, _ in checks)
    return Verification(
        ok=all_ok,
        detail="all requested packages are installed"
        if all_ok
        else "one or more packages are not installed after the operation",
        checks=tuple(checks),
    )


def _undo_install(params: Params, profile: MachineProfile) -> UndoPlan:
    adapter = _adapter(profile)
    names: list[str] = params["names"]  # type: ignore[assignment]
    return UndoPlan(
        status=UndoStatus.AVAILABLE,
        reason=f"removes {', '.join(names)} again",
        steps=(
            PlannedStep(
                description=f"undo install: remove {', '.join(names)}",
                argv=tuple(adapter.remove_argv(names)),
                tier=Tier.T1,
                requires_root=True,
                timeout_s=1800.0,
                extra_env=adapter.mutating_env,
            ),
        ),
        verify_checks=(
            CheckSpec(
                name="packages absent",
                argv=tuple(adapter.installed_check_argv(names[0])),
                expect_zero=False,
            ),
        ),
        params={"names": names},
    )


# --------------------------------------------------------------------------
# playbook: pkg.remove
# --------------------------------------------------------------------------


def _match_remove(text: str) -> Params | None:
    m = _MATCH_REMOVE.match(text)
    if not m:
        return None
    return {"names": _extract_names(m.group("rest"))}


def _build_remove(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    adapter = _adapter(profile)
    names: list[str] = params["names"]  # type: ignore[assignment]
    for name in names:
        check_removal_allowed(name)  # raises SafetyRefusal for the protected set
    return [
        PlannedStep(
            description=f"remove package(s): {', '.join(names)}",
            argv=tuple(adapter.remove_argv(names)),
            tier=Tier.T1,
            requires_root=True,
            timeout_s=1800.0,
            extra_env=adapter.mutating_env,
        )
    ]


def _verify_absent(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    names: list[str] = params["names"]  # type: ignore[assignment]
    checks = []
    for name in names:
        installed, detail = _installed_probe(profile, runner, name)
        checks.append((f"absent:{name}", not installed, detail))
    all_ok = all(passed for _, passed, _ in checks)
    return Verification(
        ok=all_ok,
        detail="all requested packages are absent" if all_ok else "packages still present",
        checks=tuple(checks),
    )


def _undo_remove(params: Params, profile: MachineProfile) -> UndoPlan:
    adapter = _adapter(profile)
    names: list[str] = params["names"]  # type: ignore[assignment]
    return UndoPlan(
        status=UndoStatus.AVAILABLE,
        reason=f"reinstalls {', '.join(names)}",
        steps=(
            PlannedStep(
                description=f"undo remove: install {', '.join(names)}",
                argv=tuple(adapter.install_argv(names)),
                tier=Tier.T1,
                requires_root=True,
                timeout_s=1800.0,
                extra_env=adapter.mutating_env,
            ),
        ),
        verify_checks=(
            CheckSpec(
                name="packages back",
                argv=tuple(adapter.installed_check_argv(names[0])),
                expect_zero=True,
            ),
        ),
        params={"names": names},
    )


# --------------------------------------------------------------------------
# playbook: pkg.search
# --------------------------------------------------------------------------


def _match_search(text: str) -> Params | None:
    m = _MATCH_SEARCH.match(text)
    if not m:
        return None
    return {"tokens": validate_search_query(m.group("query"))}


def _build_search(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    adapter = _adapter(profile)
    tokens: list[str] = params["tokens"]  # type: ignore[assignment]
    return [
        PlannedStep(
            description=f"search repositories for: {' '.join(tokens)}",
            argv=tuple(adapter.search_argv(tokens)),
            tier=Tier.T0,
            timeout_s=120.0,
        )
    ]


def _verify_from_first_step(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    if not step_results or not step_results[0]:
        return Verification(ok=False, detail="no step result recorded for the query")
    first = step_results[0]
    lines = len(first.stdout_tail.splitlines())
    return Verification(
        ok=first.ok,
        detail=f"query exit={first.exit_code}, {lines} result line(s)",
        checks=(("query succeeded", first.ok, first.stderr_tail or "ok"),),
    )


def _undo_readonly(params: Params, profile: MachineProfile) -> UndoPlan:
    return _no_undo("read-only operation; nothing to reverse")


# --------------------------------------------------------------------------
# playbook: pkg.info
# --------------------------------------------------------------------------


def _match_info(text: str) -> Params | None:
    m = _MATCH_INFO.match(text)
    if not m:
        return None
    return {"name": validate_package_name(m.group("name"))}


def _build_info(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    adapter = _adapter(profile)
    name: str = params["name"]  # type: ignore[assignment]
    return [
        PlannedStep(
            description=f"show repository information for {name}",
            argv=tuple(adapter.info_argv(name)),
            tier=Tier.T0,
            timeout_s=120.0,
        )
    ]


# --------------------------------------------------------------------------
# playbook: pkg.cache.refresh
# --------------------------------------------------------------------------


def _match_refresh(text: str) -> Params | None:
    return {} if _MATCH_REFRESH.match(text) else None


def _build_refresh(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    adapter = _adapter(profile)
    note = (
        " (Arch note: prefer 'upgrade system' to avoid partial-upgrade states)"
        if adapter.pm is PackageManager.PACMAN
        else ""
    )
    return [
        PlannedStep(
            description=f"refresh package index{note}",
            argv=tuple(adapter.refresh_argv()),
            tier=Tier.T1,
            requires_root=True,
            timeout_s=900.0,
        )
    ]


def _undo_refresh(params: Params, profile: MachineProfile) -> UndoPlan:
    return _no_undo("refreshing the index is idempotent; no reverse state exists")


# --------------------------------------------------------------------------
# playbook: pkg.upgrade
# --------------------------------------------------------------------------


def _match_upgrade(text: str) -> Params | None:
    return {} if _MATCH_UPGRADE.match(text) else None


def _build_upgrade(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    adapter = _adapter(profile)
    steps: list[PlannedStep] = []
    # apt and apk do not refresh metadata inside 'upgrade'; refresh first so the
    # upgrade actually sees current versions (dnf/pacman/zypper handle it inline).
    if adapter.pm in (PackageManager.APT, PackageManager.APK):
        steps.append(
            PlannedStep(
                description="refresh package index (pre-upgrade)",
                argv=tuple(adapter.refresh_argv()),
                tier=Tier.T1,
                requires_root=True,
                timeout_s=900.0,
            )
        )
    steps.append(
        PlannedStep(
            description="upgrade installed packages",
            argv=tuple(adapter.upgrade_argv()),
            tier=Tier.T2,
            requires_root=True,
            timeout_s=3600.0,
            extra_env=adapter.mutating_env,
        )
    )
    return steps


def _undo_upgrade(params: Params, profile: MachineProfile) -> UndoPlan:
    return UndoPlan(
        status=UndoStatus.UNAVAILABLE,
        reason=(
            "a system upgrade cannot be reversed automatically; "
            "restore from a snapshot/backup if rollback is needed"
        ),
    )


# --------------------------------------------------------------------------
# playbook: svc.status
# --------------------------------------------------------------------------


def _match_svc_status(text: str) -> Params | None:
    m = _MATCH_SVC_STATUS.match(text)
    if not m:
        return None
    return {"unit": validate_unit_name(m.group("unit"))}


def _require_unit(params: Params) -> str:
    unit = params["unit"]
    if not isinstance(unit, str):
        raise InvalidInputError("unit parameter must be a string")
    return unit


def _build_svc_status(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    _require_systemd(profile)
    unit = _require_unit(params)
    return [
        PlannedStep(
            description=f"check unit {unit} exists",
            argv=("systemctl", "cat", "--", unit),
            tier=Tier.T0,
            timeout_s=60.0,
        ),
        PlannedStep(
            description=f"read active state of {unit}",
            argv=("systemctl", "is-active", "--", unit),
            tier=Tier.T0,
            timeout_s=60.0,
            optional=True,  # inactive units legitimately exit non-zero
        ),
    ]


def _verify_svc_status(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    unit = _require_unit(params)
    if not step_results or not step_results[0]:
        return Verification(ok=False, detail="no step result recorded")
    exists_ok = step_results[0].ok
    if not exists_ok:
        return Verification(
            ok=False,
            detail=f"unit {unit} not found on this system",
            checks=((f"unit-exists:{unit}", False, step_results[0].stderr_tail),),
        )
    state = step_results[1].stdout_tail.strip() if len(step_results) > 1 and step_results[1] else ""
    return Verification(
        ok=True,
        detail=f"unit {unit} exists; active state: {state or 'unknown'}",
        checks=((f"unit-exists:{unit}", True, "found"),),
    )


# --------------------------------------------------------------------------
# playbook: svc.start
# --------------------------------------------------------------------------


def _match_svc_start(text: str) -> Params | None:
    m = _MATCH_SVC_START.match(text)
    if not m:
        return None
    return {"unit": validate_unit_name(m.group("unit"))}


def _build_svc_start(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    _require_systemd(profile)
    unit = _require_unit(params)
    return [
        PlannedStep(
            description=f"start unit {unit}",
            argv=("systemctl", "start", "--", unit),
            tier=Tier.T2,
            requires_root=True,
            timeout_s=300.0,
        )
    ]


def _verify_svc_active(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    unit = _require_unit(params)
    res = _run_probe(runner, ("systemctl", "is-active", "--", unit))
    active = res.exit_code == 0 and res.stdout_tail.strip() == "active"
    return Verification(
        ok=active,
        detail=f"unit {unit} active state: {res.stdout_tail.strip() or 'unknown'}",
        checks=((f"is-active:{unit}", active, res.stdout_tail or res.stderr_tail),),
    )


def _undo_svc_start(params: Params, profile: MachineProfile) -> UndoPlan:
    unit = _require_unit(params)
    return UndoPlan(
        status=UndoStatus.AVAILABLE,
        reason=f"stops {unit} again",
        steps=(
            PlannedStep(
                description=f"undo start: stop {unit}",
                argv=("systemctl", "stop", "--", unit),
                tier=Tier.T2,
                requires_root=True,
                timeout_s=300.0,
            ),
        ),
        verify_checks=(
            CheckSpec(
                name="unit stopped",
                argv=("systemctl", "is-active", "--", unit),
                expect_zero=False,
            ),
        ),
        params={"unit": unit},
    )


# --------------------------------------------------------------------------
# playbook: svc.enable
# --------------------------------------------------------------------------


def _match_svc_enable(text: str) -> Params | None:
    m = _MATCH_SVC_ENABLE.match(text)
    if not m:
        return None
    return {"unit": validate_unit_name(m.group("unit"))}


def _build_svc_enable(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    _require_systemd(profile)
    unit = _require_unit(params)
    return [
        PlannedStep(
            description=f"enable unit {unit} (start on boot)",
            argv=("systemctl", "enable", "--", unit),
            tier=Tier.T2,
            requires_root=True,
            timeout_s=120.0,
        )
    ]


def _verify_svc_enabled(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    unit = _require_unit(params)
    res = _run_probe(runner, ("systemctl", "is-enabled", "--", unit))
    enabled = res.exit_code == 0 and res.stdout_tail.strip() == "enabled"
    return Verification(
        ok=enabled,
        detail=f"unit {unit} enabled state: {res.stdout_tail.strip() or 'unknown'}",
        checks=((f"is-enabled:{unit}", enabled, res.stdout_tail or res.stderr_tail),),
    )


def _undo_svc_enable(params: Params, profile: MachineProfile) -> UndoPlan:
    unit = _require_unit(params)
    return UndoPlan(
        status=UndoStatus.AVAILABLE,
        reason=f"disables {unit} again",
        steps=(
            PlannedStep(
                description=f"undo enable: disable {unit}",
                argv=("systemctl", "disable", "--", unit),
                tier=Tier.T2,
                requires_root=True,
                timeout_s=120.0,
            ),
        ),
        verify_checks=(
            CheckSpec(
                name="unit disabled",
                argv=("systemctl", "is-enabled", "--", unit),
                expect_zero=False,
            ),
        ),
        params={"unit": unit},
    )


# --------------------------------------------------------------------------
# playbook: sys.info
# --------------------------------------------------------------------------


def _match_sysinfo(text: str) -> Params | None:
    return {} if _MATCH_SYSINFO.match(text) else None


def _build_sysinfo(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    return [
        PlannedStep(
            description="kernel and architecture",
            argv=("uname", "-a"),
            tier=Tier.T0,
            timeout_s=30.0,
        ),
        PlannedStep(
            description="filesystem usage for /",
            # No '--' marker here: '/' is a path operand, not a package token,
            # and the marker rule rightly only admits package/unit tokens.
            argv=("df", "-h", "/"),
            tier=Tier.T0,
            timeout_s=30.0,
        ),
        PlannedStep(
            description="memory usage",
            argv=("free", "-h"),
            tier=Tier.T0,
            timeout_s=30.0,
            optional=True,  # procps is absent on some minimal systems
        ),
    ]


def _verify_sysinfo(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    if not step_results or not step_results[0]:
        return Verification(ok=False, detail="no step result recorded")
    uname_ok = step_results[0].ok
    return Verification(
        ok=uname_ok,
        detail="system summary collected" if uname_ok else "uname failed",
        checks=(("uname", uname_ok, step_results[0].stdout_tail or "no output"),),
    )


# --------------------------------------------------------------------------
# registry + dispatch
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# playbook: gui.launch (ADR-0010; app-name only, never paths; case-preserving)
# --------------------------------------------------------------------------


_GUI_LAUNCH_RE = re.compile(r"^(?:open|launch|run|start)\s+(?P<app>[A-Za-z0-9][A-Za-z0-9 ._+-]*)$")
_GUI_LAUNCH_TOKEN_RE = re.compile(r"^-{0,2}[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _match_gui_launch(request: str) -> Params | None:
    matched = _GUI_LAUNCH_RE.match(request.strip())
    if not matched:
        return None
    tokens = tuple(matched.group("app").split())
    if not all(_GUI_LAUNCH_TOKEN_RE.fullmatch(token) for token in tokens):
        return None
    return {"app": tokens[0], "tokens": list(tokens)}


def _build_gui_launch(params: Params, profile: MachineProfile) -> list[PlannedStep]:
    raw = params.get("tokens")
    tokens = tuple(str(t) for t in raw) if isinstance(raw, list) else ()
    if not tokens or not all(_GUI_LAUNCH_TOKEN_RE.fullmatch(t) for t in tokens):
        raise SafetyRefusal("gui.launch: invalid app argv")
    return [
        PlannedStep(
            description=f"launch {tokens[0]} (detached GUI process)",
            argv=("setsid", "--fork", *tokens),
            tier=Tier.T2,
            timeout_s=30.0,
        )
    ]


def _verify_gui_launch(
    params: Params,
    profile: MachineProfile,
    runner: Runner,
    step_results: Sequence[ExecResult | None] | None,
) -> Verification:
    if not step_results or not step_results[0]:
        return Verification(ok=False, detail="no step result recorded for the launch")
    first = step_results[0]
    return Verification(
        ok=first.ok,
        detail=f"setsid exit={first.exit_code} (window appearance not awaited)",
        checks=(("launch command succeeded", first.ok, first.stderr_tail or "ok"),),
    )


def _undo_gui_launch(params: Params, profile: MachineProfile) -> UndoPlan:
    return _no_undo("a launched app cannot be reverted by the kernel; close it manually")


PLAYBOOKS: tuple[Playbook, ...] = (
    Playbook(
        id="pkg.upgrade",
        description="upgrade all installed packages (T2, approval-gated)",
        tier=Tier.T2,
        match=_match_upgrade,
        build=_build_upgrade,
        verify=_verify_from_first_step,
        undo=_undo_upgrade,
    ),
    Playbook(
        id="pkg.cache.refresh",
        description="refresh the package index/repository metadata",
        tier=Tier.T1,
        match=_match_refresh,
        build=_build_refresh,
        verify=_verify_from_first_step,
        undo=_undo_refresh,
    ),
    Playbook(
        id="pkg.install",
        description="install one or more packages (reversible; undo kept)",
        tier=Tier.T1,
        match=_match_install,
        build=_build_install,
        verify=_verify_install,
        undo=_undo_install,
    ),
    Playbook(
        id="pkg.remove",
        description="remove one or more packages (protected set refused; undo kept)",
        tier=Tier.T1,
        match=_match_remove,
        build=_build_remove,
        verify=_verify_absent,
        undo=_undo_remove,
    ),
    Playbook(
        id="pkg.search",
        description="search repositories (read-only)",
        tier=Tier.T0,
        match=_match_search,
        build=_build_search,
        verify=_verify_from_first_step,
        undo=_undo_readonly,
    ),
    Playbook(
        id="pkg.info",
        description="show repository information for a package (read-only)",
        tier=Tier.T0,
        match=_match_info,
        build=_build_info,
        verify=_verify_from_first_step,
        undo=_undo_readonly,
    ),
    Playbook(
        id="svc.status",
        description="report a systemd unit's existence and active state (read-only)",
        tier=Tier.T0,
        match=_match_svc_status,
        build=_build_svc_status,
        verify=_verify_svc_status,
        undo=_undo_readonly,
    ),
    Playbook(
        id="svc.start",
        description="start a systemd unit (T2, approval-gated; undo kept)",
        tier=Tier.T2,
        match=_match_svc_start,
        build=_build_svc_start,
        verify=_verify_svc_active,
        undo=_undo_svc_start,
    ),
    Playbook(
        id="svc.enable",
        description="enable a systemd unit at boot (T2, approval-gated; undo kept)",
        tier=Tier.T2,
        match=_match_svc_enable,
        build=_build_svc_enable,
        verify=_verify_svc_enabled,
        undo=_undo_svc_enable,
    ),
    Playbook(
        id="sys.info",
        description="print a system summary (read-only)",
        tier=Tier.T0,
        match=_match_sysinfo,
        build=_build_sysinfo,
        verify=_verify_sysinfo,
        undo=_undo_readonly,
    ),
    # file.append is built in planner.fileops (breaks an import cycle); its
    # effective tier is computed from the built steps (T2 for system paths).
    Playbook(
        id="file.append",
        description="append one line to a file (backup taken; undo restores it)",
        tier=Tier.T1,
        match=_match_append,
        build=_build_append,
        verify=_verify_append,
        undo=_undo_append,
    ),
    Playbook(
        id="gui.launch",
        description="launch a desktop app detached (T2, approval-gated; ADR-0010)",
        tier=Tier.T2,
        match=_match_gui_launch,
        build=_build_gui_launch,
        verify=_verify_gui_launch,
        undo=_undo_gui_launch,
    ),
)


def match_intent(text: str) -> tuple[Playbook, Params] | None:
    """Map normalized text to (playbook, params). None = refuse (never guess).

    Package/service intents are matched lowercased (names are case-insensitive
    there); file intents are matched against the whitespace-collapsed ORIGINAL
    because Linux paths are case-sensitive.
    """
    collapsed = re.sub(r"\s+", " ", text.strip())
    normalized = collapsed.lower()
    for playbook in PLAYBOOKS:
        source = collapsed if playbook.id.startswith(("file.", "gui.")) else normalized
        params = playbook.match(source)
        if params is not None:
            return playbook, params
    return None
