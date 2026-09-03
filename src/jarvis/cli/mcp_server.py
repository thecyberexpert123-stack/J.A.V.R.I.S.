"""MCP server surface (ADR-0013 M9a) — Model Context Protocol over stdio.

Harm model: an MCP client is just another untrusted-ingress front-end,
identical in standing to the CLI. Nothing here bypasses the kernel — the
tool set is fixed and narrow, every mutation flows through the same
Orchestrator → tier → consent → journal path as `jarvis do`, and there is
deliberately NO free-form-exec passthrough tool. T2 (system-level) acts
require explicit per-call `allow: true` (mapped to the same ApprovalPolicy
`--yes` semantics the CLI uses); T3 is refused unconditionally.

Transport: newline-delimited JSON-RPC 2.0 on stdio (MCP stdio transport).
stdout carries protocol frames only; every diagnostic goes to stderr.
Implementation is stdlib-only by design (ADR-0005 dependency discipline).
"""

from __future__ import annotations

import io
import json
import re
import sys
from collections.abc import Callable

from jarvis import __version__
from jarvis.context.store import ContextStore, default_context_path
from jarvis.core.fingerprint import build_profile
from jarvis.core.orchestrator import Orchestrator
from jarvis.execution.runner import LocalRunner
from jarvis.journal.sqlite import Journal, default_db_path
from jarvis.knowledge.answers import answer as kb_answer
from jarvis.knowledge.store import load_kb
from jarvis.safety.approval import ApprovalPolicy
from jarvis.safety.disclosure import blast_radius
from jarvis.suggest.engine import generate_suggestions

_FALLBACK_PROTOCOL_VERSION = "2024-11-05"
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

# JSON-RPC 2.0 error codes used by MCP.
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602

_REFUSAL_HINT = (
    "review the plan with jarvis_preview, then re-call jarvis_do with "
    '"allow": true to consent explicitly'
)

_BOOL_SCHEMA = {"type": "boolean"}
_STR_SCHEMA = {"type": "string"}

TOOL_SPECS: tuple[dict[str, object], ...] = (
    {
        "name": "jarvis_status",
        "description": (
            "Machine fingerprint (read-only): distro, init system, package "
            "manager, session, privileges. Never acts."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "jarvis_facts",
        "description": (
            "List the cited knowledge base (read-only). Every fact carries "
            "sources; the store refuses uncited facts by design."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"topic": _STR_SCHEMA},
            "required": [],
        },
    },
    {
        "name": "jarvis_explain",
        "description": (
            "Cite-or-abstain answers from the knowledge base. Questions "
            "outside the KB are refused, never guessed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"question": _STR_SCHEMA},
            "required": ["question"],
        },
    },
    {
        "name": "jarvis_suggest",
        "description": (
            "Evidence-backed maintenance suggestions (read-only). JARVIS "
            "never runs suggestions itself; feedback tunes future suggestions."
        ),
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "jarvis_preview",
        "description": (
            "Plan a request without executing or asking: full steps plus "
            "blast radius (tier, root, network, paths)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"request": _STR_SCHEMA},
            "required": ["request"],
        },
    },
    {
        "name": "jarvis_do",
        "description": (
            "Play a natural-language request through the safety kernel "
            "(deterministic playbook only — never free-form commands). "
            "Tiers apply exactly as on the CLI: T2 requires explicit "
            '"allow": true (consent is logged to the journal); T3 is '
            "refused unconditionally."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"request": _STR_SCHEMA, "allow": _BOOL_SCHEMA},
            "required": ["request"],
        },
    },
)

RESOURCES: tuple[dict[str, object], ...] = (
    {
        "uri": "kb://facts",
        "name": "Cited knowledge base",
        "description": "All facts with their sources (application/json).",
        "mimeType": "application/json",
    },
    {
        "uri": "journal://tasks",
        "name": "Journal — recent tasks",
        "description": "Recent journaled tasks with status and tier (application/json).",
        "mimeType": "application/json",
    },
)


