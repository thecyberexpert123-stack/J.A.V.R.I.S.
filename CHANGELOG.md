# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning targets [SemVer](https://semver.org/).

> Merge policy: the development agent **never merges** anything into `main`. All entries below land on the session working branch and reach `main` only through owner-approved merges.

## [Unreleased] — M1 container evaluation: 70/70 PASSED

### Verified (observed, run 33637847042)
- Container execution-eval green on **all five distros** — debian:12, ubuntu:24.04, fedora:latest, archlinux:latest, alpine:latest — **14/14 tasks each (70/70 overall)**, including real install/remove/upgrade across apt/dnf/pacman/zypper/apk, the undo round-trip with post-condition replay, and all honest-refusal paths. Evidence: check annotations + [eval summary](evals/results/m1-baseline.md). CI annotation channel added to the driver; artifact names sanitized; GITHUB_ACTIONS passed into containers.

### Added
- `evals/catalog/m1.json` — M1 seed catalog: 14 executable expectations per distro (10 playbooks incl. undo round-trip, idempotent reinstall, system upgrade, honest service refusal in non-systemd containers, and three refusal cases: protected package, unmatched intent, invalid option-like name).
- `evals/harness/m1_eval.py` — stdlib-only eval driver; runs the real CLI per task, checks status/playbook/verification/error substrings/exit codes, writes JSON results, exits non-zero on any mismatch.
- `evals/harness/bootstrap.sh`, `evals/harness/run_in_container.sh` — python3 bootstrap (apt/dnf/pacman/apk/zypper) and container entrypoint.
- `.github/workflows/container-eval.yml` — matrix evaluation in debian:12, ubuntu:24.04, fedora:latest, archlinux:latest, alpine:latest containers (root, network), results uploaded as artifacts.

### Changed
- `.gitignore` — generated eval JSON excluded from version control; curated summaries are committed instead (`evals/results/`).

## [1.0.0] - 2026-09-02 — M6 Production hardening & packaging

### Added
- **Packaging** (ADR-0011): wheel + sdist (`jarvis-agent`), self-contained `.deb` (real dpkg lifecycle verified: install → run → remove), `.rpm` spec (built+installed in fedora CI container), AUR `PKGBUILD` (makepkg+pacman verified in arch CI container); all native packages unpack the wheel to `/usr/share/jarvis/lib` + `/usr/bin/jarvis` shim, depend only on `python3 >= 3.10`.
- **KB ships in the package** (`jarvis/knowledge/data/` via `importlib.resources`) — fixes a P1: the KB previously resolved against the repo root and vanished in installed wheels; clean-venv install proven; install harness greps for the KB on every distro.
- **Install matrix** (`packaging.yml`): every push builds artifacts and install-tests them on clean containers of all five Tier-1 distros (debian-12, ubuntu-24.04, fedora, arch, alpine) with a KB smoke.
- **Release pipeline** (`release.yml`): tag `v*` → artifacts + clean-venv smoke → draft GitHub Release; PyPI publishing manual and owner-only; `workflow_dispatch` on CI, container-eval, packaging, release for on-demand fresh VMs.
- **Docs**: `INSTALL.md` (per-distro install story), `docs/RELEASING.md` (owner release runbook).

### Changed
- **Distribution rename**: `jarvis-linux` → **`jarvis-agent`** (import package and `jarvis` command unchanged; metadata test guards the new name).
- **Telemetry: none** (owner decision pending; nothing added).

## [0.5.0] - 2026-09-02 — M5 GUI control

### Added
- **GUI capability matrix** (`jarvis gui status`): honest per-machine report of session (x11/wayland/headless), desktop, and per-capability backend — availability never pretended (ADR-0010).
- **Backends**: X11 (wmctrl/xdotool/scrot), i3/sway IPC (get_tree JSON walk, focus verification), Hyprland (hyprctl -j), KDE Wayland (kdotool when present; spectacle), GNOME Wayland (gdbus Shell screenshot), Wayland input via ydotool gated on a live `ydotoold` socket; AT-SPI optional read layer via `pyatspi` (honest absence).
- **Consent-gated actions** (`jarvis gui open/focus/type/key/screenshot/close`): focused-window target disclosure BEFORE acting, T2 approval via the standard policy, journaled; **typed text is never persisted** (length + sha256 prefix only — a unit test caught the argv leak, fixed); injection is CLI-only, unreachable from NL playbooks; text/key-combo/launch-argv policies.
- **ydotool wizard** (`jarvis gui wizard`): real readiness checks with distro-specific fix commands (apt/dnf/pacman/apk).
- **Vision fallback** (`jarvis gui describe`): screenshot → local Ollama vision model; abstains loudly when absent.
- **`gui.launch` playbook** (NL "open firefox", registry 12): app-name argv only, no paths, case-preserving, T2.
- **GUI eval** (`evals/harness/m5_gui.py` + 15-task catalog): real X stack (Xvfb + i3 + xterm) through the real CLI in CI (`gui-eval` job), gate ≥98% ⇒ 15/15; headless honesty subset (4 tasks) verified locally **4/4**; consent refusal is a graded task.
- Tests: +38 (detection, matrix, parsers, policy, service consent/journal/privacy, wizard, vision stub, CLI, playbook, detach regression). Suite: **339 passed + 1 honest skip**; live 5 pass + 1 skip.

