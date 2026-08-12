"""Layer B compressor. One HTTP call. Template fallback. No SDK.

Never imported by policy.py, ledger.py, or loop.py.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from iagency.brief import render_brief
from iagency.types import Brief, PolicyVerdict, ProposedAction

DEFAULT_MODEL = "grok-4.6"
DEFAULT_TIMEOUT_SECONDS = 8
API_URL = "https://api.x.ai/v1/chat/completions"

SYSTEM_PROMPT = (
    "Compress a gated action into a predicament brief. "
    "Return JSON only. Prefer omission over filler. No soothing language. "
    "Do not invent choices. Do not change reason codes. "
    "recommended_choice_id must be one of the provided choice ids, or null."
)

FILL_SCHEMA = {
    "type": "object",
    "properties": {
        "proposed": {
            "type": "string",
            "description": "One or two factual sentences, max 280 characters.",
        },
        "tradeoffs": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Zero to three short trade-off lines.",
        },
        "recommendation": {
            "type": ["string", "null"],
            "description": "Optional one-line rationale for the suggested choice.",
        },
        "recommended_choice_id": {
            "type": ["string", "null"],
            "description": "Must be one of the provided choice ids, or null.",
        },
    },
    "required": ["proposed", "tradeoffs", "recommendation", "recommended_choice_id"],
    "additionalProperties": False,
}


class LlmFill:
    """Parsed model fill. Validated in from_mapping, not a ledger type."""

    def __init__(
        self,
        proposed: str,
        tradeoffs: list[str],
        recommendation: str | None,
        recommended_choice_id: str | None,
    ) -> None:
        self.proposed = proposed
        self.tradeoffs = tradeoffs
        self.recommendation = recommendation
        self.recommended_choice_id = recommended_choice_id

    @classmethod
    def from_mapping(cls, data: object) -> LlmFill:
        if not isinstance(data, dict):
            raise ValueError("fill must be an object")
        proposed = data.get("proposed")
        if not isinstance(proposed, str) or not proposed.strip():
            raise ValueError("proposed must be a non-empty string")
        raw_tradeoffs = data.get("tradeoffs") or []
        if not isinstance(raw_tradeoffs, list):
            raise ValueError("tradeoffs must be a list")
        tradeoffs = [t.strip() for t in raw_tradeoffs if isinstance(t, str) and t.strip()]
        rec = data.get("recommendation")
        if rec is not None and not isinstance(rec, str):
            raise ValueError("recommendation must be a string or null")
        rec_id = data.get("recommended_choice_id")
        if rec_id is not None and not isinstance(rec_id, str):
            raise ValueError("recommended_choice_id must be a string or null")
        return cls(
            proposed=proposed.strip()[:280],
            tradeoffs=[t[:160] for t in tradeoffs[:3]],
            recommendation=(
                rec.strip()[:200] if isinstance(rec, str) and rec.strip() else None
            ),
            recommended_choice_id=(
                rec_id.strip() if isinstance(rec_id, str) and rec_id.strip() else None
            ),
        )


def render_brief_llm(gate_id: str, action: ProposedAction, verdict: PolicyVerdict) -> Brief:
    """Template first. Overlay model fill. Any failure returns the template."""
    template = render_brief(gate_id, action, verdict)
    try:
        fill = _call_model(action, verdict)
        return _merge(template, fill)
    except Exception:
        return template


def _merge(template: Brief, fill: LlmFill) -> Brief:
    legal = {c.id for c in template.choices}
    rec_id = fill.recommended_choice_id if fill.recommended_choice_id in legal else None
    merged = template.model_copy(
        update={
            "proposed": fill.proposed,
            "tradeoffs": fill.tradeoffs,
            "recommendation": fill.recommendation,
            "recommended_choice_id": rec_id,
            "generator": "llm",
        }
    )
    try:
        merged.assert_budget()
    except ValueError:
        return template
    return merged


def _call_model(action: ProposedAction, verdict: PolicyVerdict) -> LlmFill:
    key = os.environ.get("XAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("XAI_API_KEY is not set")
    timeout = float(os.environ.get("IAGENCY_BRIEF_TIMEOUT", DEFAULT_TIMEOUT_SECONDS))
    model = os.environ.get("IAGENCY_MODEL", DEFAULT_MODEL)
    user_payload = {
        "action": action.model_dump(mode="json"),
        "reasons": [r.model_dump(mode="json") for r in verdict.reasons],
        "choice_ids": [c.id for c in verdict.choices],
        "choices": [c.model_dump(mode="json") for c in verdict.choices],
    }
    body = {
        "model": model,
        "temperature": 0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "brief_fill",
                "schema": FILL_SCHEMA,
                "strict": True,
            },
        },
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(f"brief model request failed: {e}") from e
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as e:
        raise RuntimeError("brief model response missing content") from e
    return LlmFill.from_mapping(json.loads(content))
