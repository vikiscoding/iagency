"""Canonical types on the critical path.

Keep them small. Changing a field is a schema event.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

SCHEMA_VERSION = "0.2.0"
MAX_PARAMS_BYTES = 8 * 1024
MAX_CONTEXT_BYTES = 16 * 1024
BRIEF_CHAR_BUDGET = 1500
RATIONALE_CODES = frozenset(
    {
        "risk_accepted",
        "risk_too_high",
        "insufficient_context",
        "policy_exception",
        "better_alternative",
        "out_of_scope",
    }
)


def _jsonable(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


def canonical_json(obj: Any) -> str:
    """Stable JSON used for hashing. Datetimes as ISO-8601. Keys sorted."""
    return json.dumps(_jsonable(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class Actor(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    kind: Literal["agent", "workflow", "human", "system"]
    name: str = Field(..., min_length=1, max_length=128)


class HumanIdentity(BaseModel):
    id: str = Field(..., min_length=1, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=128)
    channel: Literal["cli", "web"] = "cli"


class Money(BaseModel):
    cents: int = Field(..., ge=0)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class Reason(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)
    fact: str = Field(..., min_length=1, max_length=240)


class Choice(BaseModel):
    id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=1, max_length=80)
    effect: str = Field(..., min_length=1, max_length=240)
    resume: Literal["proceed", "halt"]


class ProposedAction(BaseModel):
    action_id: str = Field(..., min_length=1, max_length=128)
    actor: Actor
    verb: str = Field(..., min_length=1, max_length=64)
    object_ref: str = Field(..., min_length=1, max_length=256)
    params: dict[str, Any] = Field(default_factory=dict)
    environment: Literal["dev", "staging", "prod"]
    irreversibility: Literal["reversible", "costly", "irreversible"]
    estimated_cost: Money | None = None
    data_class: Literal["public", "internal", "sensitive", "restricted"]
    raw_context: dict[str, Any] = Field(default_factory=dict)
    submitted_at: datetime

    @field_validator("verb")
    @classmethod
    def normalize_verb(cls, v: str) -> str:
        return v.strip().lower().replace(" ", "_")

    @field_validator("params")
    @classmethod
    def cap_params(cls, v: dict[str, Any]) -> dict[str, Any]:
        blob = canonical_json(v)
        if len(blob.encode("utf-8")) > MAX_PARAMS_BYTES:
            raise ValueError(f"params exceed {MAX_PARAMS_BYTES} bytes")
        return v

    @field_validator("raw_context")
    @classmethod
    def cap_context(cls, v: dict[str, Any]) -> dict[str, Any]:
        blob = canonical_json(v)
        if len(blob.encode("utf-8")) > MAX_CONTEXT_BYTES:
            raise ValueError(f"raw_context exceed {MAX_CONTEXT_BYTES} bytes")
        return v


class PolicyVerdict(BaseModel):
    decision: Literal["allow", "block", "gate"]
    policy_id: str
    policy_version: str
    reasons: list[Reason] = Field(default_factory=list)
    choices: list[Choice] = Field(default_factory=list)
    deadline_seconds: int = Field(default=3600, ge=1, le=7 * 24 * 3600)
    default_on_timeout: Literal["halt"] = "halt"

    @field_validator("choices")
    @classmethod
    def unique_choice_ids(cls, v: list[Choice]) -> list[Choice]:
        ids = [c.id for c in v]
        if len(ids) != len(set(ids)):
            raise ValueError("choice ids must be unique")
        return v


class Brief(BaseModel):
    gate_id: str
    title: str = Field(..., max_length=80)
    proposed: str = Field(..., max_length=280)
    why_human: list[str] = Field(..., min_length=1, max_length=6)
    choices: list[Choice] = Field(..., min_length=1)
    tradeoffs: list[str] = Field(default_factory=list, max_length=3)
    recommendation: str | None = Field(default=None, max_length=200)
    recommended_choice_id: str | None = None
    deeper_refs: list[str] = Field(default_factory=list, max_length=5)
    generator: Literal["template", "llm"] = "template"
    schema_version: str = SCHEMA_VERSION

    @model_validator(mode="after")
    def recommended_choice_must_exist(self) -> Brief:
        if self.recommended_choice_id is None:
            return self
        legal = {c.id for c in self.choices}
        if self.recommended_choice_id not in legal:
            self.recommended_choice_id = None
        return self

    def render(self) -> str:
        lines = [
            f"GATE {self.gate_id}",
            self.title,
            self.proposed,
            "Why human:",
            *[f"  - {w}" for w in self.why_human],
            "Choices:",
            *[f"  [{c.id}] {c.label} — {c.effect} ({c.resume})" for c in self.choices],
        ]
        if self.tradeoffs:
            lines.append("Tradeoffs:")
            lines.extend(f"  - {t}" for t in self.tradeoffs)
        if self.recommendation:
            lines.append(f"Recommendation: {self.recommendation}")
        if self.recommended_choice_id:
            lines.append(f"Suggested choice: {self.recommended_choice_id}")
        if self.deeper_refs:
            lines.append("Deeper: " + "; ".join(self.deeper_refs))
        return "\n".join(lines)

    def assert_budget(self) -> None:
        text = self.render()
        if len(text) > BRIEF_CHAR_BUDGET:
            raise ValueError(f"brief is {len(text)} chars; budget is {BRIEF_CHAR_BUDGET}")


class Decision(BaseModel):
    decision_id: str
    gate_id: str
    choice_id: str
    rationale_codes: list[str] = Field(..., min_length=1, max_length=4)
    rationale_text: str = Field(..., min_length=1, max_length=500)
    confidence: Literal["low", "medium", "high"]
    overrides_recommendation: bool = False
    actor: HumanIdentity
    decided_at: datetime
    brief_hash: str = Field(..., min_length=64, max_length=64)
    request_hash: str = Field(..., min_length=64, max_length=64)

    @field_validator("rationale_codes")
    @classmethod
    def known_codes(cls, v: list[str]) -> list[str]:
        unknown = [c for c in v if c not in RATIONALE_CODES]
        if unknown:
            raise ValueError(f"unknown rationale codes: {unknown}")
        if len(v) != len(set(v)):
            raise ValueError("rationale codes must be unique")
        return v


class LedgerRecord(BaseModel):
    seq: int = Field(..., ge=1)
    prev_hash: str = Field(..., min_length=64, max_length=64)
    record_type: Literal["auto_allow", "auto_block", "gate_opened", "decision", "timeout"]
    recorded_at: datetime
    body: dict[str, Any]
    hash: str = Field(..., min_length=64, max_length=64)


class ResumeToken(BaseModel):
    action_id: str
    gate_id: str | None
    status: Literal["proceed", "halt", "pending", "expired"]
    choice_id: str | None = None
    decision_id: str | None = None
    ledger_hash: str
    policy_version: str


class GateOpened(BaseModel):
    gate_id: str
    action: ProposedAction
    verdict: PolicyVerdict
    brief: Brief
    request_hash: str
    brief_hash: str
    created_at: datetime
    deadline_at: datetime
