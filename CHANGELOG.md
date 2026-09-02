# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning targets [SemVer](https://semver.org/).

> Merge policy: the development agent **never merges** anything into `main`. All entries below land on the session working branch and reach `main` only through owner-approved merges.

## [Unreleased]

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
