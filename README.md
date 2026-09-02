# JARVIS

> **J**ust **A** **R**ather **V**ery **I**ntelligent **S**ystem — an AI automation agent for Linux.
> Plans, executes, and **verifies** real tasks on any Tier-1 distribution — with a safety kernel,
> an audit journal, and no blind execution. Ever.
>
> *(Repository keeps its original name `J.A.V.R.I.S.`; the canonical project name is JARVIS per owner ruling, 2026-09-02.)*

**Status: `M1 KERNEL` (v0.1.0) — working CLI agent: 10 playbooks, 5 distro backends, safety kernel, journal, undo. Container eval in progress.**
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

## Status of this repository

Planning phase (M0). Implementation begins after plan sign-off. See the milestone table in
[`docs/PLAN.md` §7](docs/PLAN.md).
