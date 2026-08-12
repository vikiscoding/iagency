# IAgency

Deterministic human-gate spine.

When an agent or workflow proposes an action whose cost of being wrong is high, IAgency evaluates a pure policy, presents a short predicament brief, captures a structured human decision, appends an immutable hash-chained record, and returns a resume token.

Architecture and invariants: [`FIRST_PRINCIPLES.md`](FIRST_PRINCIPLES.md).  
Change protocol for implementers: [`AGENTS.md`](AGENTS.md).

Phase 0 includes no LLM. Tests and `iagency verify` require no network.

## Critical path

```
ProposedAction → policy.evaluate → allow | block | gate
                                      │
                      gate → template brief → human decision
                                      │
                         hash-chained ledger → ResumeToken(proceed|halt)
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Human loop

```powershell
iagency submit examples\prod_transfer.json
iagency pending
iagency decide <gate_id> --choice approve --rationale risk_accepted --text "Vendor is allow-listed." --confidence high --who reviewer
iagency resume <gate_id>
iagency verify
```

| Example | Policy result |
|---------|----------------|
| `examples/dev_log_write.json` | auto-allow (`proceed`) |
| `examples/prod_transfer.json` | gate (human required) |
| `examples/exfiltrate.json` | auto-block (`halt`) |

Default ledger path is `data/ledger.sqlite`. Override with `--db` or `IAGENCY_LEDGER`.

## Out of scope (Phase 0)

Slack, Teams, Postgres, SSO, dashboards, and the brief LLM. Those are later adapters. They are not required for the spine to function.
