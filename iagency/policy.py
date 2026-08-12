"""Layer A — deterministic policy. No I/O. No LLM."""

from __future__ import annotations

from iagency.types import Choice, PolicyVerdict, ProposedAction, Reason

POLICY_ID = "default"
POLICY_VERSION = "0.1.0"

ALWAYS_BLOCK = frozenset({"exfiltrate", "disable_audit"})
COST_GATE_CENTS = 100_000
GATE_DEADLINE_SECONDS = 3600

GATE_CHOICES = (
    Choice(
        id="approve",
        label="Approve",
        effect="Allow the proposed action to proceed.",
        resume="proceed",
    ),
    Choice(
        id="reject",
        label="Reject",
        effect="Block the proposed action.",
        resume="halt",
    ),
)


def evaluate(action: ProposedAction) -> PolicyVerdict:
    reasons: list[Reason] = []

    if action.verb in ALWAYS_BLOCK:
        reasons.append(
            Reason(code="always_block_verb", fact=f"verb '{action.verb}' is never allowed")
        )
        return PolicyVerdict(
            decision="block",
            policy_id=POLICY_ID,
            policy_version=POLICY_VERSION,
            reasons=reasons,
        )

    if action.environment == "prod":
        reasons.append(Reason(code="prod_environment", fact="action targets prod"))
    if action.irreversibility == "irreversible":
        reasons.append(
            Reason(code="irreversible", fact="action is marked irreversible")
        )
    if action.data_class == "restricted":
        reasons.append(
            Reason(code="restricted_data", fact="action touches restricted data")
        )
    if action.estimated_cost is not None and action.estimated_cost.cents >= COST_GATE_CENTS:
        reasons.append(
            Reason(
                code="cost_threshold",
                fact=(
                    f"estimated cost {action.estimated_cost.cents} cents "
                    f"exceeds {COST_GATE_CENTS}"
                ),
            )
        )

    if reasons:
        return PolicyVerdict(
            decision="gate",
            policy_id=POLICY_ID,
            policy_version=POLICY_VERSION,
            reasons=reasons,
            choices=list(GATE_CHOICES),
            deadline_seconds=GATE_DEADLINE_SECONDS,
        )

    reasons.append(Reason(code="default_allow", fact="no gate predicate matched"))
    return PolicyVerdict(
        decision="allow",
        policy_id=POLICY_ID,
        policy_version=POLICY_VERSION,
        reasons=reasons,
    )
