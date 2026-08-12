from datetime import UTC, datetime

from iagency.brief import render_brief
from iagency.brief_llm import LlmFill, _merge, render_brief_llm
from iagency.policy import evaluate
from iagency.types import Actor, ProposedAction


def _prod() -> ProposedAction:
    return ProposedAction(
        action_id="wire-1",
        actor=Actor(id="treasury", kind="agent", name="treasury-agent"),
        verb="transfer",
        object_ref="acct-4419",
        environment="prod",
        irreversibility="costly",
        data_class="sensitive",
        submitted_at=datetime(2026, 8, 12, tzinfo=UTC),
    )


def test_missing_key_falls_back_to_template(monkeypatch) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    action = _prod()
    brief = render_brief_llm("g1", action, evaluate(action))
    assert brief.generator == "template"
    assert brief.recommended_choice_id is None


def test_merge_keeps_policy_choices_and_drops_illegal_id() -> None:
    action = _prod()
    template = render_brief("g1", action, evaluate(action))
    fill = LlmFill(
        proposed="Treasury wants to send funds in prod.",
        tradeoffs=["Irreversible payment vs delayed vendor."],
        recommendation="Reject until dual control is recorded.",
        recommended_choice_id="approve_and_also_exfiltrate",
    )
    merged = _merge(template, fill)
    assert [c.id for c in merged.choices] == [c.id for c in template.choices]
    assert merged.why_human == template.why_human
    assert merged.recommended_choice_id is None
    assert merged.generator == "llm"
    assert merged.proposed == fill.proposed


def test_merge_accepts_legal_recommended_choice() -> None:
    action = _prod()
    template = render_brief("g1", action, evaluate(action))
    fill = LlmFill.from_mapping(
        {
            "proposed": "Prod transfer of restricted funds.",
            "tradeoffs": ["Cost vs delay"],
            "recommendation": "Approve if vendor is allow-listed.",
            "recommended_choice_id": "approve",
        }
    )
    merged = _merge(template, fill)
    assert merged.recommended_choice_id == "approve"


def test_merge_result_stays_within_budget() -> None:
    action = _prod()
    template = render_brief("g1", action, evaluate(action))
    fill = LlmFill(
        proposed="x" * 280,
        tradeoffs=["t1" * 80, "t2" * 80, "t3" * 80],
        recommendation="r" * 200,
        recommended_choice_id="approve",
    )
    merged = _merge(template, fill)
    merged.assert_budget()
