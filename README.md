# JARVIS

> **J**ust **A** **R**ather **V**ery **I**ntelligent **S**ystem — an AI automation agent for Linux.
> Plans, executes, and **verifies** real tasks on any Tier-1 distribution — with a safety kernel,
> an audit journal, and no blind execution. Ever.
>
> *(Repository keeps its original name `J.A.V.R.I.S.`; the canonical project name is JARVIS per owner ruling, 2026-09-02.)*

**Status: `v1.12.0` — M0–M11 complete + GUI contract + playbook breadth (ADR-0016) + hybrid
residency (ADR-0018)**: deterministic engine + LLM planner with failure semantics + a
proposals-only neural intent classifier + safety kernel + cited knowledge + MCP surface +
verified skill packs + charters + integrity doctor + GUI control + **56 deterministic playbooks**
across guarded families + an opt-in loopback doorway for resident front-ends, packaged
(wheel/deb/rpm/AUR) and install-verified on all Tier-1 distros in CI. Review candidates
`v1.0.0-rc1` … `v1.12.0-rc1` await the owner's release decisions. Reports: `evals/results/`.
See `INSTALL.md`.**
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
jarvis safety-check                # prove the guards are alive on THIS machine
jarvis do --preview "upgrade the system"   # plan + blast radius, nothing runs
jarvis cautious on                 # early-days guard for a fresh machine
jarvis suggest                     # evidence-backed suggestions (read-only; nothing runs)
```

> **Before a machine you care about:** read [`docs/SAFE-TESTING.md`](docs/SAFE-TESTING.md) —
> the honest risk map and a 4-rung ladder for building trust.

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

**AI failure semantics (ADR-0014):** the AI path is optional, breaker-tracked,
and honest. A persistently failing model trips a per-provider circuit breaker
(`status` shows it; `state_dir/ai/breaker.state`), failures are classified
(`unreachable/timeout/http/malformed/key-missing/breaker-open`), planner
output is schema-constrained *and* strictly validated, `explain` falls back
from KB cite-or-abstain to a grounded AI answer only when citations resolve
to real KB facts, unknown requests return nearest-known intents plus a
journal record for owner review, and `--no-ai` (or `JARVIS_NO_AI=1`) disables
every model path in one switch — the agent remains fully usable without any
AI.

**Learned intent recall (ADR-0015):** a tiny purpose-built neural network
(~13K parameters, shipped weights, stdlib inference) ranks the playbook
vocabulary for loosely-phrased requests when the engine and the LLM planner
have both declined. It is proposals-only by construction: suggestions must
re-pass the real matchers and are printed for you to type (`jarvis do …`),
never executed; `--no-ai` switches it off. Retrain any time:
`python training/train_intent.py` (gated, deterministic).

## Playbook breadth (ADR-0016)

`jarvis playbooks` lists **56 deterministic playbooks** (was 12). Breadth follows one rule: every
new command enters through a **guarded family** — a pinned binary, a fixed flag prefix, and
argument slots validated at match time (a user flag such as `-rf` is a refusal that makes the
intent unmatchable, never a sanitize; shell metacharacters are banned outright). Families:

- **Read-only inspection (T0):** `fs.list/read/head/tail/count/stat/file_type/which/disk_usage/find/search/disk_free`,
  `sys.memory/processes/uptime/date/hostname/cpus/pci/usb/blocks/sockets/network/routes/journal/kernel_log/users/login_history/env/identity/checksum`,
  `net.ping` (bounded: 4 packets, 4 s), `net.dns`.
- **File management (T1, root-gated where policy demands):** `fs.mkdir/touch/copy/move/remove/link`
  — protected paths refused, undo planned before execution, deletion disclosed as irreversible.
- **Process & service control (T2):** `svc.stop/restart/disable` (systemd-gated),
  `proc.kill` (numeric pid), `proc.kill_name` (exact name, no patterns).

Some things are **deliberately absent** and documented as such in ADR-0016: `dd`, `mkfs`,
partition editors, `shutdown`/`reboot`, downloads-and-pipes (`curl | sh`), stream editing
(`sed -i`), and permission changes (`chmod`/`chown`) have no playbook at all — they are
unmatchable by design, and tests prove it. `jarvis playbooks` shows the full catalog with tiers.

## Hybrid residency (ADR-0018)

By default **nothing runs unless you run it**. If you want front-ends (the GUI, scripts) to
reach JARVIS any time after login without starting it yourself, opt in:

```bash
jarvis serve install [--with-gui]   # systemd --user unit (+ GUI autostart if installed)
jarvis serve                        # or run the doorway in the foreground
jarvis serve status / uninstall     # inspect / return to pure on-demand
```

The doorway is **loopback-only and token-authenticated** (token `0600` in the state dir, never
logged). It serves exactly the six MCP tools with **identical consent semantics**: T2 still
needs a per-call `allow: true`, T3 is always refused, there is no persistent yes and no
exec passthrough — a doorway, never an actor. Packaging never enables it; `uninstall` removes
every trace.

## MCP surface (ADR-0013 M9a)

`jarvis mcp serve` speaks the Model Context Protocol — newline-delimited JSON-RPC 2.0 on stdio, stdlib-only (no SDK). An MCP client is just another front-end to the same kernel:

- tools: `jarvis_status`, `jarvis_facts`, `jarvis_explain`, `jarvis_suggest`, `jarvis_preview`, `jarvis_do`
- resources: `kb://facts`, `journal://tasks`
- consent is unchanged: T2 actions need an explicit per-call `"allow": true`; T3 is refused; there is no free-form-exec passthrough tool

