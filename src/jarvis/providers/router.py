"""Provider routing (ADR-0003: hybrid, local-first).

Precedence for *planning* (execution safety is independent of this choice —
every plan still passes the tier gate):
1. deterministic engine (decided by the caller via playbook match),
2. local Ollama when reachable,
3. remote OpenAI-compatible endpoint when configured AND not disabled,
4. none → the agent refuses honestly instead of guessing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from jarvis.providers.base import Provider
from jarvis.providers.ollama import OllamaProvider
from jarvis.providers.openai_compatible import DEFAULT_BASE_URL, KEY_ENV, OpenAICompatibleProvider

REMOTE_DISABLE_ENV = "JARVIS_REMOTE_LLM"
NO_AI_ENV = "JARVIS_NO_AI"


@dataclass(frozen=True)
class Routing:
    """Outcome of the planning-backend decision."""

    mode: str  # "local" | "remote" | "none"
    provider: Provider | None
    note: str


def remote_allowed(env: dict[str, str] | None = None) -> bool:
    source = env if env is not None else dict(os.environ)
    return source.get(REMOTE_DISABLE_ENV, "1") != "0"


def plan_routing(env: dict[str, str] | None = None, *, enabled: bool = True) -> Routing:
    """Decide which planning backend to use (cheap availability probes only).

    ``enabled=False`` (CLI ``--no-ai`` / ``JARVIS_NO_AI=1`` — ADR-0014 D7)
    returns a "none" routing without probing anything: the no-AI contract is
    a declared operator mode, not an accident of a missing backend.
    """
    env_map = env or {}
    if not enabled:
        return Routing("none", None, f"AI disabled by operator (--no-ai or {NO_AI_ENV}=1)")
    local = OllamaProvider(host=env_map.get("OLLAMA_HOST"), model=env_map.get("JARVIS_LOCAL_MODEL"))
    if local.available():
        return Routing("local", local, "local-first policy (ADR-0003)")

    if not remote_allowed(env):
        return Routing(
            "none",
            None,
            "no local model detected and remote planning disabled (JARVIS_REMOTE_LLM=0)",
        )

    remote = OpenAICompatibleProvider()
    if remote.available():
        return Routing("remote", remote, "no local model detected; remote endpoint configured")
    return Routing(
        "none",
        None,
        f"no local Ollama detected and no remote key configured ({KEY_ENV}); "
        f"remote base URL would be {DEFAULT_BASE_URL}",
    )
