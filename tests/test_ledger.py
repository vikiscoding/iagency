from datetime import UTC, datetime

import pytest

from iagency.ledger import GENESIS_HASH, Ledger, compute_hash


def test_empty_chain_verifies(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    ledger.verify()
    assert ledger.last_hash() == GENESIS_HASH
    assert ledger.last_seq() == 0
    ledger.close()


def test_append_and_recompute(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    now = datetime(2026, 8, 12, tzinfo=UTC)
    r1 = ledger.append("auto_allow", {"k": 1}, now)
    r2 = ledger.append("auto_block", {"k": 2}, now)
    assert r1.prev_hash == GENESIS_HASH
    assert r2.prev_hash == r1.hash
    assert r1.seq == 1 and r2.seq == 2
    ledger.verify()
    ledger.close()


def test_tamper_is_detected(tmp_path) -> None:
    path = tmp_path / "l.sqlite"
    ledger = Ledger(path)
    now = datetime(2026, 8, 12, tzinfo=UTC)
    ledger.append("auto_allow", {"ok": True}, now)
    ledger.close()

    import sqlite3

    conn = sqlite3.connect(path)
    conn.execute("UPDATE ledger SET body_json = '{\"ok\": false}' WHERE seq = 1")
    conn.commit()
    conn.close()

    ledger = Ledger(path)
    with pytest.raises(ValueError, match="hash mismatch"):
        ledger.verify()
    ledger.close()


def test_hash_function_is_stable() -> None:
    now = datetime(2026, 8, 12, tzinfo=UTC)
    a = compute_hash(
        seq=1, prev_hash=GENESIS_HASH, record_type="auto_allow", recorded_at=now, body={"x": 1}
    )
    b = compute_hash(
        seq=1, prev_hash=GENESIS_HASH, record_type="auto_allow", recorded_at=now, body={"x": 1}
    )
    c = compute_hash(
        seq=1, prev_hash=GENESIS_HASH, record_type="auto_allow", recorded_at=now, body={"x": 2}
    )
    assert a == b
    assert a != c
