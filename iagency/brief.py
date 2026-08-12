"""Layer B template. Owns choices and reason codes. Fallback when the compressor fails."""

from __future__ import annotations

from iagency.types import Brief, PolicyVerdict, ProposedAction


def render_brief(gate_id: str, action: ProposedAction, verdict: PolicyVerdict) -> Brief:
    if verdict.decision != "gate":
        raise ValueError("brief is only produced for gated actions")
    if not verdict.choices:
        raise ValueError("gated verdict must carry a choice set")

    cost = (
        f"{action.estimated_cost.cents} {action.estimated_cost.currency} cents"
        if action.estimated_cost
        else "unspecified cost"
    )
    proposed = (
        f"{action.actor.name} ({action.actor.kind}) wants to {action.verb} "
        f"{action.object_ref} in {action.environment} ({action.irreversibility}, {cost})."
    )
    if len(proposed) > 280:
        proposed = proposed[:277] + "..."

    title = f"{action.verb} {action.object_ref}"[:80]
    why = [f"{r.code}: {r.fact}" for r in verdict.reasons]
    refs = [f"action:{action.action_id}", f"policy:{verdict.policy_id}@{verdict.policy_version}"]

    brief = Brief(
        gate_id=gate_id,
        title=title,
        proposed=proposed,
        why_human=why,
        choices=list(verdict.choices),
        tradeoffs=[],
        recommendation=None,
        deeper_refs=refs,
        generator="template",
    )
    brief.assert_budget()
    return brief
