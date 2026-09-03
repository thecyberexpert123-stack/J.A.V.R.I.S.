# Wiring J.A.V.R.I.S.-GUI to the J.A.V.R.I.S. kernel

**Status:** Active contract (2026-09-03) · **Backend:** this repository (jarvis-agent ≥ 1.8.0) · **Front-end:** [J.A.V.R.I.S.-GUI](https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.-GUI) (javris ≥ 0.1.0)

The GUI is a front-end to the same kernel — identical in standing to the CLI. This
document is the wiring contract; `jarvis mcp describe` publishes it as JSON, and
`tests/test_frontend_contract.py` asserts that published form against live server
behavior, so the two cannot drift.

## 1. Architecture — who owns what

```
┌────────────────────────────┐        spawns (fixed argv)        ┌──────────────────────────┐
│  J.A.V.R.I.S.-GUI (Qt6)    │ ────────────────────────────────► │  jarvis mcp serve        │
│  HUD, telemetry, console   │   stdin/stdout, newline JSON-RPC  │  (this repo, stdio only) │
│  owns presentation only    │ ◄──────────────────────────────── │  owns tiers + journal    │
└────────────────────────────┘                                   └──────────────────────────┘
```

- **The GUI never gains authority.** It renders state and relays owner intent; every
  mutation flows through the kernel's tiers exactly as on the CLI (ADR-0013 M9a harm
  model: a front-end is another untrusted-ingress surface).
- **The kernel never renders.** The server returns JSON; the GUI decides presentation.
- One fixed spawn (`jarvis mcp serve`) — this is the GUI's single extension of its
  "no processes" posture, pinned to one argv, no shell, no network.

## 2. Transport and handshake (normative)

- Spawn `jarvis mcp serve`; speak newline-delimited JSON-RPC 2.0 on its stdio. One
  object per line; stdout carries protocol frames only (server logs go to stderr).
- `initialize` → the server echoes the client's date `protocolVersion` (fallback
  `2024-11-05`); read `result.serverInfo.version` for the version handshake.
- `notifications/initialized` (no response), then `tools/list`.
- Full machine-readable form: `jarvis mcp describe` (`contract: javris-frontend/1`).

## 3. Tools and consent UX

| Tool | Consent | GUI behavior |
|---|---|---|
| `jarvis_status`, `jarvis_facts`, `jarvis_explain`, `jarvis_suggest`, `jarvis_preview` | `read-only` | fire freely |
| `jarvis_do` | `explicit-allow` | call **without** `allow` first; on `isError` with `payload.outcome.status == "refused"` show the plan/refusal to the owner; re-call with `"allow": true` **only** after an explicit owner action (button/dialog), once per call |

Invariants (non-negotiable): the GUI never synthesizes `allow: true` without an owner
action; T3 is refused by the kernel unconditionally; charters (`jarvis charter`) remain
the only pre-authorized automation. `jarvis_preview` powers a "show me the plan" flow —
the refusal hint already points there.

## 4. State-machine mapping (legal transitions only)

Mapped onto `javris`'s explicit `AssistantState` table — every arrow below is a legal
transition (or an always-reachable one):

| GUI state | When |
|---|---|
| `BOOTING` | spawning the server + handshake |
| `STANDBY` | handshake done, idle. `jarvis` missing from PATH → `OFFLINE` (telemetry continues — honest degradation, never a faked agent) |
| `LISTENING` | console focused |
| `PROCESSING` | any request in flight |
| `EXECUTING` | `jarvis_do` running with the owner's per-call allow |
| `SPEAKING` | rendering a result |
| `ERROR` | `isError` result, consent refusal, protocol/parse error → acknowledged back to `STANDBY` |

## 5. Suggested console verbs (GUI-side vocabulary)

Extending the fixed `CommandRouter` vocabulary (still no shell; each verb maps to one
bridge call): `ask <question>` → `jarvis_explain` · `do <request>` → consent flow above ·
`agent status` → server info/health · `plan <request>` → `jarvis_preview` ·
`agent disconnect` → close the child process (SIGTERM) and go `STANDBY`/`OFFLINE`.

## 6. Security posture (both sides keep their guarantees)

- GUI side: the console's allow-list, input capping, and control-char stripping are
  unchanged; the bridge is one more allow-listed handler set. `jarvis` text output is
  length-capped before entering the log renderer.
- Kernel side: nothing changes for other callers — the MCP server already treats every
  client identically; the GUI gets no private API, no elevated tier, no bypass.
- Local-only: stdio pipes between parent and child; no sockets, no network, no keys.

## 7. Licensing note (deliberate)

The contract (protocol + descriptor) is the integration surface; each project
implements its own client/server code. This repository's license is
`LicenseRef-Proprietary-Until-Owner-Decides` while the GUI is MIT — so no code is
copied across repos in either direction until the owner sets the license. The
protocol is fully specified by `jarvis mcp describe`; a QProcess-based client for the
GUI is small (framing + JSON parse + signal wiring).
