from datetime import UTC, datetime

from iagency.policy import POLICY_VERSION, evaluate
from iagency.types import Actor, Money, ProposedAction


def _action(**kwargs) -> ProposedAction:
    base = dict(
        action_id="a1",
        actor=Actor(id="bot", kind="agent", name="payments-bot"),
        verb="write_log",
        object_ref="app.log",
        environment="dev",
        irreversibility="reversible",
        data_class="internal",
        submitted_at=datetime(2026, 8, 12, tzinfo=UTC),
    )
    base.update(kwargs)
    return ProposedAction.model_validate(base)


def test_dev_reversible_internal_allows() -> None:
    v = evaluate(_action())
    assert v.decision == "allow"
    assert v.choices == []
    assert v.policy_version == POLICY_VERSION


def test_prod_gates_with_fixed_choices() -> None:
    v = evaluate(_action(environment="prod", verb="deploy", object_ref="api"))
    assert v.decision == "gate"
    assert [c.id for c in v.choices] == ["approve", "reject"]
    assert {c.resume for c in v.choices} == {"proceed", "halt"}
    assert any(r.code == "prod_environment" for r in v.reasons)


def test_irreversible_gates_even_in_dev() -> None:
    v = evaluate(_action(irreversibility="irreversible", verb="drop_table"))
    assert v.decision == "gate"
    assert any(r.code == "irreversible" for r in v.reasons)


def test_restricted_data_gates() -> None:
    v = evaluate(_action(data_class="restricted", verb="export"))
    assert v.decision == "gate"


def test_cost_threshold_gates() -> None:
    v = evaluate(_action(estimated_cost=Money(cents=100_000, currency="USD"), verb="transfer"))
    assert v.decision == "gate"
    assert any(r.code == "cost_threshold" for r in v.reasons)


def test_always_block_beats_everything() -> None:
    v = evaluate(
        _action(
            verb="exfiltrate",
            environment="dev",
            irreversibility="reversible",
            data_class="public",
        )
    )
    assert v.decision == "block"
    assert v.choices == []


def test_policy_is_deterministic() -> None:
    a = _action(environment="prod", verb="transfer", object_ref="acct-9")
    assert evaluate(a).model_dump() == evaluate(a).model_dump()
