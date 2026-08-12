from datetime import UTC, datetime

import pytest

from iagency.brief import render_brief
from iagency.policy import evaluate
from iagency.types import BRIEF_CHAR_BUDGET, Actor, ProposedAction


def _prod_transfer() -> ProposedAction:
    return ProposedAction(
        action_id="wire-1",
        actor=Actor(id="treasury", kind="agent", name="treasury-agent"),
        verb="transfer",
        object_ref="acct-4419",
        params={"cents": 250000, "to": "vendor-88"},
        environment="prod",
        irreversibility="costly",
        data_class="sensitive",
        submitted_at=datetime(2026, 8, 12, 15, 0, tzinfo=UTC),
    )


def test_brief_copies_policy_choices_and_stays_short() -> None:
    action = _prod_transfer()
    verdict = evaluate(action)
    brief = render_brief("gate1", action, verdict)
    assert [c.id for c in brief.choices] == [c.id for c in verdict.choices]
    assert brief.generator == "template"
    assert brief.recommendation is None
    assert len(brief.render()) <= BRIEF_CHAR_BUDGET
    assert "prod" in brief.proposed


def test_brief_refuses_non_gate() -> None:
    action = ProposedAction(
        action_id="log-1",
        actor=Actor(id="bot", kind="agent", name="bot"),
        verb="write_log",
        object_ref="app.log",
        environment="dev",
        irreversibility="reversible",
        data_class="internal",
        submitted_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="only produced for gated"):
        render_brief("g", action, evaluate(action))


def test_same_inputs_same_brief() -> None:
    action = _prod_transfer()
    v = evaluate(action)
    a = render_brief("g", action, v)
    b = render_brief("g", action, v)
    assert a.model_dump() == b.model_dump()
