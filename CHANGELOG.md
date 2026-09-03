# Changelog

All notable changes to this project are documented in this file.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning targets [SemVer](https://semver.org/).

> Merge policy: the development agent **never merges** anything into `main`. All entries below land on the session working branch and reach `main` only through owner-approved merges.

## Errata — 2026-09-03

Suite-count claims were re-verified by replaying each milestone's exact commit in an
isolated worktree (era-correct package metadata, `RUN_LIVE=1`, no local LLM; skip
identities confirmed via `-rs`). Originals preserved here for transparency; numbers
below each entry were corrected in place.

- **0.2.0 / 0.3.0:** the quoted "unit" totals (193 / 231) already included the 4 opt-in
  live tests; true split is 189+4 / 227+4 (verified by `--collect-only` sums at
  `4178777` / `7720176`). Totals were right; the split labels double-counted.
- **0.4.0:** "297 unit + 6 live" → observed at `d2e40f4`: **301 collected = 294 unit +
  7 live-marked (live: 6 pass + 1 skip)**.
- **0.5.0:** "+38 tests / 339 passed + 1 honest skip; live 5 pass + 1 skip" → observed
  at `6d53a63`: **+40 tests; 340 passed + 1 skip (341 collected); live-marked set is 10
  (9 pass + 1 skip)**. The "live 5" phrasing was stale from the 0.4.0 era.
- **1.1.0:** "+18 tests / 352 passed + 1 honest skip" → observed at `a08ba8f`: **+17
  tests; 356 passed + 2 skipped** (both model-availability skips: `live_llm` gate and
  the Ollama smoke test).
- Verified exact, no change: 1.0.0 gates (REPORT-m6 §8: 340 passed + 1 skip at
  `1f9f430`), 1.2.0 (370 passed + 2 skips at `2c64904`), 1.2.1 (372 passed + 2 skips).
- `evals/results/REPORT-m6.md` §4 cited packaging run `33653104688` — a transcription
  slip (HTTP 404). Actual run at `1f9f430`: **33653349705** (build + 5/5 distro jobs
  success), CI run `33653349731` also green. Corrected in place.

## [1.6.0] - 2026-09-03 — M9e + M9b: ADR-0013 complete (owner-approved)

### Added — M9e: API-first GUI actions
- **`type_text` gains an AT-SPI EditableText API path**: when `pyatspi` is importable, text entry prefers the accessibility interface — no synthetic keystrokes. Same T2 consent, same TOCTOU focus guard, same no-text-in-journal redaction. **Fallback is disclosed, not silent** (ADR-0013 ordering: API preferred, synthetic input as last resort): if the API path fails (e.g. the focused app exposes no editable), the injection backend runs under the same consent and the journal/result name both attempts (`api_attempt`); with no fallback at all it is an honest error. Key combinations stay injection-only — stated plainly: there is no honest API path for key synthesis.
- **Action-path disclosure**: every capability binding now carries a `path` (`api` / `wm` / `injection`) shown by `jarvis gui status` and `--json` — the UFO²-informed guarantee that the operator can see whether an action rides OS interfaces or synthetic input.

### Added — M9b: verified skill packs
- **`jarvis skill install/list/remove`**: a skill pack is **data that compiles through the kernel** — it may only re-expose an existing playbook under a new one-line match regex with fixed scalar params. The referenced playbook determines argv and tier; packs cannot add commands, raise tiers, or carry instructions any model reads at runtime (the anti-ClawHub design; ~12% of ClawHub's instruction-file catalog was documented malicious).
- Install is consent-gated (T2 through the real `ApprovalPolicy`), shows the full pack first, and runs every eval case as a real planning dry-run — a pack that cannot build on this machine never installs. Installed bytes are pinned by a sha256 receipt; a pack whose bytes drift is skipped **fail-closed** by the matcher and flagged by `jarvis doctor` (skills live in the M9c integrity scope).
- `match_intent` gains a verified fallback: installed, receipt-verified packs extend NL matching deterministically (id order, first fullmatch); `run_intent` journals the alias in `params.skill`. Charter precheck deliberately still speaks canonical phrasings only — standing orders don't change meaning silently.
- Format note: ADR-0013 sketched YAML; packs are strict **JSON** (`*.skill.json`) — stdlib-only per ADR-0005.
- GUI eval catalog: task `03-input-xdotool` now asserts the stable fact (`capabilities.key.backend == xdotool`) instead of pinning `type_text`'s backend — which legitimately becomes `atspi-editable` on machines with pyatspi.
- Tests: +40 (M9e matrix paths, API flow incl. consent/TOCTOU/disclosed fallback/no-tool honesty with a fake pyatspi; M9b validation matrix, eval gating, receipt drift fail-closed, end-to-end skill phrasing through `run_intent`, CLI, integrity scope). Suite: **489 passed + 2 honest skips** (491 collected).

### Changed
- Version 1.6.0; PKGBUILD/spec synced. **ADR-0013 is now fully implemented** (M9a 1.3.0 · M9c 1.4.0 · M9d 1.5.0 · M9e+M9b 1.6.0).

## [1.5.0] - 2026-09-03 — M9d: charters, circuit-broken standing orders (ADR-0013, owner-approved)

### Added
- **`jarvis charter`**: recurring automation as a versioned, revocable contract — the "heartbeat" capability the landscape research shows is the field's most useful *and* most abused feature, designed here against its documented failure modes.
- **Install (`charter install`, T2 consent through the real `ApprovalPolicy` gate)**: the contract is printed line-by-line before consent — one pre-authorized NL request, an explicit playbook allowlist, a hard tier ceiling (0..2; **T3 is never charterable**), `--on-calendar` (systemd user timer; omit for manual scheduling), per-run step cap, monthly run budget, and `TimeoutStartSec` wall-clock bound.
- **Run (`charter run`)**: precheck opens every firing — status must be `active`, the contract must still validate, the request must still resolve to an allowlisted playbook at or under the ceiling (semantic drift **pauses** instead of improvising), and the rolling-30-day journal budget must be under the cap. Only then does the request play through the normal Orchestrator with pre-authorized consent; every firing is a normal journaled task.
- **Circuit breakers**: failure policy is fixed at `pause` (a failed or refused firing stops the charter until the owner resumes); budget exhaustion pauses; `pause`/`resume`/`revoke` give the owner instant control (revoke keeps the audit file, firings refuse forever).
- **systemd user timers, honestly degraded**: `charter install` writes `jarvis-charter-<id>.{service,timer}` and enables them when a systemd user session exists; otherwise it says so and documents the manual path (`jarvis charter run`). Unit generation is pure and unit-tested; `systemctl --user` is best-effort and never crashes the CLI.
- **Integrity integration**: charter contracts live in the M9c scope (`~/.local/state/jarvis/charters/*.json`) — a new or drifted contract trips `jarvis doctor` until deliberately re-baselined; operational state files (`.state`) are deliberately outside the glob so pausing/resuming never false-alarms.
- Anti-Ultron clause holds: a charter can only replay its own allowlisted request through the kernel; it cannot modify charters, code, or policy.
- Tests: +23 (schema invariants incl. T3 refusal, consent gate, dry-run semantics, failure pause → refusal, budget exhaustion, tamper + semantic-drift layers, revoke, systemd units, integrity-scope placement). Suite: **448 passed + 2 honest skips** (450 collected).

### Changed
- Version 1.5.0; PKGBUILD/spec synced.

## [1.4.0] - 2026-09-03 — M9c: memory & config integrity (ADR-0013, owner-approved)

### Added
- **`jarvis doctor`**: hash baseline over policy-relevant state — packaged KB files, the decision/gate/execution code (playbooks registry, safety kernel, runner, orchestrator, both ingress front-ends), the context store module, and the cautious-mode marker — written **only** via explicit `--write-baseline`; every later run reports drift (`ok` / exit 0, drift / exit 1, no baseline / exit 2 with guidance). `jarvis status` carries a live integrity line. Honest limitation stated in code and docs: this is a tripwire against invisible, gradual modification (the OpenClaw "security degradation" class), not a cryptographic anchor.
- **`jarvis doctor --canaries`**: every suggestion render (CLI human output, MCP `jarvis_suggest`) now issues a random canary token recorded in `canaries.jsonl`; if a canary string appears off-machine, the owner can trace exactly which suggestion batch leaked.
- **Context store hardening**: feedback text (reason/title) is scanned at write time for injection patterns and refused (the table feeds future suggestions in M8b — poisoned feedback would become poisoned suggestions); every entry carries a content hash chained into a table digest, so silent edits, deletions, and forgeries are reported by `verify_integrity()`; pre-1.4.0 rows are honestly reported as legacy and gain hashes on their next upsert; `jarvis doctor` folds the chain verdict into its exit status.
- Tests: +26 (baseline round-trip/changed/missing/added, doctor CLI + status line, canary issuance/trace, scan refusal/allowance, tamper detection incl. a doctor-level poisoned-store case). Suite: **425 passed + 2 honest skips** (427 collected).

### Changed
- Version 1.4.0; PKGBUILD/spec synced.
- MCP tool surface intentionally unchanged (fixed set of six — new capabilities are CLI/doctor-side; the server's `jarvis_suggest` payload gains only a `canary` field).

## [1.3.0] - 2026-09-03 — M9a: MCP server surface (ADR-0013, owner-approved)

### Added
- **`jarvis mcp serve`**: a Model Context Protocol server on stdio — newline-delimited JSON-RPC 2.0, **stdlib-only** (ADR-0005 dependency discipline holds; no SDK). Harm model: an MCP client is just another untrusted-ingress front-end, identical in standing to the CLI; nothing bypasses the kernel.
- **Tools (fixed set — deliberately no free-form-exec passthrough)**: `jarvis_status` (fingerprint) · `jarvis_facts` (cited KB) · `jarvis_explain` (cite-or-abstain) · `jarvis_suggest` (read-only) · `jarvis_preview` (plan + blast radius; never asks, never executes) · `jarvis_do` (deterministic playbook through the same Orchestrator; **T2 requires explicit per-call `"allow": true`**, mapped onto the CLI's `--yes` semantics with a deterministic non-tty stdin; **T3 refused unconditionally**; refusals restated in MCP terms with a preview-then-allow hint).
- **Resources**: `kb://facts` (all cited facts) · `journal://tasks` (recent journaled tasks).
- Protocol conformance: initialize (version echo with fallback) / ping / tools+resources discovery; parse-error, invalid-request, method-not-found, invalid-params error codes; notification silence; batch rejection. stdout carries protocol frames only — diagnostics go to stderr.
- Tests: +27 (protocol frames, tool semantics incl. refusal through the real ApprovalPolicy, execution via scripted runner, CLI wiring). Suite: **399 passed + 2 honest skips** (401 collected).

### Changed
- Version 1.3.0; `packaging/arch/PKGBUILD` + `packaging/rpm/jarvis-agent.spec` synced from stale 1.2.0 → 1.3.0 (they document the next v-tag; artifacts become fetchable when the owner cuts the v1.3.0 release).
- ADR-0013 status Proposed → Accepted (owner go-ahead 2026-09-03); M9a implemented, M9b–M9e pending per-phase go.

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

## [1.2.1] - 2026-09-03 — Security & quality audit fixes

### Fixed
- **P1 security**: knowledge fetch now re-validates **every redirect** against the URL allowlist (`SafeRedirectHandler`); previously only the initial URL was checked and redirects were followed blindly. All request sites routed through the validating opener (+2 tests).
- **P1 bug**: `jarvis safety-check` could **hang interactively** on graphical desktops (GUI battery's approval policy defaulted to the TTY stdin and would prompt with a focused window). Battery now uses a non-tty stdin.
- **P2 packaging**: install-test rpm version now derived from the wheel filename and verified via `rpm -q` (the tested rpm was previously mislabeled 1.0.0 while containing 1.2.0); spec/PKGBUILD synced to 1.2.0.
- P2 hygiene: `gui/detect.py` normal imports; dev-env setuptools upgraded past published advisory (build-system already required ≥68; jarvis has zero runtime deps).

### Audit
Full findings, soundness checks, and documented limitations: `evals/results/AUDIT-1.2.1.md`. Tests: **372 passed + 2 honest skips**.

## [1.2.0] - 2026-09-03 — M8a Adaptive initiative: suggestion engine

### Added (ADR-0012 — "proactivity proposes; consent executes")
- **`jarvis suggest`**: deterministic, evidence-backed suggestions — failed tasks with available undo artifacts (journal evidence), stale package index (>14 days, journal evidence), distro-relevant pitfall briefings (KB-cited with sources). The engine takes **no runner and executes nothing**; accept prints the exact `jarvis …` command for the user to run through the normal consent path.
- **Feedback ledger** (`jarvis suggest accept|reject <id> [--reason]`): handled suggestions are suppressed from future listings; rejections require a reason (calibration signal); ledger is the seed of the M8b context store.
- **`jarvis context show`** (+ status line): the local store is inspectable from day one; it tunes suggestions and never grants authority to act.
- Tests: +14 (rules, evidence, suppression, determinism, read-only invariant, broken-journal resilience, CLI flow). Suite: **370 passed + 2 honest skips**.

### Planned (recorded in ADR-0012, not built yet)
- M8b context store (preferences/routines/house-rules; inspectable, deletable, local-only), M8c charters (revocable standing orders on systemd timers, journaled, tier-capped), M8d supervised growth loop (KB/playbook proposals as gated PRs).

## [1.1.0] - 2026-09-02 — M7 Real-machine readiness

### Added
- **GUI focus TOCTOU guard**: the focused window is re-verified after consent, immediately before injection; a focus change aborts with disclosure (old → new). Keystrokes can no longer silently land in a window that took focus during approval.
- **`jarvis safety-check`**: live refusal battery through the real components — protected package, destructive NL, flag smuggling, protected file append, T2 consent gate, GUI injection guard — with an execution-blocked sentinel runner (a refusal bug still cannot touch the system). Verdict: `SAFETY CHECK PASSED` (7/7).
- **`jarvis do --preview`**: full plan + blast radius (max tier, root?, network?, commands, classified system/kernel/home paths) — never asks, never executes.
- **Auto-rollback** (`jarvis do --auto-rollback`): failed consented tasks are reversed automatically via the full `undo()` path (artifact rebuild + kernel revalidation + verification) under the original task's consent; journal keeps the task `failed` and marks the undo applied.
- **Cautious mode** (`jarvis cautious on/off/status`): blocks T2+ even with `--yes`; each action needs `--cautious-ok`; `--preview` always allowed. Status line in `jarvis status`.
- **Live-LLM injection corpus** (`tests/test_fault_injection_live.py`, marker `live_llm`): 7 prompt-injection frames through a real local model; planner-or-kernel-must-refuse invariant; honest skip without a model. New weekly `llm-eval.yml` CI lane (Ollama + qwen2.5:0.5b) for real-model drift detection.
- **`docs/SAFE-TESTING.md`**: verified/unverified map + 4-rung safe-testing ladder + safety-bug reporting protocol.
- Tests: +17 (TOCTOU order-semantics runner, blast radius, cautious gates, auto-rollback with real journal, battery, CLI). Suite: **356 passed + 2 honest skips** (both model-availability skips).

### Changed
- `Orchestrator` gains `auto_rollback` / `cautious_ok`; `undo()` gains internal `skip_consent` (rollback runs under the original task's consent); `TaskOutcome` gains `rolled_back` / `rollback_task_id`.

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
- Tests: +40 (detection, matrix, parsers, policy, service consent/journal/privacy, wizard, vision stub, CLI, playbook, detach regression). Suite: **340 passed + 1 honest skip** (341 collected); live-marked set: 10 (9 pass + 1 skip).

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
- Tests: +26 (store schema refusals, verifiers on the real host, answers honesty, CLI surface, allowlist-before-network, live upstream verification). Suite: **301 collected (294 unit + 7 live-marked; live: 6 pass + 1 skip)**.

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
- Tests: +38 (provider HTTP behavior on real sockets via stub server, planner validation branches, composite plan lifecycle incl. poisoned undo, CLI routing incl. remote-fallback). Total suite: **227 unit + 4 live (231 collected)**.

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
- Tests: 189 unit tests (adapters exact-argv contracts, safety blocklist, matching table, journal round-trips, orchestrator lifecycle incl. tampered-undo refusal and interrupt semantics, runner sudo/timeout behavior, CLI surface) plus 4 opt-in live integration tests (193 collected in total) (`RUN_LIVE=1`; read-only and honest privilege-failure paths only — real mutations belong to the CI distro-container evaluation).
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
