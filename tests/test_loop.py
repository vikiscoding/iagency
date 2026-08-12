from datetime import UTC, datetime, timedelta

import pytest

from iagency.ledger import Ledger
from iagency.loop import decide, resume, submit
from iagency.types import Actor, HumanIdentity, Money, ProposedAction

NOW = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)


def _clock(t: datetime):
    return lambda: t


def _human() -> HumanIdentity:
    return HumanIdentity(id="reviewer", display_name="Reviewer", channel="cli")


def _action(**kwargs) -> ProposedAction:
    base = dict(
        action_id="act-1",
        actor=Actor(id="treasury", kind="agent", name="treasury-agent"),
        verb="write_log",
        object_ref="app.log",
        environment="dev",
        irreversibility="reversible",
        data_class="internal",
        submitted_at=NOW,
    )
    base.update(kwargs)
    return ProposedAction.model_validate(base)


def test_auto_allow_resumes_proceed(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    token = submit(ledger, _action(), clock=_clock(NOW))
    assert token.status == "proceed"
    assert token.gate_id is None
    ledger.verify()
    assert ledger.records()[0].record_type == "auto_allow"
    ledger.close()


def test_auto_block_resumes_halt(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    token = submit(ledger, _action(verb="disable_audit"), clock=_clock(NOW))
    assert token.status == "halt"
    assert ledger.records()[0].record_type == "auto_block"
    ledger.close()


def test_full_human_loop_approve(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    action = _action(
        verb="transfer",
        object_ref="acct-9",
        environment="prod",
        estimated_cost=Money(cents=250_000, currency="USD"),
    )
    pending = submit(ledger, action, clock=_clock(NOW))
    assert pending.status == "pending"
    assert pending.gate_id

    token = decide(
        ledger,
        gate_id=pending.gate_id,
        choice_id="approve",
        rationale_codes=["risk_accepted"],
        rationale_text="Vendor is on the allow-list and dual-control already ran.",
        confidence="high",
        actor=_human(),
        clock=_clock(NOW + timedelta(minutes=5)),
    )
    assert token.status == "proceed"
    assert token.choice_id == "approve"
    later = resume(ledger, pending.gate_id, clock=_clock(NOW + timedelta(minutes=6)))
    assert later.status == "proceed"
    ledger.verify()
    types = [r.record_type for r in ledger.records()]
    assert types == ["gate_opened", "decision"]
    ledger.close()


def test_reject_resumes_halt(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    pending = submit(ledger, _action(environment="prod", verb="deploy"), clock=_clock(NOW))
    token = decide(
        ledger,
        gate_id=pending.gate_id,
        choice_id="reject",
        rationale_codes=["risk_too_high"],
        rationale_text="Change window is closed.",
        confidence="medium",
        actor=_human(),
        clock=_clock(NOW + timedelta(minutes=1)),
    )
    assert token.status == "halt"
    ledger.close()


def test_illegal_choice_is_rejected(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    pending = submit(ledger, _action(environment="prod"), clock=_clock(NOW))
    with pytest.raises(ValueError, match="not in the opened choice set"):
        decide(
            ledger,
            gate_id=pending.gate_id,
            choice_id="approve_and_also_wire_me",
            rationale_codes=["risk_accepted"],
            rationale_text="no",
            confidence="low",
            actor=_human(),
            clock=_clock(NOW + timedelta(seconds=1)),
        )
    assert ledger.gate_status(pending.gate_id) == "pending"
    ledger.close()


def test_silence_expires_to_halt(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    pending = submit(ledger, _action(environment="prod"), clock=_clock(NOW))
    token = resume(ledger, pending.gate_id, clock=_clock(NOW + timedelta(hours=2)))
    assert token.status == "expired"
    assert ledger.gate_status(pending.gate_id) == "expired"
    with pytest.raises(TimeoutError):
        decide(
            ledger,
            gate_id=pending.gate_id,
            choice_id="approve",
            rationale_codes=["risk_accepted"],
            rationale_text="too late",
            confidence="low",
            actor=_human(),
            clock=_clock(NOW + timedelta(hours=2, minutes=1)),
        )
    ledger.verify()
    assert [r.record_type for r in ledger.records()] == ["gate_opened", "timeout"]
    ledger.close()


def test_double_decide_rejected(tmp_path) -> None:
    ledger = Ledger(tmp_path / "l.sqlite")
    pending = submit(ledger, _action(environment="prod"), clock=_clock(NOW))
    decide(
        ledger,
        gate_id=pending.gate_id,
        choice_id="approve",
        rationale_codes=["risk_accepted"],
        rationale_text="ok",
        confidence="high",
        actor=_human(),
        clock=_clock(NOW + timedelta(seconds=2)),
    )
    with pytest.raises(ValueError, match="decided"):
        decide(
            ledger,
            gate_id=pending.gate_id,
            choice_id="reject",
            rationale_codes=["risk_too_high"],
            rationale_text="changed mind",
            confidence="low",
            actor=_human(),
            clock=_clock(NOW + timedelta(seconds=3)),
        )
    ledger.close()
