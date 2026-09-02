# JARVIS

> **J**ust **A** **R**ather **V**ery **I**ntelligent **S**ystem — an AI automation agent for Linux.
> Plans, executes, and **verifies** real tasks on any Tier-1 distribution — with a safety kernel,
> an audit journal, and no blind execution. Ever.
>
> *(Repository keeps its original name `J.A.V.R.I.S.`; the canonical project name is JARVIS per owner ruling, 2026-09-02.)*

**Status: `M3 HARDENED` (v0.3.0) — engine + LLM planner behind a fault-tested safety kernel: snapshots, file-edit backups, 35-vector injection gate (0 escapes), eval-verified on 5 distros. Report: `evals/results/REPORT-m3.md`.**
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
```

Planning backends (ADR-0003): local **Ollama** is auto-detected (`OLLAMA_HOST`,
`JARVIS_LOCAL_MODEL`); an **OpenAI-compatible** endpoint is opt-in
(`JARVIS_OPENAI_API_KEY`, `JARVIS_OPENAI_BASE_URL`, `JARVIS_OPENAI_MODEL`);
`JARVIS_REMOTE_LLM=0` disables the remote fallback. The LLM never issues
commands — it proposes intents that must pass the same validators as the
deterministic engine (ADR-0007).

## Status of this repository

Planning phase (M0). Implementation begins after plan sign-off. See the milestone table in
[`docs/PLAN.md` §7](docs/PLAN.md).
