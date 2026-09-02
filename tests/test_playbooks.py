"""Intent matching, plan building, and undo planning for all 10 seed playbooks."""

from __future__ import annotations

import pytest

from conftest import FakeRunner
from jarvis.execution.runner import ExecResult
from jarvis.planner.models import UndoStatus
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.safety.tiers import SafetyRefusal, Tier
from jarvis.system.models import InvalidInputError, UnsupportedError


def test_registry_has_exactly_ten_seed_playbooks() -> None:
    assert len(PLAYBOOKS) == 10
    ids = {pb.id for pb in PLAYBOOKS}
    assert ids == {
        "pkg.install",
        "pkg.remove",
        "pkg.search",
        "pkg.info",
        "pkg.cache.refresh",
        "pkg.upgrade",
        "svc.status",
        "svc.start",
        "svc.enable",
        "sys.info",
    }


@pytest.mark.parametrize(
    ("text", "expected_id"),
    [
        ("install htop", "pkg.install"),
        ("Install the package curl", "pkg.install"),
        ("install htop and curl", "pkg.install"),
        ("install htop, curl and btop", "pkg.install"),
        ("remove htop", "pkg.remove"),
        ("uninstall vim", "pkg.remove"),
        ("search text editor", "pkg.search"),
        ("search for text editor", "pkg.search"),
        ("info htop", "pkg.info"),
        ("details for htop", "pkg.info"),
        ("update", "pkg.cache.refresh"),
        ("update the package cache", "pkg.cache.refresh"),
        ("refresh the package index", None),  # 'refresh' alone is not an intent
        ("update the system", "pkg.upgrade"),
        ("upgrade system", "pkg.upgrade"),
        ("upgrade", "pkg.upgrade"),
        ("update everything", "pkg.upgrade"),
        ("status of ssh.service", "svc.status"),
        ("what's the status of docker", "svc.status"),
        ("start ssh", "svc.start"),
        ("start the ssh.service", "svc.start"),
        ("enable docker", "svc.enable"),
        ("system info", "sys.info"),
        ("machine summary", "sys.info"),
        ("tell me a joke", None),
        ("delete everything", None),
        ("install", None),
        ("make me a sandwich", None),
    ],
)
def test_match_intent(text: str, expected_id: str | None) -> None:
    matched = match_intent(text)
    if expected_id is None:
        assert matched is None
    else:
        assert matched is not None
        playbook, _params = matched
        assert playbook.id == expected_id


def test_match_extracts_multiple_names() -> None:
    _pb, params = match_intent("install htop and curl")  # type: ignore[misc]
    assert params["names"] == ["htop", "curl"]
    _pb, params = match_intent("remove htop, curl btop")  # type: ignore[misc]
    assert params["names"] == ["htop", "curl", "btop"]


def test_match_rejects_flag_injection_in_names() -> None:
    with pytest.raises(InvalidInputError):
        match_intent("install --flag htop")


def test_install_plan_on_debian(debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("install htop")  # type: ignore[misc]
    steps = playbook.build(params, debian_profile)
    assert len(steps) == 1
    step = steps[0]
    assert step.argv == ("apt-get", "install", "-y", "--", "htop")
    assert step.requires_root is True
    assert step.tier is Tier.T1
    assert step.extra_env == {"DEBIAN_FRONTEND": "noninteractive", "DEBIAN_PRIORITY": "critical"}


def test_upgrade_plan_has_refresh_first_on_apt(arch_profile, debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("upgrade system")  # type: ignore[misc]
    apt_steps = playbook.build(params, debian_profile)
    assert [s.argv for s in apt_steps] == [
        ("apt-get", "update"),
        ("apt-get", "upgrade", "-y"),
    ]
    assert apt_steps[-1].tier is Tier.T2
    # pacman upgrades atomically include the index refresh (-Syu).
    pacman_steps = playbook.build(params, arch_profile)
    assert [s.argv for s in pacman_steps] == [("pacman", "-Syu", "--noconfirm")]


def test_refresh_plan_warns_on_pacman(arch_profile, debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("update")  # type: ignore[misc]
    apt_desc = playbook.build(params, debian_profile)[0].description
    arch_desc = playbook.build(params, arch_profile)[0].description
    assert "Arch" not in apt_desc
    assert "Arch" in arch_desc


def test_remove_plan_refuses_protected_packages(debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("remove libc6")  # type: ignore[misc]
    with pytest.raises(SafetyRefusal):
        playbook.build(params, debian_profile)


def test_service_plans_require_systemd(debian_profile) -> None:  # type: ignore[no-untyped-def]
    from dataclasses import replace

    non_systemd = replace(debian_profile, init_system="other:openrc")
    for text in ("start ssh", "enable ssh", "status of ssh"):
        playbook, params = match_intent(text)  # type: ignore[misc]
        with pytest.raises(UnsupportedError):
            playbook.build(params, non_systemd)


def test_install_verify_and_undo(debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("install htop")  # type: ignore[misc]
    runner = FakeRunner(script=[(("dpkg-query", "-W"), ExecResult(0, "ii  htop", ""))])
    verification = playbook.verify(params, debian_profile, runner, None)
    assert verification.ok is True
    undo = playbook.undo(params, debian_profile)
    assert undo.status is UndoStatus.AVAILABLE
    assert undo.steps[0].argv == ("apt-get", "remove", "-y", "--", "htop")
    assert undo.verify_checks[0].expect_zero is False


def test_install_verify_failure(debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("install htop")  # type: ignore[misc]
    runner = FakeRunner(script=[(("dpkg-query", "-W"), ExecResult(1, "", ""))])
    verification = playbook.verify(params, debian_profile, runner, None)
    assert verification.ok is False


def test_upgrade_undo_is_honestly_unavailable(debian_profile) -> None:  # type: ignore[no-untyped-def]
    playbook, params = match_intent("upgrade system")  # type: ignore[misc]
    undo = playbook.undo(params, debian_profile)
    assert undo.status is UndoStatus.UNAVAILABLE
    assert "snapshot" in undo.reason or "backup" in undo.reason


def test_tiers_of_all_playbooks() -> None:
    expected = {
        "pkg.install": Tier.T1,
        "pkg.remove": Tier.T1,
        "pkg.search": Tier.T0,
        "pkg.info": Tier.T0,
        "pkg.cache.refresh": Tier.T1,
        "pkg.upgrade": Tier.T2,
        "svc.status": Tier.T0,
        "svc.start": Tier.T2,
        "svc.enable": Tier.T2,
        "sys.info": Tier.T0,
    }
    for pb in PLAYBOOKS:
        assert pb.tier is expected[pb.id], pb.id
