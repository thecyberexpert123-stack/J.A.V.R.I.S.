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
from jarvis.knowledge.answers import answer as kb_answer
from jarvis.knowledge.store import load_kb
from jarvis.planner.llm import PlanRefused, build_plan
from jarvis.planner.models import TaskStatus
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.providers.base import ProviderError
from jarvis.providers.router import plan_routing
from jarvis.safety.approval import ApprovalPolicy
from jarvis.system.models import InvalidInputError


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
    if outcome.snapshot_note:
        print(f"snapshot : {outcome.snapshot_note}")
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
    try:
        routing = plan_routing()
        llm_line = f"{routing.mode} — {routing.note}"
    except Exception as exc:  # status must never crash
        llm_line = f"probe failed: {exc}"
    print(f"llm planning    : {llm_line}")
    try:
        kb = load_kb()
        print(f"knowledge base  : v{kb.version}, {len(kb.facts)} cited facts")
    except Exception as exc:  # status must never crash
        print(f"knowledge base  : unavailable ({exc})")
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


def _ask_flow(orch: Orchestrator, args: argparse.Namespace, text: str) -> TaskOutcome:
    """Engine-first routing: deterministic playbooks, LLM planner otherwise."""
    quiet = bool(args.json)
    try:
        matched = match_intent(text)
    except InvalidInputError as exc:
        return TaskOutcome(
            playbook_id="<unmatched>",
            status=TaskStatus.REFUSED,
            error=f"invalid input: {exc}",
        )
    if matched is not None:
        if not quiet:
            print("[engine] deterministic playbook match — LLM not consulted")
        return orch.run_intent(text, dry_run=args.dry_run)

    routing = plan_routing()
    if routing.mode == "none" or routing.provider is None:
        return TaskOutcome(
            playbook_id="<unmatched>",
            status=TaskStatus.REFUSED,
            error="no planning backend available for this request",
            hint=(
                f"{routing.note}. Install Ollama (local-first, ADR-0003) or "
                "configure the remote endpoint, or use 'jarvis do' with a "
                "supported playbook intent."
            ),
        )
    provider = routing.provider
    if not quiet:
        print(f"[planner] asking {routing.mode}:{provider.name}/{provider.model} for a plan...")
    try:
        proposed = build_plan(text, provider)
    except PlanRefused as exc:
        return TaskOutcome(
            playbook_id="plan",
            status=TaskStatus.REFUSED,
            error=str(exc),
            hint=exc.hint,
        )
    except ProviderError as exc:
        return TaskOutcome(
            playbook_id="plan",
            status=TaskStatus.FAILED,
            error=f"planning backend failed: {exc}",
        )
    if not quiet:
        print(
            f"[planner] proposal ({len(proposed.parts)} step/s): "
            f"{proposed.explanation or '(no explanation)'}"
        )
        for i, (playbook, _params) in enumerate(proposed.parts, 1):
            print(f"  {i}. {playbook.id:<18} <- {proposed.step_texts[i - 1]}")
    return orch.run_plan(
        text,
        list(proposed.parts),
        explanation=proposed.explanation,
        provider_label=f"{routing.mode}:{provider.name}/{provider.model}",
        dry_run=args.dry_run,
    )


