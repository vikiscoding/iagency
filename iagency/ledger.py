"""Layer C — append-only hash-chained ledger. SQLite is the Phase 0 store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from iagency.types import (
    Decision,
    GateOpened,
    LedgerRecord,
    canonical_json,
)

GENESIS_HASH = "0" * 64
RecordType = Literal["auto_allow", "auto_block", "gate_opened", "decision", "timeout"]


def compute_hash(
    *,
    seq: int,
    prev_hash: str,
    record_type: str,
    recorded_at: datetime,
    body: dict[str, Any],
) -> str:
    payload = {
        "seq": seq,
        "prev_hash": prev_hash,
        "record_type": record_type,
        "recorded_at": recorded_at.isoformat(),
        "body": body,
    }
    material = prev_hash + "\n" + canonical_json(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class Ledger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._init()

    def close(self) -> None:
        self._conn.close()

    def _init(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger (
                seq INTEGER PRIMARY KEY,
                prev_hash TEXT NOT NULL,
                record_type TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                body_json TEXT NOT NULL,
                hash TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS gate_index (
                gate_id TEXT PRIMARY KEY,
                seq_opened INTEGER NOT NULL,
                status TEXT NOT NULL,
                deadline_at TEXT NOT NULL,
                action_id TEXT NOT NULL
            );
            """
        )
        self._conn.commit()

    def last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return row["hash"] if row else GENESIS_HASH

    def last_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) AS m FROM ledger").fetchone()
        return int(row["m"] or 0)

    def append(
        self,
        record_type: RecordType,
        body: dict[str, Any],
        recorded_at: datetime,
        *,
        gate_id: str | None = None,
        action_id: str | None = None,
        deadline_at: datetime | None = None,
        gate_status: str | None = None,
    ) -> LedgerRecord:
        if recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be timezone-aware")
        seq = self.last_seq() + 1
        prev_hash = self.last_hash()
        digest = compute_hash(
            seq=seq,
            prev_hash=prev_hash,
            record_type=record_type,
            recorded_at=recorded_at,
            body=body,
        )
        recorded_iso = recorded_at.isoformat()
        body_json = canonical_json(body)
        try:
            self._conn.execute("BEGIN")
            self._conn.execute(
                """
                INSERT INTO ledger (seq, prev_hash, record_type, recorded_at, body_json, hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (seq, prev_hash, record_type, recorded_iso, body_json, digest),
            )
            if record_type == "gate_opened":
                if not gate_id or not action_id or deadline_at is None:
                    raise ValueError("gate_opened requires gate_id, action_id, deadline_at")
                self._conn.execute(
                    """
                    INSERT INTO gate_index (gate_id, seq_opened, status, deadline_at, action_id)
                    VALUES (?, ?, 'pending', ?, ?)
                    """,
                    (gate_id, seq, deadline_at.isoformat(), action_id),
                )
            elif record_type in {"decision", "timeout"} and gate_id and gate_status:
                self._conn.execute(
                    "UPDATE gate_index SET status = ? WHERE gate_id = ?",
                    (gate_status, gate_id),
                )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise

        return LedgerRecord(
            seq=seq,
            prev_hash=prev_hash,
            record_type=record_type,
            recorded_at=recorded_at,
            body=body,
            hash=digest,
        )

    def records(self) -> list[LedgerRecord]:
        rows = self._conn.execute(
            "SELECT seq, prev_hash, record_type, recorded_at, body_json, hash "
            "FROM ledger ORDER BY seq ASC"
        ).fetchall()
        out: list[LedgerRecord] = []
        for row in rows:
            out.append(
                LedgerRecord(
                    seq=row["seq"],
                    prev_hash=row["prev_hash"],
                    record_type=row["record_type"],
                    recorded_at=datetime.fromisoformat(row["recorded_at"]),
                    body=json.loads(row["body_json"]),
                    hash=row["hash"],
                )
            )
        return out

    def verify(self) -> None:
        """Recompute the chain. Raises ValueError on any break. No model involved."""
        expected_prev = GENESIS_HASH
        expected_seq = 1
        rows = self._conn.execute(
            "SELECT seq, prev_hash, record_type, recorded_at, body_json, hash "
            "FROM ledger ORDER BY seq ASC"
        ).fetchall()
        for row in rows:
            if row["seq"] != expected_seq:
                raise ValueError(f"seq gap: expected {expected_seq}, got {row['seq']}")
            if row["prev_hash"] != expected_prev:
                raise ValueError(f"prev_hash mismatch at seq {row['seq']}")
            body = json.loads(row["body_json"])
            recorded_at = datetime.fromisoformat(row["recorded_at"])
            digest = compute_hash(
                seq=row["seq"],
                prev_hash=row["prev_hash"],
                record_type=row["record_type"],
                recorded_at=recorded_at,
                body=body,
            )
            if digest != row["hash"]:
                raise ValueError(f"hash mismatch at seq {row['seq']}")
            expected_prev = row["hash"]
            expected_seq += 1

    def get_gate(self, gate_id: str) -> GateOpened | None:
        idx = self._conn.execute(
            "SELECT seq_opened FROM gate_index WHERE gate_id = ?", (gate_id,)
        ).fetchone()
        if not idx:
            return None
        row = self._conn.execute(
            "SELECT body_json FROM ledger WHERE seq = ?", (idx["seq_opened"],)
        ).fetchone()
        if not row:
            return None
        return GateOpened.model_validate(json.loads(row["body_json"]))

    def gate_status(self, gate_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM gate_index WHERE gate_id = ?", (gate_id,)
        ).fetchone()
        return row["status"] if row else None

    def pending_gates(self) -> list[tuple[str, str, str]]:
        rows = self._conn.execute(
            "SELECT gate_id, action_id, deadline_at FROM gate_index "
            "WHERE status = 'pending' ORDER BY deadline_at ASC"
        ).fetchall()
        return [(r["gate_id"], r["action_id"], r["deadline_at"]) for r in rows]

    def decision_for(self, gate_id: str) -> Decision | None:
        rows = self._conn.execute(
            "SELECT body_json FROM ledger WHERE record_type = 'decision' ORDER BY seq ASC"
        ).fetchall()
        for row in rows:
            body = json.loads(row["body_json"])
            if body.get("gate_id") == gate_id:
                return Decision.model_validate(body)
        return None