Smoke test:

```console
$ printf '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}\n{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n' | jarvis mcp serve
```

## Integrity (ADR-0013 M9c)

Policy-relevant state — KB files, playbooks registry, safety kernel, execution and ingress code, cautious flag — is hashed into a machine-local baseline:

```console
$ jarvis doctor --write-baseline   # once, after reviewing the state
$ jarvis doctor                    # verify: 0 clean · 1 drift · 2 no baseline
$ jarvis doctor --canaries         # trace suggestion-canary leak paths
```

`jarvis status` shows a live integrity line. Stored feedback is write-time-scanned for injection patterns and hash-chained; `jarvis doctor` reports tampering with it. Honest limitation: a tripwire against invisible, gradual modification — not a cryptographic anchor.

## Charters (ADR-0013 M9d)

Recurring automation as a circuit-broken contract — one pre-authorized request, played through the same kernel on a schedule:

```console
$ jarvis --yes charter install nightly-cache \
    --request "update the package cache" \
    --playbook pkg.cache.refresh --tier-ceiling 1 \
    --monthly-runs 30 --on-calendar daily
$ jarvis charter run nightly-cache      # one firing (what the timer executes)
$ jarvis charter list / pause / resume / revoke
```

Breakers: failure **pauses** the charter; monthly run budget and per-run step caps; hard tier ceiling (T3 never charterable); systemd `TimeoutStartSec` wall-clock bound; semantic drift (a request that stops matching its allowlist) pauses instead of improvising; contract bytes are inside the `jarvis doctor` integrity scope. Without a systemd user session, scheduling degrades honestly to manual `charter run` invocations.

## Skill packs (ADR-0013 M9b)

A skill pack adds new phrasings for an **existing** playbook — never new commands, never model-read instructions:

```json
{
  "schema": 1,
  "id": "refresh-all",
  "description": "colloquial phrasings for refreshing the package index",
  "match": "^(?:refresh|sync)\s+(?:everything|all)$",
  "playbook": "pkg.cache.refresh",
  "params": {},
  "evals": [{"request": "refresh everything"}],
  "provenance": {"source": "owner", "sha256": "<hex>"}
}
```

```console
$ jarvis --yes skill install refresh-all.skill.json   # evals run as real dry-runs
$ jarvis do --dry-run "refresh everything"            # plans through the kernel
```

Packs are receipt-pinned (sha256) and live inside the `jarvis doctor` integrity scope; drifted packs are skipped fail-closed. GUI actions disclose their route (`api` / `wm` / `injection`) in `jarvis gui status`; `type_text` prefers the AT-SPI EditableText API over synthetic keystrokes (ADR-0013 M9e).

## Context & growth (ADR-0012 M8b/M8d)

```console
$ jarvis context prefer suppress.undo 1        # tune suggestions, never authority
$ jarvis context rule never touch docker       # house rules suppress matching suggestions
$ jarvis context routines                      # journal-inferred patterns (never persisted)
$ jarvis context forget                        # delete everything (consent-gated)
$ jarvis grow fact --id t.f --topic t --claim "..." --pattern q \
    --sources '[{"kind":"docs","ref":"..."}]'  # drafts validated by the real KB store
$ jarvis grow export t.f --out out/            # artifact + owner commands (owner merges)
```

Context is local, inspectable (`context show`), deletable, and tamper-evident (`jarvis doctor` verifies its hash chains). Growth proposals are inert data; the kernel, policy, and shipped knowledge stay outside JARVIS's write scope — promotion runs through owner-reviewed PRs and consented installs only.

## Front-ends (J.A.V.R.I.S.-GUI)

Native HUD front-end (owner's [J.A.V.R.I.S.-GUI](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.-GUI) project) wires to this kernel over the MCP stdio surface:

```console
$ jarvis mcp describe    # machine-readable front-end contract (javris-frontend/1)
```

A front-end is another untrusted-ingress surface: it renders, it never widens authority — T2 actions need the owner's explicit per-call consent in the UI; `docs/integration/JAVRIS-GUI.md` is the wiring contract, and CI asserts the published contract against live server behavior.

## Status of this repository

Planning phase (M0). Implementation begins after plan sign-off. See the milestone table in
[`docs/PLAN.md` §7](docs/PLAN.md).