### Changed
- Package version 0.5.0; README GUI section; report addendum `evals/results/REPORT-m5.md`.

## [0.4.0] - 2026-09-02 — M4 Knowledge system

### Added
- **Cited knowledge base** (`knowledge/*.json`, KB v1): 12 facts across kernel/distros/pitfalls; every fact carries sources (kernel-doc paths in `torvalds/linux`, man pages, specs, distro docs) and an optional local verifier; the store **refuses uncited facts at load** (ADR-0009).
- **Local grounding** (`knowledge/grounding.py`): file_equals / file_exists / os_release_field / binary_present / command_ok verifiers; honest three-state results (verified / contradicted / unverifiable-here).
- **Cite-or-abstain answers** (`knowledge/answers.py` + `jarvis explain`): answers always carry sources + on-machine verification status; anything outside the KB is refused, never guessed.
- **Opt-in online verification** (`knowledge/fetch.py`, `JARVIS_ONLINE_DOCS=1`): kernel-doc citations verified against **`torvalds/linux` master** via the GitHub Contents API (owner-directed knowledge source; upstream reference, not vendored — ADR-0009); strict URL allowlist refuses anything else before a request; results cached in the state dir.
- **`jarvis facts [topic]`** browser; KB version/count in `jarvis status`; `jarvis` console-script entry point (`pip install` now puts the CLI on PATH).
- **Grounding eval** (`evals/harness/m4_grounding.py` + catalog): gate **0 unverifiable claims** — answered ⇒ cited; verified ⇒ verifier passed; kernel citations re-verified upstream in CI (online mode). Result: **12/12, 0 unverifiable claims** (offline 10/10; +2 upstream torvalds/linux checks).
- Tests: +26 (store schema refusals, verifiers on the real host, answers honesty, CLI surface, allowlist-before-network, live upstream verification). Suite: **297 unit + 6 live**.

### Changed
- Package version 0.4.0; README quick start gains `explain`/`facts`; report addendum `evals/results/REPORT-m4.md`.

## [0.3.0] - 2026-09-02 — M3 Safety hardening

