"""The critical path. Policy → brief → ledger → resume. No LLM."""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from iagency.brief import render_brief
from iagency.ledger import Ledger
from iagency.policy import evaluate
from iagency.types import (
    Brief,
    Decision,
    GateOpened,
    HumanIdentity,
    ProposedAction,
    ResumeToken,
    canonical_json,
)

Clock = Callable[[], datetime]


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _sha(obj: object) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def submit(ledger: Ledger, action: ProposedAction, *, clock: Clock = _now_utc) -> ResumeToken:
    verdict = evaluate(action)
    now = clock()

    if verdict.decision == "allow":
        rec = ledger.append(
            "auto_allow",
            {
                "action": action.model_dump(mode="json"),
                "verdict": verdict.model_dump(mode="json"),
            },
            now,
        )
        return ResumeToken(
            action_id=action.action_id,
            gate_id=None,
            status="proceed",
            ledger_hash=rec.hash,
            policy_version=verdict.policy_version,
        )

    if verdict.decision == "block":
        rec = ledger.append(
            "auto_block",
            {
                "action": action.model_dump(mode="json"),
                "verdict": verdict.model_dump(mode="json"),
            },
            now,
        )
        return ResumeToken(
            action_id=action.action_id,
            gate_id=None,
            status="halt",
            ledger_hash=rec.hash,
            policy_version=verdict.policy_version,
        )

    gate_id = uuid.uuid4().hex
    brief = render_brief(gate_id, action, verdict)
    deadline_at = now + timedelta(seconds=verdict.deadline_seconds)
    request_hash = _sha({"action": action, "verdict": verdict})
    brief_hash = _sha(brief)
    opened = GateOpened(
        gate_id=gate_id,
        action=action,
        verdict=verdict,
        brief=brief,
        request_hash=request_hash,
        brief_hash=brief_hash,
        created_at=now,
        deadline_at=deadline_at,
    )
    rec = ledger.append(
        "gate_opened",
        opened.model_dump(mode="json"),
        now,
        gate_id=gate_id,
        action_id=action.action_id,
        deadline_at=deadline_at,
    )
    return ResumeToken(
        action_id=action.action_id,
        gate_id=gate_id,
        status="pending",
        ledger_hash=rec.hash,
        policy_version=verdict.policy_version,
    )


def expire_if_due(ledger: Ledger, gate_id: str, *, clock: Clock = _now_utc) -> ResumeToken | None:
    opened = ledger.get_gate(gate_id)
    if opened is None:
        raise KeyError(f"unknown gate {gate_id}")
    status = ledger.gate_status(gate_id)
    now = clock()
    if status != "pending":
        return None
    if now <= opened.deadline_at:
        return None
    rec = ledger.append(
        "timeout",
        {
            "gate_id": gate_id,
            "action_id": opened.action.action_id,
            "default": opened.verdict.default_on_timeout,
        },
        now,
        gate_id=gate_id,
        gate_status="expired",
    )
    return ResumeToken(
        action_id=opened.action.action_id,
        gate_id=gate_id,
        status="expired",
        ledger_hash=rec.hash,
        policy_version=opened.verdict.policy_version,
    )


def decide(
    ledger: Ledger,
    *,
    gate_id: str,
    choice_id: str,
    rationale_codes: list[str],
    rationale_text: str,
    confidence: str,
    actor: HumanIdentity,
    clock: Clock = _now_utc,
) -> ResumeToken:
    expired = expire_if_due(ledger, gate_id, clock=clock)
    if expired is not None:
        raise TimeoutError(f"gate {gate_id} expired; recorded as halt")

    opened = ledger.get_gate(gate_id)
    if opened is None:
        raise KeyError(f"unknown gate {gate_id}")
    status = ledger.gate_status(gate_id)
    if status == "expired":
        raise TimeoutError(f"gate {gate_id} expired; recorded as halt")
    if status != "pending":
        raise ValueError(f"gate {gate_id} is {status}, not pending")

    legal = {c.id: c for c in opened.verdict.choices}
    if choice_id not in legal:
        raise ValueError(f"choice '{choice_id}' is not in the opened choice set")

    now = clock()
    decision = Decision(
        decision_id=uuid.uuid4().hex,
        gate_id=gate_id,
        choice_id=choice_id,
        rationale_codes=rationale_codes,
        rationale_text=rationale_text,
        confidence=confidence,  # type: ignore[arg-type]
        overrides_recommendation=False,
        actor=actor,
        decided_at=now,
        brief_hash=opened.brief_hash,
        request_hash=opened.request_hash,
    )
    rec = ledger.append(
        "decision",
        decision.model_dump(mode="json"),
        now,
        gate_id=gate_id,
        gate_status="decided",
    )
    return ResumeToken(
        action_id=opened.action.action_id,
        gate_id=gate_id,
        status=legal[choice_id].resume,
        choice_id=choice_id,
        decision_id=decision.decision_id,
        ledger_hash=rec.hash,
        policy_version=opened.verdict.policy_version,
    )


def resume(ledger: Ledger, gate_id: str, *, clock: Clock = _now_utc) -> ResumeToken:
    expired = expire_if_due(ledger, gate_id, clock=clock)
    if expired is not None:
        return expired
    opened = ledger.get_gate(gate_id)
    if opened is None:
        raise KeyError(f"unknown gate {gate_id}")
    status = ledger.gate_status(gate_id)
    if status == "pending":
        return ResumeToken(
            action_id=opened.action.action_id,
            gate_id=gate_id,
            status="pending",
            ledger_hash=ledger.last_hash(),
            policy_version=opened.verdict.policy_version,
        )
    if status == "expired":
        return ResumeToken(
            action_id=opened.action.action_id,
            gate_id=gate_id,
            status="expired",
            ledger_hash=ledger.last_hash(),
            policy_version=opened.verdict.policy_version,
        )
    decision = ledger.decision_for(gate_id)
    if decision is None:
        raise ValueError(f"gate {gate_id} marked decided but no decision record")
    legal = {c.id: c for c in opened.verdict.choices}
    return ResumeToken(
        action_id=opened.action.action_id,
        gate_id=gate_id,
        status=legal[decision.choice_id].resume,
        choice_id=decision.choice_id,
        decision_id=decision.decision_id,
        ledger_hash=ledger.last_hash(),
        policy_version=opened.verdict.policy_version,
    )


def brief_for(ledger: Ledger, gate_id: str) -> Brief:
    opened = ledger.get_gate(gate_id)
    if opened is None:
        raise KeyError(f"unknown gate {gate_id}")
    return opened.brief
