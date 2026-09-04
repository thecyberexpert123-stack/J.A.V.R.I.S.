"""LLM planner (pipeline stages GROUND/PLAN when the engine has no match).

Security architecture (ADR-0007): the model **proposes, the kernel disposes**.
The LLM never emits commands, argv, flags, or paths — only short natural-
language intents which MUST pass the very same strict playbook matchers the
deterministic engine uses. Anything unparseable, out of vocabulary, or
injection-shaped is refused, never guessed. Output contract: strict JSON
`{"explanation": str, "steps": [str, ...]}`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from jarvis.planner.playbooks import Params, Playbook, match_intent
from jarvis.providers.base import Provider
from jarvis.providers.breaker import ProviderBreaker, guarded_complete

MAX_STEPS = 6
MAX_REQUEST_CHARS = 2000
MAX_STEP_CHARS = 120

# ADR-0014 D4: the planner wire is schema-constrained (Ollama `format`,
# OpenAI-compatible `json_schema`), and the strict post-validation below is
# unchanged — schema-constrained output is still untrusted input.
PLAN_JSON_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
        "steps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["steps"],
}

_SYSTEM_PROMPT = """You are the planner inside JARVIS, a Linux automation agent.
Respond with STRICT JSON only - no markdown, no prose outside the JSON:
{"explanation": "<one short sentence>", "steps": ["<intent>", ...]}
Rules:
- Each step must be an English imperative drawn ONLY from the supported intent patterns below.
- Never include shell syntax, paths, options, flags, pipes, semicolons, or package versions.
- Use 1 to {max_steps} steps; prefer fewer.
- If the request cannot be expressed with the supported intents, use an empty "steps" list.
Supported intent patterns:
- install <package(s)>                 e.g. "install htop", "install htop and curl"
- remove <package(s)> / uninstall <package(s)>
- search <terms>                       e.g. "search text editor"
- info <package>
- update                               (refresh the package index)
- upgrade (the) system                 (upgrade installed packages)
- status of <unit> / start <unit> / enable <unit>   (systemd only)
- system info
""".replace("{max_steps}", str(MAX_STEPS))


@dataclass(frozen=True)
class ProposedPlan:
    """A validated LLM proposal: playbook invocations, never raw commands."""

    explanation: str
    parts: tuple[tuple[Playbook, Params], ...]
    step_texts: tuple[str, ...]
    provider_name: str
    provider_model: str


class PlanRefused(RuntimeError):
    """The model's proposal failed validation; refused, never guessed.

    ``kind`` (ADR-0014 D1): ``"malformed"`` — the model misbehaved (bad JSON,
    out-of-vocabulary steps) and counts as a breaker failure;
    ``"unexpressible"`` — the model honestly reported it cannot express the
    request with supported intents; the model is healthy, so this must NOT
    trip the breaker.
    """

    def __init__(self, reason: str, hint: str = "", *, kind: str = "malformed") -> None:
        super().__init__(reason)
        self.hint = hint
        self.kind = kind


def build_plan(
    request: str, provider: Provider, *, breaker: ProviderBreaker | None = None
) -> ProposedPlan:
    """Ask *provider* for a plan and strictly validate it against the catalog."""
    content = guarded_complete(
        provider,
        _SYSTEM_PROMPT,
        request[:MAX_REQUEST_CHARS],
        breaker,
        schema=PLAN_JSON_SCHEMA,
    )

    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        snippet = content[:120].replace("\n", " ")
        raise PlanRefused(
            "planner output was not valid JSON; refusing rather than guessing",
            hint=f"raw output began with: {snippet!r} ({exc.msg})",
        ) from exc

    if not isinstance(data, dict):
        raise PlanRefused("planner output was not a JSON object")

    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list):
        raise PlanRefused('planner output missing a "steps" list')
    if not raw_steps:
        raise PlanRefused(
            "planner returned no steps (it could not express the request with supported intents)",
            hint="try rephrasing, or use a supported playbook (see: jarvis playbooks)",
            kind="unexpressible",
        )
    if len(raw_steps) > MAX_STEPS:
        raise PlanRefused(f"planner proposed {len(raw_steps)} steps; maximum is {MAX_STEPS}")

    explanation = data.get("explanation", "")
    if not isinstance(explanation, str):
        explanation = ""

    parts: list[tuple[Playbook, Params]] = []
    texts: list[str] = []
    for index, raw in enumerate(raw_steps, 1):
        if not isinstance(raw, str) or not raw.strip():
            raise PlanRefused(f"planner step {index} is empty or not a string")
        text = raw.strip()
        if len(text) > MAX_STEP_CHARS:
            raise PlanRefused(
                f"planner step {index} is implausibly long for an intent ({len(text)} chars)"
            )
        try:
            matched = match_intent(text)
        except Exception as exc:  # InvalidInputError from matcher validation
            raise PlanRefused(
                f"planner step {index} failed validation: {exc}",
                hint="planner output must be plain intents; never commands or flags",
            ) from exc
        if matched is None:
            raise PlanRefused(
                f"planner step {index} does not map to a supported playbook: {text[:80]!r}",
                hint="supported intents: jarvis playbooks",
            )
        playbook, params = matched
        parts.append((playbook, params))
        texts.append(text)

    return ProposedPlan(
        explanation=explanation.strip()[:200],
        parts=tuple(parts),
        step_texts=tuple(texts),
        provider_name=provider.name,
        provider_model=provider.model,
    )