def _facts_payload(topic: str | None) -> dict[str, object]:
    kb = load_kb()
    facts = kb.facts
    if topic is not None:
        wanted = topic.lower()
        facts = tuple(f for f in facts if f.topic == wanted)
    return {
        "kb_version": kb.version,
        "count": len(facts),
        "facts": [
            {
                "id": f.id,
                "topic": f.topic,
                "claim": f.claim,
                "sources": len(f.sources),
                "local_check": bool(f.verify),
            }
            for f in facts
        ],
    }


def _build_orchestrator(allow: bool) -> Orchestrator:
    """Same construction as the CLI's, with MCP consent semantics.

    `allow` maps onto the CLI's `--yes`; stdin is always a non-tty so a
    T2 plan without consent is refused deterministically instead of
    hanging the protocol stream.
    """
    profile = build_profile()
    journal = Journal(default_db_path())
    runner = LocalRunner()
    policy = ApprovalPolicy(yes=allow, silent=True, stdin=io.StringIO())
    return Orchestrator(profile, journal, runner, policy, echo=False)


def _tool_status(_args: dict[str, object]) -> tuple[object, bool]:
    return build_profile().to_dict(), False


def _tool_facts(args: dict[str, object]) -> tuple[object, bool]:
    topic = args.get("topic")
    if topic is not None and not isinstance(topic, str):
        return {"error": "topic must be a string"}, True
    return _facts_payload(topic), False


def _tool_explain(args: dict[str, object]) -> tuple[object, bool]:
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return {"error": "question must be a non-empty string"}, True
    result = kb_answer(question, load_kb())
    return result.to_json_dict(), result.status == "refused"


def _tool_suggest(_args: dict[str, object]) -> tuple[object, bool]:
    journal = Journal(default_db_path())
    context = ContextStore(default_context_path())
    suggestions = [
        s.to_json_dict() for s in generate_suggestions(build_profile(), journal, context)
    ]
    return (
        {
            "suggestions": suggestions,
            "note": "read-only; JARVIS does not execute suggestions",
        },
        False,
    )


def _tool_preview(args: dict[str, object]) -> tuple[object, bool]:
    request = args.get("request")
    if not isinstance(request, str) or not request.strip():
        return {"error": "request must be a non-empty string"}, True
    orch = _build_orchestrator(allow=False)
    outcome = orch.run_intent(request, dry_run=True)
    return (
        {
            "preview": outcome.to_json_dict(),
            "blast_radius": blast_radius(outcome.steps),
        },
        outcome.exit_code() != 0,
    )


def _tool_do(args: dict[str, object]) -> tuple[object, bool]:
    request = args.get("request")
    if not isinstance(request, str) or not request.strip():
        return {"error": "request must be a non-empty string"}, True
    allow = args.get("allow", False)
    if not isinstance(allow, bool):
        return {"error": "allow must be a boolean"}, True
    orch = _build_orchestrator(allow=allow)
    outcome = orch.run_intent(request)
    payload: dict[str, object] = outcome.to_json_dict()
    # The kernel returns consent refusals as REFUSED outcomes (never raises);
    # restate the CLI's "--yes" wording in this surface's terms.
    if outcome.status.value == "refused" and "approval" in str(outcome.error or ""):
        payload["hint"] = _REFUSAL_HINT
    return {"outcome": payload}, outcome.exit_code() != 0


_TOOL_HANDLERS: dict[str, Callable[[dict[str, object]], tuple[object, bool]]] = {
    "jarvis_status": _tool_status,
    "jarvis_facts": _tool_facts,
    "jarvis_explain": _tool_explain,
    "jarvis_suggest": _tool_suggest,
    "jarvis_preview": _tool_preview,
    "jarvis_do": _tool_do,
}


