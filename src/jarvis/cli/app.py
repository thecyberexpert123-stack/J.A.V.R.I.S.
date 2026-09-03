"""JARVIS command-line interface (argparse; ADR-0005 — stdlib only at M1).

Exit codes: 0 success/dry-run · 1 execution or verification failure ·
2 refused (policy, protected set, unmatched intent, invalid input) ·
130 interrupted by signal.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import cast

from jarvis import __version__
from jarvis.context.store import ContextStore, default_context_path
from jarvis.core.fingerprint import build_profile
from jarvis.core.orchestrator import Orchestrator, TaskOutcome
from jarvis.execution.runner import LocalRunner
from jarvis.gui.backends import GuiBackendError
from jarvis.gui.service import GuiPolicyError, GuiService, GuiUnavailable
from jarvis.gui.wizard import report as wizard_report
from jarvis.gui.wizard import run_checks as wizard_checks
from jarvis.journal.sqlite import Journal, default_db_path
from jarvis.knowledge.answers import answer as kb_answer
from jarvis.knowledge.store import load_kb
from jarvis.planner.llm import PlanRefused, build_plan
from jarvis.planner.models import TaskStatus
from jarvis.planner.playbooks import PLAYBOOKS, match_intent
from jarvis.providers.base import ProviderError
from jarvis.providers.router import plan_routing
from jarvis.safety.approval import ApprovalPolicy, ApprovalRefused
from jarvis.safety.disclosure import blast_radius
from jarvis.safety.selftest import run_battery
from jarvis.suggest.engine import generate_suggestions
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
    return Orchestrator(
        profile,
        journal,
        runner,
        policy,
        echo=echo,
        cautious_ok=getattr(args, "cautious_ok", False),
    ), journal


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
    try:
        from jarvis.gui.detect import probe as gui_probe

        gui_env = gui_probe()
        print(
            f"gui             : {gui_env.session_type} ({gui_env.desktop}),"
            f" {len(gui_env.tools)} GUI tool(s) on PATH"
        )
    except Exception as exc:  # status must never crash
        print(f"gui             : probe failed ({exc})")
    print(f"cautious mode   : {'ON' if _cautious_path().exists() else 'OFF'}")
    context_rows = len(ContextStore(default_context_path()).feedback_rows())
    print(f"context store   : {context_rows} feedback entr{'y' if context_rows == 1 else 'ies'}")
    print(f"journal         : {default_db_path()}")
    return 0


def _cmd_do(args: argparse.Namespace) -> int:
    text = " ".join(args.text).strip()
    if not text:
        print("error: empty request", file=sys.stderr)
        return 2
    orch, _journal = _build_orchestrator(args)
    if args.preview:
        outcome = orch.run_intent(text, dry_run=True)
        radius = blast_radius(outcome.steps)
        if args.json:
            print(json.dumps({"preview": outcome.to_json_dict(), "blast_radius": radius}, indent=2))
            return outcome.exit_code()
        print("[preview] plan (nothing executed, nothing asked):")
        for step in outcome.steps:
            step_argv = step["argv"]
            assert isinstance(step_argv, list)
            print(f"  {step['seq']}. {step['description']}")
            print(f"       $ {' '.join(str(a) for a in step_argv)}")
        print(
            f"  blast radius: tier={radius['max_tier']} root={radius['requires_root']} "
            f"network={radius['network']}"
        )
        commands = radius["commands"]
        assert isinstance(commands, list)
        print(f"  commands: {', '.join(str(c) for c in commands) or '(none)'}")
        paths_map = radius["paths"]
        assert isinstance(paths_map, dict)
        for klass, paths_ in paths_map.items():
            if paths_:
                assert isinstance(paths_, list)
                print(f"  {klass} paths: {', '.join(str(p_) for p_ in paths_)}")
        print("  execute by re-running with --yes (review the plan above first).")
        return outcome.exit_code()
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


def _cmd_gui(args: argparse.Namespace) -> int:
    kind = args.gui_command

    if kind == "status":
        service = _build_gui(args)
        data = service.status()
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        session = data["session"]
        assert isinstance(session, dict)
        print(f"session   : {session['session_type']} ({session['desktop']})")
        print(f"tools     : {', '.join(session['tools']) or '(none)'}")
        caps = data["capabilities"]
        assert isinstance(caps, dict)
        for cap, binding in caps.items():
            assert isinstance(binding, dict)
            mark = binding.get("backend") or "unavailable"
            print(f"  {cap:<11}: {mark} — {binding.get('reason')}")
        atspi = data["atspi"]
        assert isinstance(atspi, dict)
        print(f"  atspi      detail: {atspi['detail']}")
        if data.get("hint"):
            print(f"hint      : {data['hint']}")
        return 0

    if kind == "wizard":
        checks = wizard_checks()
        if args.json:
            print(
                json.dumps(
                    [
                        {"name": c.name, "ok": c.ok, "detail": c.detail, "fix": c.fix}
                        for c in checks
                    ],
                    indent=2,
                )
            )
            return 0
        print(wizard_report(checks))
        return 0

    if kind == "windows":
        service = _build_gui(args)
        try:
            windows = service.windows()
        except (GuiUnavailable, GuiPolicyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        except GuiBackendError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(
                json.dumps(
                    [{"id": w.id, "title": w.title, "backend": w.backend} for w in windows],
                    indent=2,
                )
            )
        else:
            for w in windows:
                print(f"  {w.id:<12} {w.title}")
        return 0

    service = _build_gui(args)
    try:
        if kind == "open":
            outcome = service.open_app(args.argv)
        elif kind == "focus":
            outcome = service.focus(args.title)
        elif kind == "type":
            outcome = service.type_text(" ".join(args.text))
        elif kind == "key":
            outcome = service.key(args.combo)
        elif kind == "screenshot":
            outcome = service.screenshot(Path(args.path))
        elif kind == "close":
            outcome = service.close(args.title)
        elif kind == "describe":
            question = " ".join(args.question).strip() or (
                "Describe what is on this screen concisely."
            )
            text = service.describe(Path(args.path), question)
            if args.json:
                print(json.dumps({"description": text}, indent=2))
            else:
                print(text)
            return 0
        else:  # pragma: no cover - argparse guards this
            return 2
    except ApprovalRefused as exc:
        print(f"refused  : {exc}", file=sys.stderr)
        return 2
    except (GuiPolicyError, GuiUnavailable) as exc:
        print(f"error    : {exc}", file=sys.stderr)
        return 2
    except GuiBackendError as exc:
        print(f"error    : {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(outcome.to_json_dict(), indent=2))
    else:
        print(f"action    : {outcome.action}")
        print(f"status    : {outcome.status}")
        if outcome.target:
            print(f"target    : {outcome.target}")
        print(f"detail    : {outcome.detail}")
    return 0


def _build_gui(args: argparse.Namespace) -> GuiService:
    journal = Journal(default_db_path())
    runner = LocalRunner()
    policy = ApprovalPolicy(yes=args.yes, silent=bool(args.json))
    return GuiService(runner, policy, journal, echo=not args.json)


def _cmd_safety_check(args: argparse.Namespace) -> int:
    results = run_battery()
    if args.json:
        print(
            json.dumps(
                [{"name": r.name, "ok": r.ok, "detail": r.detail} for r in results],
                indent=2,
            )
        )
    else:
        print("JARVIS safety self-test (real components, execution-blocked runner):")
        for result in results:
            mark = "PASS" if result.ok else "FAIL"
            print(f"  [{mark}] {result.name}: {result.detail}")
    failed = sum(1 for r in results if not r.ok)
    verdict = "SAFETY CHECK PASSED" if failed == 0 else f"SAFETY CHECK FAILED ({failed})"
    if args.json:
        print(json.dumps({"verdict": verdict, "failed": failed}, indent=2))
    else:
        print(f"== {verdict} ==")
    return 0 if failed == 0 else 1


def _cautious_path() -> Path:
    from jarvis.journal.sqlite import state_dir

    return state_dir() / "cautious"


def _cmd_cautious(args: argparse.Namespace) -> int:
    marker = _cautious_path()
    if args.action in ("on", "off"):
        marker.parent.mkdir(parents=True, exist_ok=True)
        if args.action == "on":
            marker.write_text("on\n", encoding="utf-8")
        else:
            marker.unlink(missing_ok=True)
    active = marker.exists()
    if args.json:
        print(json.dumps({"cautious": active}, indent=2))
        return 0
    print(f"cautious mode : {'ON' if active else 'OFF'}")
    if not active:
        print("  (recommended while JARVIS is new on this machine: jarvis cautious on)")
    if active:
        print(
            "  T2+ actions are blocked; review plans with --preview, then run "
            "once with --cautious-ok, or disable: jarvis cautious off"
        )
    return 0


def _suggest_target() -> list[dict[str, object]]:
    from jarvis.core.fingerprint import build_profile
    from jarvis.journal.sqlite import Journal

    journal = Journal(default_db_path())
    context = ContextStore(default_context_path())
    suggestions = generate_suggestions(build_profile(), journal, context)
    return [s.to_json_dict() for s in suggestions]


def _cmd_suggest(args: argparse.Namespace) -> int:
    action = getattr(args, "suggest_command", None)

    if action in ("accept", "reject"):
        if action == "reject" and not args.reason:
            print(
                "error: rejecting without a reason wastes the calibration signal "
                '(use --reason "...")',
                file=sys.stderr,
            )
            return 2
        context = ContextStore(default_context_path())
        suggestion = _lookup_suggestion(args.suggestion_id) if action == "accept" else None
        if action == "accept" and suggestion is None:
            print(
                f"error: no current suggestion {args.suggestion_id!r} (list with: jarvis suggest)",
                file=sys.stderr,
            )
            return 2
        try:
            context.record_feedback(
                args.suggestion_id,
                "accepted" if action == "accept" else "rejected",
                reason=args.reason,
                title=str(suggestion["title"]) if suggestion else "",
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if suggestion is not None:
            print(f"accepted: {suggestion['title']}")
            print("review first, then run:")
            print(f"  {suggestion['command']}")
        else:
            print(f"rejected {args.suggestion_id} — suppressed from future suggestions")
            print(f"reason recorded: {args.reason}")
        return 0

    suggestions = _suggest_target()
    if args.json:
        print(json.dumps(suggestions, indent=2))
        return 0
    if not suggestions:
        print(
            "no suggestions right now — everything I can see is already handled "
            "or nothing matches the evidence rules."
        )
        return 0
    print("suggestions (evidence-backed; I will not run anything):")
    for suggestion in suggestions:
        assert isinstance(suggestion, dict)
        evidence_list = suggestion["evidence"]
        assert isinstance(evidence_list, list)
        print(f"  [{suggestion['id']}] {suggestion['title']}")
        print(f"      {suggestion['detail']}")
        for evidence in evidence_list:
            assert isinstance(evidence, dict)
            kind = evidence.get("kind", "")
            detail = evidence.get("detail") or evidence.get("claim", "")
            print(f"      evidence: {kind}: {detail}")
        print(f"      accept: jarvis suggest accept {suggestion['id']}")
        print(f'      reject: jarvis suggest reject {suggestion["id"]} --reason "..."')
    return 0


def _lookup_suggestion(suggestion_id: str) -> dict[str, object] | None:
    from jarvis.core.fingerprint import build_profile
    from jarvis.journal.sqlite import Journal

    journal = Journal(default_db_path())
    context = ContextStore(default_context_path())
    for suggestion in generate_suggestions(build_profile(), journal, context):
        data = suggestion.to_json_dict()
        if data["id"] == suggestion_id:
            return data
    return None


def _cmd_context(args: argparse.Namespace) -> int:
    context = ContextStore(default_context_path())
    rows = context.feedback_rows()
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not rows:
        print("context store: empty (no suggestion feedback recorded yet)")
        return 0
    print(f"context store — {len(rows)} feedback entr{'y' if len(rows) == 1 else 'ies'}:")
    for row in rows:
        print(
            f"  {row['created_utc']}  {row['decision']:<8} {row['suggestion_id']}"
            + (f" — {row['reason']}" if row["reason"] else "")
        )
    print("this store tunes suggestions only; it never grants authority to act (ADR-0012).")
    return 0


def _cmd_mcp_serve(args: argparse.Namespace) -> int:
    """Serve the MCP tool/resource surface on stdio (ADR-0013 M9a)."""
    from jarvis.cli.mcp_server import MCPServer

    print(
        "[jarvis] MCP server on stdio: newline-delimited JSON-RPC 2.0; "
        "consent tiers unchanged (T2 needs per-call allow:true, T3 refused)",
        file=sys.stderr,
    )
    stdin = cast(io.TextIOBase, sys.stdin)
    stdout = cast(io.TextIOBase, sys.stdout)
    return MCPServer(stdin, stdout).serve()


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
    p_do.add_argument(
        "--preview",
        action="store_true",
        help="show the full plan + blast radius; never asks, never executes",
    )
    p_do.add_argument(
        "--cautious-ok",
        action="store_true",
        help="execute this one T2+ action while cautious mode is ON",
    )
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

    p_gui = sub.add_parser(
        "gui", help="desktop control: capability matrix + consent-gated actions (ADR-0010)"
    )
    p_gui_sub = p_gui.add_subparsers(dest="gui_command", required=True)
    for name, help_text in (
        ("status", "show this machine's GUI capability matrix"),
        ("wizard", "ydotool readiness wizard with distro-specific fixes"),
        ("windows", "list windows via the session backend"),
    ):
        p_sub = p_gui_sub.add_parser(name, help=help_text)
        p_sub.set_defaults(func=_cmd_gui, gui_command=name)
    p_open = p_gui_sub.add_parser("open", help="launch an app detached (T2, consent-gated)")
    p_open.add_argument("argv", nargs="+", help="app name + args, PATH lookup only")
    p_open.set_defaults(func=_cmd_gui, gui_command="open")
    p_focus = p_gui_sub.add_parser("focus", help="focus a window by title (T2)")
    p_focus.add_argument("title", help="case-insensitive substring; must be unique")
    p_focus.set_defaults(func=_cmd_gui, gui_command="focus")
    p_type = p_gui_sub.add_parser(
        "type", help="type text into the FOCUSED window (T2; target disclosed first)"
    )
    p_type.add_argument("text", nargs="+", help="single-line text, no control chars")
    p_type.set_defaults(func=_cmd_gui, gui_command="type")
    p_key = p_gui_sub.add_parser("key", help="send a key combo to the FOCUSED window (T2)")
    p_key.add_argument("combo", help="e.g. Return, ctrl+c, super")
    p_key.set_defaults(func=_cmd_gui, gui_command="key")
    p_shot = p_gui_sub.add_parser("screenshot", help="capture the screen (T2: privacy)")
    p_shot.add_argument("path", help="output PNG path")
    p_shot.set_defaults(func=_cmd_gui, gui_command="screenshot")
    p_close = p_gui_sub.add_parser("close", help="close a window (graceful WM delete, T2)")
    p_close.add_argument("title", help="case-insensitive substring; must be unique")
    p_close.set_defaults(func=_cmd_gui, gui_command="close")
    p_describe = p_gui_sub.add_parser(
        "describe", help="describe a screenshot with a local vision model (abstains if absent)"
    )
    p_describe.add_argument("path", help="PNG path (e.g. from 'jarvis gui screenshot')")
    p_describe.add_argument("question", nargs="*", default=[], help="optional question")
    p_describe.set_defaults(func=_cmd_gui, gui_command="describe")

    p_safety = sub.add_parser(
        "safety-check",
        help="prove the refusal guards are alive on this machine (no side effects)",
    )
    p_safety.set_defaults(func=_cmd_safety_check)

    p_cautious = sub.add_parser(
        "cautious",
        help="early-days guard: block T2+ actions until you trust this machine's setup",
    )
    p_cautious.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"])
    p_cautious.set_defaults(func=_cmd_cautious)

    p_suggest = sub.add_parser(
        "suggest",
        help="evidence-backed suggestions (read-only; nothing runs without you)",
    )
    p_suggest_sub = p_suggest.add_subparsers(dest="suggest_command")
    p_suggest_acc = p_suggest_sub.add_parser(
        "accept", help="accept a suggestion (prints the command)"
    )
    p_suggest_acc.add_argument("suggestion_id")
    p_suggest_acc.set_defaults(func=_cmd_suggest, reason="")
    p_suggest_rej = p_suggest_sub.add_parser(
        "reject", help="reject a suggestion (suppressed henceforth)"
    )
    p_suggest_rej.add_argument("suggestion_id")
    p_suggest_rej.add_argument("--reason", default="", help="why (calibration signal)")
    p_suggest_rej.set_defaults(func=_cmd_suggest)
    p_suggest.set_defaults(func=_cmd_suggest)

    p_context = sub.add_parser("context", help="inspect the local context store (M8b grows it)")
    p_context_sub = p_context.add_subparsers(dest="context_command")
    p_context_show = p_context_sub.add_parser("show", help="show everything stored about you")
    p_context_show.set_defaults(func=_cmd_context)
    p_context.set_defaults(func=_cmd_context)

    p_mcp = sub.add_parser("mcp", help="Model Context Protocol surface (ADR-0013 M9a)")
    p_mcp_sub = p_mcp.add_subparsers(dest="mcp_command", required=True)
    p_mcp_serve = p_mcp_sub.add_parser(
        "serve",
        help=(
            "serve fixed tools (status/facts/explain/suggest/preview/do) and "
            "resources over stdio JSON-RPC; an MCP client fronts the same "
            "kernel — consent tiers unchanged, no passthrough exec"
        ),
    )
    p_mcp_serve.set_defaults(func=_cmd_mcp_serve)

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
