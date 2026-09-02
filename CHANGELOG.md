# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning targets [SemVer](https://semver.org/).

> Merge policy: the development agent **never merges** anything into `main`. All entries below land on the session working branch and reach `main` only through owner-approved merges.

## [Unreleased] — M1 container evaluation

### Added
- `evals/catalog/m1.json` — M1 seed catalog: 14 executable expectations per distro (10 playbooks incl. undo round-trip, idempotent reinstall, system upgrade, honest service refusal in non-systemd containers, and three refusal cases: protected package, unmatched intent, invalid option-like name).
- `evals/harness/m1_eval.py` — stdlib-only eval driver; runs the real CLI per task, checks status/playbook/verification/error substrings/exit codes, writes JSON results, exits non-zero on any mismatch.
- `evals/harness/bootstrap.sh`, `evals/harness/run_in_container.sh` — python3 bootstrap (apt/dnf/pacman/apk/zypper) and container entrypoint.
- `.github/workflows/container-eval.yml` — matrix evaluation in debian:12, ubuntu:24.04, fedora:latest, archlinux:latest, alpine:latest containers (root, network), results uploaded as artifacts.

### Changed
- `.gitignore` — generated eval JSON excluded from version control; curated summaries are committed instead (`evals/results/`).

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
