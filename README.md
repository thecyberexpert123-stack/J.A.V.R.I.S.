# JARVIS

> **J**ust **A** **R**ather **V**ery **I**ntelligent **S**ystem — an AI automation agent for Linux.
> Plans, executes, and **verifies** real tasks on any Tier-1 distribution — with a safety kernel,
> an audit journal, and no blind execution. Ever.
>
> *(Repository keeps its original name `J.A.V.R.I.S.`; the canonical project name is JARVIS per owner ruling, 2026-09-02.)*

**Status: `M5 GUI` (v0.5.0) — engine + LLM planner + cited knowledge + capability-matrix GUI control behind a fault-tested safety kernel. Eval-verified on 5 distros; 15-task GUI suite on real X in CI. Reports: `evals/results/`.**
Plan accepted 2026-09-02; open decisions recorded in [`docs/PLAN.md` §13](docs/PLAN.md).

| | |
|---|---|
| Plan & architecture | [`docs/PLAN.md`](docs/PLAN.md) |
| Research & evidence | [`docs/RESEARCH.md`](docs/RESEARCH.md) |
| Change log | [`CHANGELOG.md`](CHANGELOG.md) |
| Development experience log | [`AGENT-EXPERIENCE.md`](AGENT-EXPERIENCE.md) |

## What it will do

- Automate Linux tasks from natural language: packages, services, files, configuration, networking, scheduled jobs, and desktop (GUI) operations.
- Run on Tier-1 distributions (Ubuntu/Debian, Fedora, Arch, openSUSE, Alpine) through a distro-abstraction layer; more via community adapters.
- Use a deterministic playbook engine for common tasks and local/API LLMs for open-ended planning — routed per task by complexity and sensitivity.
- Never act blindly: every action is classified by safety tier, verified against the real machine before execution, gated by approval policy, checked after execution, and fully journaled with an undo path.

## Honest capability statement

Open-world task success at "98%" is not promised by anyone honestly — the best published
computer-use agents reach ~63–76% on the OSWorld benchmark. This project's contract is different and
verifiable: **≥98% execution-verified success on its published, versioned task catalog**, with
graceful refusal or escalation outside it, and all evaluation results auditable in the open.
Details: [`docs/PLAN.md` §3](docs/PLAN.md).

## Quick start (from a checkout)

```bash
pip install .                      # zero runtime dependencies
jarvis status                      # what JARVIS sees on this machine
jarvis do --dry-run "install htop" # deterministic engine: exact plan, nothing run
jarvis do "install htop"           # execute with journal + undo artifact
jarvis undo <task-id>              # reverse a task (see: jarvis tasks)
jarvis ask "set up monitoring"     # engine first; LLM planner for the rest
jarvis chat                        # interactive REPL
jarvis explain "what is ostype"    # cited answer + on-machine verification
jarvis facts                       # browse the knowledge base (12 cited facts)
```

Knowledge answers are **cite-or-abstain**

GUI control is a **capability matrix**, not a promise: `jarvis gui status` reports
exactly what this desktop supports (X11 · i3/sway · Hyprland · KDE · GNOME; AT-SPI
when present). Keystroke injection always shows you the focused window it will type
into and asks for consent — and typed text is never written to the journal.
`jarvis gui wizard` checks ydotool readiness on Wayland with distro-specific fixes.
: every answer names its sources
(kernel docs in [`torvalds/linux`](https://github.com/torvalds/linux), man pages,
distro docs) and whether the fact was verified *on this machine*; anything
outside the knowledge base is refused, never guessed (ADR-0009). With
`JARVIS_ONLINE_DOCS=1`, JARVIS additionally verifies its kernel-doc citations
against `torvalds/linux` master on demand (CI does this on every push).

Planning backends (ADR-0003): local **Ollama** is auto-detected (`OLLAMA_HOST`,
`JARVIS_LOCAL_MODEL`); an **OpenAI-compatible** endpoint is opt-in
(`JARVIS_OPENAI_API_KEY`, `JARVIS_OPENAI_BASE_URL`, `JARVIS_OPENAI_MODEL`);
`JARVIS_REMOTE_LLM=0` disables the remote fallback. The LLM never issues
commands — it proposes intents that must pass the same validators as the
deterministic engine (ADR-0007).

## Status of this repository

Planning phase (M0). Implementation begins after plan sign-off. See the milestone table in
[`docs/PLAN.md` §7](docs/PLAN.md).
