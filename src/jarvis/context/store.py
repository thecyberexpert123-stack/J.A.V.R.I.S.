"""User context store (ADR-0012): feedback ledger now; preferences later (M8b).

Local, inspectable, deletable. Context tunes what JARVIS *suggests* — it never
grants authority to act.

M9c hardening (ADR-0013): feedback text is untrusted ingress — it is scanned
for injection patterns at write time, and every hashed entry carries a content
hash chained into a table digest (``store_meta.chain_digest``), so silent row
edits, deletions, or forgeries are reported by ``verify_integrity()``. Rows
written before 1.4.0 have no hash (reported as legacy; they gain one on their
next upsert). Honest limitation: an attacker with arbitrary DB write access
can recompute hashes and the digest — this raises the cost of *invisible,
gradual* tampering, it is not a cryptographic anchor.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path

from jarvis.journal.sqlite import _utcnow, state_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    suggestion_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reason TEXT NOT NULL DEFAULT '',
    suggestion_title TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL,
    entry_hash TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Pre-1.4.0 databases lack the hash column; CREATE IF NOT EXISTS cannot add it.
_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("entry_hash", "ALTER TABLE feedback ADD COLUMN entry_hash TEXT NOT NULL DEFAULT ''"),
)

# Write-time scan: this table feeds future suggestions (M8b), so poisoned
# feedback would become poisoned suggestions — the memory-poisoning class from
# the landscape research. Patterns are deliberately tight to avoid refusing
# honest calibration reasons.
_SCAN_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|earlier)",
        r"disregard\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above|your)",
        r"system\s*prompt\s*:",
        r"you\s+are\s+now\s+(?:a|an|the)\b",
        r"new\s+(?:high(?:est)?\s+priority\s+)?instructions\s*:",
        r"<\|[^>]*\|>",
    )
)


def _scan_untrusted(field: str, value: str) -> None:
    for pattern in _SCAN_PATTERNS:
        match = pattern.search(value)
        if match is not None:
            raise ValueError(
                f"{field} looks like prompt injection (pattern {pattern.pattern!r}); "
                "not recorded. Rephrase the reason without instruction-like text."
            )


def _row_hash(
    suggestion_id: object, decision: object, reason: object, title: object, created_utc: object
) -> str:
    canonical = "\x1f".join(
        (str(suggestion_id), str(decision), str(reason), str(title), str(created_utc))
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _chain_digest(entry_hashes: Sequence[str]) -> str:
    return hashlib.sha256("\x1f".join(sorted(entry_hashes)).encode("utf-8")).hexdigest()


def default_context_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "context.db"


class ContextStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        existing = {str(row["name"]) for row in self._conn.execute("PRAGMA table_info(feedback)")}
        for column, sql in _MIGRATIONS:
            if column not in existing:
                self._conn.execute(sql)
        self._conn.commit()

    def record_feedback(
        self, suggestion_id: str, decision: str, *, reason: str = "", title: str = ""
    ) -> None:
        if decision not in ("accepted", "rejected"):
            raise ValueError(f"invalid decision {decision!r}")
        _scan_untrusted("reason", reason)
        _scan_untrusted("title", title)
        created = _utcnow()
        entry_hash = _row_hash(suggestion_id, decision, reason, title, created)
        self._conn.execute(
            "INSERT INTO feedback (suggestion_id, decision, reason, suggestion_title,"
            " created_utc, entry_hash)"
            " VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(suggestion_id) DO UPDATE SET decision=excluded.decision,"
            " reason=excluded.reason, suggestion_title=excluded.suggestion_title,"
            " created_utc=excluded.created_utc, entry_hash=excluded.entry_hash",
            (suggestion_id, decision, reason, title, created, entry_hash),
        )
        self._refresh_digest()
        self._conn.commit()

    def _refresh_digest(self) -> None:
        rows = self._conn.execute(
            "SELECT entry_hash FROM feedback WHERE entry_hash != ''"
        ).fetchall()
        digest = _chain_digest([str(r["entry_hash"]) for r in rows])
        self._conn.execute(
            "INSERT INTO store_meta (key, value) VALUES ('chain_digest', ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (digest,),
        )

    def decisions(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT suggestion_id, decision FROM feedback").fetchall()
        return {str(r["suggestion_id"]): str(r["decision"]) for r in rows}

    def feedback_rows(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT suggestion_id, decision, reason, suggestion_title, created_utc"
            " FROM feedback ORDER BY created_utc DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def verify_integrity(self) -> dict[str, object]:
        """Recompute hashes and the chain digest; report, never raise, on drift."""
        rows = self._conn.execute(
            "SELECT suggestion_id, decision, reason, suggestion_title, created_utc, entry_hash"
            " FROM feedback"
        ).fetchall()
        legacy = 0
        mismatched: list[str] = []
        hashes: list[str] = []
        for row in rows:
            entry_hash = str(row["entry_hash"])
            if not entry_hash:
                legacy += 1
                continue
            hashes.append(entry_hash)
            expected = _row_hash(
                row["suggestion_id"],
                row["decision"],
                row["reason"],
                row["suggestion_title"],
                row["created_utc"],
            )
            if expected != entry_hash:
                mismatched.append(str(row["suggestion_id"]))
        digest_ok: bool | None = None
        if hashes:
            stored = self._conn.execute(
                "SELECT value FROM store_meta WHERE key = 'chain_digest'"
            ).fetchone()
            digest_ok = _chain_digest(hashes) == (str(stored["value"]) if stored else "")
        detail = ""
        if mismatched:
            detail = "content hash mismatch for: " + ", ".join(sorted(mismatched)[:3])
        elif digest_ok is False:
            detail = "chain digest mismatch (rows edited in, added, or removed without re-hash)"
        return {
            "total": len(rows),
            "hashed": len(hashes),
            "legacy_unhashed": legacy,
            "row_hashes_ok": not mismatched,
            "chain_digest_ok": digest_ok,
            "ok": not mismatched and digest_ok is not False,
            "detail": detail,
        }

    def close(self) -> None:
        self._conn.close()