### Added
- **Snapshot preflight** (`safety/snapshots.py`): best-effort snapper/timeshift snapshot before every T2+ task, journaled per task (`task_meta`), surfaced in CLI output; honest degradation (never blocks; says exactly what protection exists). Restore stays manual by design (ADR-0008).
- **File edits with real backups**: `file.append` playbook + `jarvis file append <path> <text>` — pre-edit backup into the state dir (hash-addressed, mode-preserving `cp -p`), argv-only execution (`tee -a` via new runner `stdin_text` support), undo restores byte-identical content (or removes created files). Path policy (`safety/paths.py`): symlink-resolving checks; auth material (`passwd`/`shadow`/`sudoers`) and `/boot`/`/proc`/`/sys`/`/dev` refused outright; `/etc`,`/usr`,`/var`,`/opt`,`/srv` require T2 consent.
- **Dynamic tier elevation**: effective task tier is now computed from built steps (file edits under system paths are gated as T2 even though the playbook's registry tier is T1).
- **Blocklist hardening**: `wipefs`/`parted`/`fdisk`/`gdisk`/`sgdisk` refused as argv[0]; generic pipe-to-shell (`| sh`, `| bash`, sudo variants); `chmod 777 /`.
- **Injected-fault gate** (`tests/test_fault_injection.py` + `evals/harness/m3_faults.py` in CI): 35 adversarial vectors across 9 ingresses — **0 escapes**. The suite caught a real gap during development: tampered undo artifacts could reach `/etc/shadow` via `tee`; undo replay now re-applies the file-path policy to `tee`/`cp`/`rm`/`truncate` operands.
- **First published consolidated eval report**: `evals/results/REPORT-m3.md` (M1 70/70 containers · M2 9/9 planner · M3 fault gate 35/0 · rollback evidence).
- Rollback integration tests on real files (byte-identical restore; created-file removal); live Ollama smoke test (skips honestly when no backend).

### Changed
- Package version 0.3.0; journal gains a `task_meta` store (snapshot records); runner supports piped stdin for argv-only editors.

## [0.2.0] - 2026-09-02 — M2 LLM planner & router

### Added
- **Provider abstraction** (`src/jarvis/providers/`): stdlib-`urllib` backends for local **Ollama** (JSON mode, temperature 0, availability probe) and any **OpenAI-compatible** endpoint (opt-in key via `JARVIS_OPENAI_API_KEY`, base URL/model configurable) — no provider SDKs, keys from env only (ADR-0007).
- **Router** (`providers/router.py`): deterministic engine first (LLM never consulted on playbook matches — eval-asserted at 0 requests), then local Ollama, then remote if configured and not disabled (`JARVIS_REMOTE_LLM=0` disables only the remote fallback), else honest refusal with setup hint.
- **LLM planner** (`planner/llm.py`): strict JSON contract (`{"explanation", "steps"}` of natural-language intents); every step must pass the deterministic playbook matchers — invalid JSON, out-of-vocabulary, injection-shaped, or oversized proposals are **refused, never guessed** (ADR-0007 "the LLM proposes, the kernel disposes").
- **Composite plan execution** (`Orchestrator.run_plan`): multi-part plans with per-part post-condition verification, one journal task (`plan/<provider>`), tier gate on the maximum step tier, and **composite undo applied last-first**; a part without a reverse path (e.g. upgrade) marks the plan's undo honestly unavailable.
- **CLI**: `jarvis ask` (one-shot engine+planner with `--dry-run`) and `jarvis chat` (interactive REPL: `/status`, `/playbooks`, `/tasks [n]`, `/undo <id>`, `/help`); `jarvis status` now reports planning-backend availability.
- **M2 eval** (`evals/harness/m2_eval.py` + `evals/catalog/m2.json`): 9 deterministic cases against a scripted local LLM stub — routing (0-LLM fast path), schema validity of proposals, injection/malformed/empty refusals, provider-outage honesty, no-backend guidance. Wired into CI; **9/9 required**.
- Tests: +38 (provider HTTP behavior on real sockets via stub server, planner validation branches, composite plan lifecycle incl. poisoned undo, CLI routing incl. remote-fallback). Total suite: **231 unit + 4 live**.

### Changed
- Package version 0.2.0; ADR-0007 records the planner architecture and the deliberate deferral of Textual/Pydantic (stdlib REPL + strict hand-rolled validation suffice for the fixed schema).

## [0.1.0] - 2026-09-02 — M1 Kernel

### Added
- **SENSE** (`src/jarvis/core/fingerprint.py`): machine fingerprint from `/etc/os-release` (man-5 parser), init-system detection, package-manager resolution (distro mapping *verified against PATH*, honest `unknown`), session type, privilege state.
- **Distro adapters** (`src/jarvis/system/`): exact-argv command vocabulary for apt, dnf, pacman, zypper, apk — install/remove/refresh/upgrade/search/info/installed-probe — plus the boot-critical protected-package set (ADR-0006).
- **Guarded execution** (`src/jarvis/execution/runner.py`): argv-only subprocess (no shell anywhere), per-step timeouts with process-group SIGTERM-to-SIGKILL, 16 KiB output tails, non-interactive `sudo -n` privilege path with clean refusal when unavailable (ADR-0006).
- **Static safety analysis** (`src/jarvis/safety/tiers.py`): strict token validation (refuse, never sanitize), fork-bomb / `mkfs` / `dd of=/dev` / `rm -rf /` / piped-curl-sh / shutdown-class blocklist (argv[0]- and `-c`-content-aware to avoid false positives), end-of-options marker rule that blocks flag smuggling from tampered journals.
- **Tiered approval** (`src/jarvis/safety/approval.py`): T0/T1 auto · T2 interactive or `--yes` (refused, never hung, in non-interactive mode) · T3 always refused.
- **Playbook engine** (`src/jarvis/planner/`): 10 deterministic seed playbooks (`pkg.install`, `pkg.remove`, `pkg.search`, `pkg.info`, `pkg.cache.refresh`, `pkg.upgrade`, `svc.status`, `svc.start`, `svc.enable`, `sys.info`) with strict anchored intent matching (unmappable requests are refused, not guessed), per-backend step building, post-condition verification (pipeline VERIFY), and undo plans built *before* execution.
- **Audit journal** (`src/jarvis/journal/sqlite.py`): SQLite (0600) tasks/steps/undo-artifacts under `~/.local/state/jarvis` (XDG/state-dir env precedence); undo artifacts stored before first execution and strictly revalidated (incl. protected-set re-check) on replay.
- **Orchestrator** (`src/jarvis/core/orchestrator.py`): full lifecycle REFUSED, RUNNING, SUCCEEDED/FAILED/INTERRUPTED/UNDONE with SIGINT/SIGTERM kill-switch (process-group termination, journal marked `interrupted`, exit 130).
- **CLI** (`src/jarvis/cli/app.py`, stdlib argparse per ADR-0005): `status` / `do [--dry-run] [--yes]` / `undo [--dry-run]` / `playbooks` / `tasks`, global `--json`, documented exit codes (0/1/2/130).
- Tests: 193 unit tests (adapters exact-argv contracts, safety blocklist, matching table, journal round-trips, orchestrator lifecycle incl. tampered-undo refusal and interrupt semantics, runner sudo/timeout behavior, CLI surface) plus 4 opt-in live integration tests (`RUN_LIVE=1`; read-only and honest privilege-failure paths only — real mutations belong to the CI distro-container evaluation).
- Docs: ADR-0005 (M1 stdlib-only runtime), ADR-0006 (argv-only execution, validation, privilege policy).

### Changed
- Package version 0.1.0; `docs/PLAN.md` M1 status updated.

### Security
- ADR-0006 controls active: no-shell argv execution, token validation, `sudo -n` only, protected-package set enforced at plan *and* undo-replay boundaries, T3 refused by policy, kill-switch with process-group cleanup. A blocklist anchoring flaw was caught by tests before any release (see AGENT-EXPERIENCE.md).

## [0.0.1] - 2026-09-02 — M0 Governance baseline


### Added
- `docs/adr/0001-scoped-success-metric.md` — adopts the scoped ≥98% task-catalog metric (owner-delegated decision; benchmark evidence cited).
- `docs/adr/0002-cli-first-surface.md` — v1 interaction surface: CLI + TUI chat; GUI overlay and daemon deferred with rationale.
- `docs/adr/0003-hybrid-router-local-first.md` — model posture: playbook engine + local-model default + opt-in API models behind one router.
- `docs/adr/0004-m0-toolchain.md` — toolchain & dependency set with per-dependency justification (guideline 16); zero runtime dependencies at M0.
- Project skeleton: `pyproject.toml` (PEP 621, src-layout, ruff/mypy/pytest config, dev extras `ruff`/`mypy`/`pytest`, license field intentionally omitted pending owner ruling), `.gitignore`, `.github/workflows/ci.yml` (ruff lint+format, mypy, pytest on Python 3.10–3.12 matrix), `src/jarvis/__init__.py` (package root, v0.0.1), `tests/test_package.py` (packaging-integrity smoke tests).
- CI verified in operation: workflow pushed after GitHub connection upgrade (commit `feea3e2`); run [33635129000](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S./actions/runs/33635129000) observed green — 3/3 matrix jobs (py3.10/3.11/3.12) passed all gates (ruff lint, ruff format, mypy, pytest).

### Changed
- Canonical project name ruled by owner: **JARVIS** — *"Just A Rather Very Intelligent System"*; display form `JARVIS`, package/CLI `jarvis`; repository name unchanged. `README.md`, `docs/PLAN.md`, `docs/RESEARCH.md` updated accordingly; decision recorded as resolved in PLAN §13.1.
- `docs/PLAN.md` status elevated from DRAFT to **ACCEPTED (baseline)** — remaining decisions §13.2–13.5 resolved via owner delegation, each documented in an ADR; new open item §13.6 (LICENSE selection, owner decision).

### Fixed
- `docs/PLAN.md`: repaired self-inflicted corruption (a malformed edit truncated the document mid-§7, losing §8–§13; a stray fragment and a non-English character artifact also introduced). Full document restored from source content and verified (all 13 sections present, anomaly scan clean). Incident logged in `AGENT-EXPERIENCE.md`.

### Security
- No runtime code yet; M0 ships no runtime dependencies (supply-chain surface intentionally empty; ADR-0004). Safety architecture (tiered action gate, blocklists, undo/rollback, dual reviewer) specified in `docs/PLAN.md` §4.3 for M1+. CI quality gates (lint, format, types, tests) wired on push/PR.
