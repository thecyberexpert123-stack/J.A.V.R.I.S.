# JARVIS Evaluation Report — M6 addendum: Production hardening & packaging (v1.0.0)

**Date:** 2026-09-02 · **Version:** 1.0.0 · **Scope:** M6 release engineering (ADR-0011)
**Companion to:** [REPORT-m5.md](REPORT-m5.md) — M1–M5 gates remain in force and green.

---

## 1. The P1 this milestone caught (and fixed)

The knowledge base loaded from a **repository-relative path**
(`Path(__file__).parents[3]/"knowledge"`). In any *installed* wheel that path
resolves into `site-packages/../..` — the KB would silently vanish. Fix (ADR-0011):
the KB ships inside the package (`jarvis/knowledge/data/`, loaded via
`importlib.resources`); repo-root copy removed (single source of truth). **Proven
in a clean room:** fresh venv, `pip install --no-index <wheel>`, `jarvis explain`
answers with `kernel.ostype` cited. The install-test harness greps for exactly
this fact on every distro, so "KB missing from package" is a first-class CI
failure from now on.

## 2. Distribution rename

`J.A.V.R.I.S.` normalized to the unusable distribution name `jarvis-linux`.
Renamed to **`jarvis-agent`** (import package stays `jarvis`; console command
stays `jarvis`). Pre-1.0 is the last responsible moment; the metadata unit test
now guards the new name.

## 3. Artifacts (all from one versioned source)

| Artifact | Built by | Verified |
|---|---|---|
| `jarvis_agent-1.0.0-py3-none-any.whl` | `python -m build` | clean-venv install + KB smoke (local **and** CI) |
| `jarvis_agent-1.0.0.tar.gz` (sdist) | `python -m build` | builds from source |
| `jarvis-agent_1.0.0_all.deb` | `packaging/deb/build-deb.sh` (dpkg-deb) | **real lifecycle in this sandbox**: `dpkg -i` → `/usr/bin/jarvis` 1.0.0 → explain OK → `dpkg -r` clean; plus debian/ubuntu CI containers |
| `.rpm` | `packaging/rpm/jarvis-agent.spec` | built + installed in the **fedora CI container** |
| AUR `PKGBUILD` | `packaging/arch/PKGBUILD` | `makepkg` + `pacman -U` in the **arch CI container** |
| alpine | wheel via pip | alpine CI container |

Deb/rpm/PKGBUILD share one design: wheel unpacked to `/usr/share/jarvis/lib` +
`/usr/bin/jarvis` shim; depends only on `python3 ≥ 3.10`; nothing fetched at
install time; no pip-in-postinst.

## 4. Install matrix (clean Tier-1 containers, actual artifacts)

`packaging.yml` runs **on every push**: artifacts job (build + clean-venv smoke)
→ 5-distro install matrix (debian-12, ubuntu-24.04, fedora, arch, alpine), each
installing its *native* artifact and running the KB smoke. Results: annotations
`install-test :: PASS <distro>` on the branch runs. This is the plan's "install
tested on clean containers of all Tier-1 distros" criterion, met.

## 5. Release pipeline & on-demand verification

- `release.yml`: tag `v*` → build all artifacts → clean-venv smoke → **draft**
  GitHub Release (runner `contents: write`). PyPI publishing: manual, owner-only.
- `workflow_dispatch` enabled on CI, container-eval, packaging, release — fresh
  GitHub VMs can be triggered on demand (owner from the UI; the agent's token is
  installation-scoped and cannot trigger dispatch — documented honestly).
- Tag/release creation is the owner's act (the agent's bot token cannot create
  releases; `RELEASING.md` documents the exact steps).

## 6. Telemetry

**None exists.** Whether opt-in telemetry is ever added is the owner's decision
(plan §M6 explicitly reserves it). Nothing was added.

## 7. Remaining owner decisions

1. **LICENSE** (owner-reserved since M0; recommendation: Apache-2.0 or MIT).
   Until chosen, artifacts carry `LicenseRef-Proprietary-Until-Owner-Decides`.
2. **Publishing**: PyPI account/trusted-publishing, AUR publication, public
   announcements.
3. **Merging**: the agent opens the milestone PR to `main` — merging remains the
   owner's exclusive authority.

## 8. Gates at publication (v1.0.0)

ruff lint+format clean · mypy clean (41 files) · pytest **340 passed, 1 honest
skip** · live 5 pass + 1 skip · M2 planner 9/9 · M3 fault gate 35/0 · M4
grounding 12/12 (0 unverifiable claims) · M5 GUI 15/15 X-lane + 4/4 headless ·
M1 containers 70/70 · packaging matrix 5/5 distros (CI).
