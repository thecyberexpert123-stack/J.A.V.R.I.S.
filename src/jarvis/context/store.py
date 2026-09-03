"""User context store (ADR-0012): feedback ledger now; preferences later (M8b).

Local, inspectable, deletable. Context tunes what JARVIS *suggests* — it never
grants authority to act.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from jarvis.journal.sqlite import _utcnow, state_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    suggestion_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL CHECK (decision IN ('accepted', 'rejected')),
    reason TEXT NOT NULL DEFAULT '',
    suggestion_title TEXT NOT NULL DEFAULT '',
    created_utc TEXT NOT NULL
);
"""


def default_context_path(env: dict[str, str] | None = None) -> Path:
    return state_dir(env) / "context.db"


class ContextStore:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record_feedback(
        self, suggestion_id: str, decision: str, *, reason: str = "", title: str = ""
    ) -> None:
        if decision not in ("accepted", "rejected"):
            raise ValueError(f"invalid decision {decision!r}")
        self._conn.execute(
            "INSERT INTO feedback (suggestion_id, decision, reason, suggestion_title, created_utc)"
            " VALUES (?,?,?,?,?)"
            " ON CONFLICT(suggestion_id) DO UPDATE SET decision=excluded.decision,"
            " reason=excluded.reason, suggestion_title=excluded.suggestion_title,"
            " created_utc=excluded.created_utc",
            (suggestion_id, decision, reason, title, _utcnow()),
        )
        self._conn.commit()

    def decisions(self) -> dict[str, str]:
        rows = self._conn.execute("SELECT suggestion_id, decision FROM feedback").fetchall()
        return {str(r["suggestion_id"]): str(r["decision"]) for r in rows}

    def feedback_rows(self) -> list[dict[str, object]]:
        rows = self._conn.execute(
            "SELECT suggestion_id, decision, reason, suggestion_title, created_utc"
            " FROM feedback ORDER BY created_utc DESC"
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self) -> None:
        self._conn.close()