class MCPServer:
    """Frame-loop over a newline-delimited JSON-RPC 2.0 byte stream."""

    def __init__(self, stdin: io.TextIOBase, stdout: io.TextIOBase) -> None:
        self._stdin = stdin
        self._stdout = stdout

    def serve(self) -> int:
        """Read frames until EOF; returns a process exit code."""
        for raw in self._stdin:
            line = raw.strip()
            if not line:
                continue
            response = self.handle_line(line)
            if response is not None:
                self._stdout.write(response + "\n")
                self._stdout.flush()
        return 0

    # -- protocol ----------------------------------------------------------

    def handle_line(self, line: str) -> str | None:
        """Handle one frame; returns the response frame or None (notification)."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            return self._error(None, PARSE_ERROR, f"parse error: {exc}")
        if isinstance(msg, list):
            return self._error(None, INVALID_REQUEST, "batch requests are not supported")
        if (
            not isinstance(msg, dict)
            or msg.get("jsonrpc") != "2.0"
            or not isinstance(msg.get("method"), str)
        ):
            return self._error(None, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        method = msg["method"]
        assert isinstance(method, str)
        mid = msg.get("id")
        notification = "id" not in msg

        if method == "initialize":
            return self._respond(mid, self._initialize(msg.get("params")))
        if method == "notifications/initialized":
            return None
        if method == "ping":
            return None if notification else self._respond(mid, {})
        if method == "tools/list":
            return None if notification else self._respond(mid, {"tools": list(TOOL_SPECS)})
        if method == "tools/call":
            return self._tools_call(msg.get("params"), mid)
        if method == "resources/list":
            return None if notification else self._respond(mid, {"resources": list(RESOURCES)})
        if method == "resources/read":
            return self._resources_read(msg.get("params"), mid)
        if not notification:
            return self._error(mid, METHOD_NOT_FOUND, f"method not found: {method}")
        return None

    # -- method bodies -----------------------------------------------------

    def _initialize(self, params: object) -> dict[str, object]:
        requested = params.get("protocolVersion") if isinstance(params, dict) else None
        if isinstance(requested, str) and _DATE_RE.fullmatch(requested):
            version = requested  # core surface (tools/resources/ping) is stable across versions
        else:
            version = _FALLBACK_PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {"tools": {}, "resources": {}},
            "serverInfo": {"name": "jarvis", "version": __version__},
        }

    def _tools_call(self, params: object, mid: object) -> str:
        if not isinstance(params, dict):
            return self._error(mid, INVALID_PARAMS, "params must be an object")
        name = params.get("name")
        arguments = params.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            return self._error(mid, INVALID_PARAMS, "name (string) and arguments (object) required")
        handler = _TOOL_HANDLERS.get(name)
        if handler is None:
            return self._error(mid, INVALID_PARAMS, f"unknown tool: {name}")
        try:
            payload, is_error = handler(arguments)
        except Exception as exc:  # one bad tool call must not kill the session
            print(f"[jarvis-mcp] tool {name} failed: {exc}", file=sys.stderr)
            payload = {"error": f"internal error: {exc}"}
            is_error = True
        text = json.dumps(payload, indent=2, sort_keys=True)
        return self._respond(
            mid,
            {"content": [{"type": "text", "text": text}], "isError": is_error},
        )

    def _resources_read(self, params: object, mid: object) -> str:
        if not isinstance(params, dict) or not isinstance(params.get("uri"), str):
            return self._error(mid, INVALID_PARAMS, "uri (string) required")
        uri = params["uri"]
        assert isinstance(uri, str)
        if uri == "kb://facts":
            text = json.dumps(_facts_payload(None), indent=2, sort_keys=True)
        elif uri == "journal://tasks":
            tasks = Journal(default_db_path()).recent_tasks(limit=50)
            text = json.dumps(tasks, indent=2, sort_keys=True)
        else:
            return self._error(mid, INVALID_PARAMS, f"unknown resource: {uri}")
        return self._respond(
            mid,
            {"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]},
        )

    # -- framing -----------------------------------------------------------

    def _respond(self, mid: object, result: object) -> str:
        return json.dumps({"jsonrpc": "2.0", "id": mid, "result": result})

    def _error(self, mid: object, code: int, message: str) -> str:
        return json.dumps(
            {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}
        )
