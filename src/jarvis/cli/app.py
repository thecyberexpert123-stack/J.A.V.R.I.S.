"""JARVIS command-line interface (argparse; ADR-0005 — stdlib only at M1).

Exit codes: 0 success/dry-run · 1 execution or verification failure ·
2 refused (policy, protected set, unmatched intent, invalid input) ·
130 interrupted by signal.
"""

from __future__ import annotations

import argparse
import json
import sys

from jarvis import __version__
from jarvis.core.fingerprint import build_profile
from jarvis.core.orchestrator import Orchestrator, TaskOutcome
from jarvis.execution.runner import LocalRunner
from jarvis.journal.sqlite import Journal, default_db_path
from jarvis.planner.playbooks import PLAYBOOKS
from jarvis.safety.approval import ApprovalPolicy


def _print_outcome(outcome: TaskOutcome) -> None:
    print(f"playbook : {outcome.playbook_id}")
    print(f"task     : {outcome.task_id or '-'}")
    print(f"status   : {outcome.status.value} (exit {outcome.exit_code()})")
    for step in outcome.steps:
        exit_part = f" exit={step['exit_code']}" if step.get("exit_code") is not None else ""
        print(f"  step {step['seq']}: {step['status']}{exit_part} — {step['description']}")
    if outcome.verification is not None:
        mark = "PASS" if outcome.verification.ok else "FAIL"
        print(f"verify   : {mark} — {outcome.verification.detail}")
        for name, passed, detail in outcome.verification.checks:
            print(f"  [{'x' if passed else ' '}] {name}: {detail}")
    if outcome.undo_status is not None:
        extra = f" — {outcome.undo_reason}" if outcome.undo_reason else ""
        print(f"undo     : {outcome.undo_status.value}{extra}")
    if outcome.undo_status is None and outcome.playbook_id not in ("undo", "<unmatched>"):
        print("undo     : not applicable (read-only)")
    if outcome.error:
        print(f"error    : {outcome.error}", file=sys.stderr)
    if outcome.hint:
        print(f"hint     : {outcome.hint}")


def _build_orchestrator(args: argparse.Namespace) -> tuple[Orchestrator, Journal]:
    profile = build_profile()
    journal = Journal(default_db_path())
    runner = LocalRunner()
    policy = ApprovalPolicy(yes=args.yes, silent=bool(args.json))
    echo = not args.json
    return Orchestrator(profile, journal, runner, policy, echo=echo), journal


def _cmd_status(args: argparse.Namespace) -> int:
    profile = build_profile()
    if args.json:
        print(json.dumps(profile.to_dict(), indent=2))
        return 0
    pm = profile.package_manager.value if profile.package_manager else "none found"
    print(
        f"distro          : {profile.distro_name} (id={profile.distro_id}"
        f"{', v' + profile.version_id if profile.version_id else ''})"
    )
    print(f"init system     : {profile.init_system}")
    print(f"package manager : {pm}")
    print(f"session type    : {profile.session_type or 'none (likely headless)'}")
    print(
        f" privileges     : {'root' if profile.is_root else 'user'}"
        f" (sudo {'available' if profile.sudo_available else 'unavailable'})"
    )
    print(f"python          : {profile.python_version}")
    print(f"journal         : {default_db_path()}")
    return 0


def _cmd_do(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("error: empty request", file=sys.stderr)
        return 2
    orch, _journal = _build_orchestrator(args)
    outcome = orch.run_intent(text, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_undo(args: argparse.Namespace) -> int:
    orch, _journal = _build_orchestrator(args)
    outcome = orch.undo(args.task_id, dry_run=args.dry_run)
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_playbooks(args: argparse.Namespace) -> int:
    if args.json:
        print(
            json.dumps(
                [
                    {"id": pb.id, "description": pb.description, "tier": int(pb.tier)}
                    for pb in PLAYBOOKS
                ],
                indent=2,
            )
        )
        return 0
    print("available playbooks:")
    for pb in PLAYBOOKS:
        print(f"  {pb.id:<18} T{int(pb.tier)}  {pb.description}")
    return 0


def _cmd_tasks(args: argparse.Namespace) -> int:
    journal = Journal(default_db_path())
    tasks = journal.recent_tasks(limit=args.limit)
    if args.json:
        print(json.dumps(tasks, indent=2))
        return 0
    if not tasks:
        print("no tasks journaled yet")
        return 0
    print(f"{'id':<14}{'status':<12}{'tier':<6}{'playbook':<20}created (UTC)  intent")
    for t in tasks:
        print(
            f"{t['id']:<14}{t['status']:<12}T{t['tier']:<5}{t['playbook_id']:<20}"
            f"{t['created_utc']}  {t['intent_text']}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jarvis",
        description=(
            "JARVIS — Just A Rather Very Intelligent System: a verified, "
            "safety-kernelled automation agent for Linux."
        ),
    )
    parser.add_argument("--version", action="version", version=f"jarvis {__version__}")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--yes", action="store_true", help="consent non-interactively to T2 actions"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_status = sub.add_parser("status", help="fingerprint this machine (read-only)")
    p_status.set_defaults(func=_cmd_status)

    p_do = sub.add_parser("do", help='execute a request, e.g. jarvis do "install htop"')
    p_do.add_argument("--dry-run", action="store_true", help="print the plan; execute nothing")
    p_do.add_argument("text", nargs="+", help="natural-language request")
    p_do.set_defaults(func=_cmd_do)

    p_undo = sub.add_parser("undo", help="undo a previous task by id (see: jarvis tasks)")
    p_undo.add_argument("--dry-run", action="store_true", help="print the undo plan only")
    p_undo.add_argument("task_id", help="task id from the journal")
    p_undo.set_defaults(func=_cmd_undo)

    p_pb = sub.add_parser("playbooks", help="list known playbooks")
    p_pb.set_defaults(func=_cmd_playbooks)

    p_tasks = sub.add_parser("tasks", help="list recent journaled tasks")
    p_tasks.add_argument("--limit", type=int, default=20)
    p_tasks.set_defaults(func=_cmd_tasks)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = int(args.func(args))
    except KeyboardInterrupt:
        print("\n[jarvis] interrupted", file=sys.stderr)
        return 130
    return result


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