def _cmd_ask(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("error: empty request", file=sys.stderr)
        return 2
    orch, _journal = _build_orchestrator(args)
    outcome = _ask_flow(orch, args, text)
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_chat(args: argparse.Namespace) -> int:
    args.json = False  # chat is a human surface
    orch, journal = _build_orchestrator(args)
    print("JARVIS chat — deterministic engine first; local/remote planner for the rest.")
    print("commands: /status /playbooks /tasks [n] /undo <id> /help — Ctrl-D or /quit exits")
    while True:
        try:
            line = input("jarvis> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        low = line.lower()
        if low in {"q", "quit", "exit", "/quit"}:
            return 0
        if low in {"h", "help", "/help"}:
            print(
                "Type a request in plain English. /tasks lists recent task ids; "
                "/undo <id> reverses one."
            )
            continue
        if low == "/status":
            _cmd_status(args)
            continue
        if low == "/playbooks":
            _cmd_playbooks(args)
            continue
        if low.startswith("/tasks"):
            tokens = line.split()
            limit = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else 10
            tasks = journal.recent_tasks(limit=limit)
            if not tasks:
                print("no tasks journaled yet")
            for t in tasks:
                print(
                    f"  {t['id']}  {t['status']:<11} {t['playbook_id']:<20} "
                    f"{str(t['intent_text'])[:60]}"
                )
            continue
        if low.startswith("/undo"):
            tokens = line.split()
            if len(tokens) != 2:
                print("usage: /undo <task-id>")
                continue
            _print_outcome(orch.undo(tokens[1]))
            continue
        _print_outcome(_ask_flow(orch, args, line))


def _cmd_file(args: argparse.Namespace) -> int:
    orch, _journal = _build_orchestrator(args)
    playbook = next((pb for pb in PLAYBOOKS if pb.id == "file.append"), None)
    if playbook is None:  # pragma: no cover - registry constant
        print("error: file.append playbook missing", file=sys.stderr)
        return 2
    text = " ".join(args.text)
    outcome = orch.run_plan(
        f"[file] append to {args.path}",
        [(playbook, {"path": args.path, "text": text})],
        provider_label="cli:file",
        dry_run=args.dry_run,
    )
    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        _print_outcome(outcome)
    return outcome.exit_code()


def _cmd_explain(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip()
    if not question:
        print("error: empty question", file=sys.stderr)
        return 2
    try:
        kb = load_kb()
    except Exception as exc:
        print(f"error: knowledge base unavailable: {exc}", file=sys.stderr)
        return 1
    result = kb_answer(question, kb)
    if args.json:
        print(json.dumps(result.to_json_dict(), indent=2))
        return 0 if result.status != "refused" else 2
    if result.status == "refused":
        print("I cannot answer this from cited knowledge and I will not guess.")
        print(f"hint     : {result.note}")
        return 2
    print(f"fact     : {result.fact_id}")
    print(f"claim    : {result.claim}")
    print(f"machine  : {result.machine_status} — {result.machine_detail}")
    print(f"note     : {result.note}")
    for src in result.sources:
        label = f"{src.get('kind')}: {src.get('ref')}"
        if src.get("url"):
            label += f" ({src['url']})"
        print(f"source   : {label}")
    return 0


def _cmd_facts(args: argparse.Namespace) -> int:
    try:
        kb = load_kb()
    except Exception as exc:
        print(f"error: knowledge base unavailable: {exc}", file=sys.stderr)
        return 1
    facts = kb.facts
    if args.topic:
        wanted = args.topic.lower()
        facts = tuple(f for f in facts if f.topic == wanted)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "id": f.id,
                        "topic": f.topic,
                        "claim": f.claim,
                        "sources": len(f.sources),
                        "local_check": bool(f.verify),
                    }
                    for f in facts
                ],
                indent=2,
            )
        )
        return 0
    if not facts:
        print(f"no facts for topic {args.topic!r} (topics: {sorted({f.topic for f in kb.facts})})")
        return 0
    print(f"knowledge base v{kb.version} — {len(facts)} fact(s):")
    for fact in facts:
        check = "local check" if fact.verify else "doc-sourced"
        print(f"  {fact.id:<28} [{fact.topic}] {fact.claim[:70]}… ({check})")
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

    p_ask = sub.add_parser(
        "ask",
        help="engine-first request; an LLM planner handles what playbooks cannot",
    )
    p_ask.add_argument("--dry-run", action="store_true", help="print the plan only")
    p_ask.add_argument("text", nargs="+", help="natural-language request")
    p_ask.set_defaults(func=_cmd_ask)

    p_chat = sub.add_parser("chat", help="interactive chat (engine + planner)")
    p_chat.set_defaults(func=_cmd_chat)

    p_file = sub.add_parser("file", help="guarded single-line file edits (ADR-0008)")
    p_file_sub = p_file.add_subparsers(dest="file_command", required=True)
    p_file_append = p_file_sub.add_parser(
        "append", help="append one line; a backup is taken and undo restores it"
    )
    p_file_append.add_argument("path", help="absolute target path (~ allowed)")
    p_file_append.add_argument("text", nargs="+", help="single-line text to append")
    p_file_append.add_argument("--dry-run", action="store_true")
    p_file_append.set_defaults(func=_cmd_file)

    p_explain = sub.add_parser(
        "explain", help="answer a question from cited knowledge (cite-or-abstain)"
    )
    p_explain.add_argument("question", nargs="+", help="e.g. 'what is ostype'")
    p_explain.set_defaults(func=_cmd_explain)

    p_facts = sub.add_parser("facts", help="browse the knowledge base")
    p_facts.add_argument("topic", nargs="?", default=None, help="filter by topic")
    p_facts.set_defaults(func=_cmd_facts)

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
