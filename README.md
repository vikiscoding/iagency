# IAgency

Deterministic human-gate spine.

When an agent or workflow proposes an action whose cost of being wrong is high, IAgency evaluates a pure policy, presents a short predicament brief, captures a structured human decision, appends an immutable hash-chained record, and returns a resume token.

Architecture and invariants: [`FIRST_PRINCIPLES.md`](FIRST_PRINCIPLES.md).  
Change protocol for implementers: [`AGENTS.md`](AGENTS.md).

Phase 0 (no model, CLI only) is frozen on branch `prod`.  
Phase 1 (optional brief compressor + one web channel) is on branch `dev`.

## Copies and branches

| Copy | Location | Branch | Role |
|------|----------|--------|------|
| Development | this directory | `dev` | Phase 1 work |
| Production freeze | sibling `IAgency-prod` worktree | `prod` | Phase 0, do not add Phase 1 here |
| Remote | https://github.com/vikiscoding/iagency | `main`, `dev`, `prod` | `main` matches the Phase 0 initial commit |

Promote to `prod` only after review. Do not merge compressor or web changes onto `prod` by accident.

## Critical path

```
ProposedAction → policy.evaluate → allow | block | gate
                                      │
                      gate → brief (template, or one model fill) → human decision
                                      │
                         hash-chained ledger → ResumeToken(proceed|halt)
```

The template always works. The compressor is optional. If `XAI_API_KEY` is unset or the call fails, the human still sees a valid brief.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Human loop (CLI)

```powershell
iagency submit examples\prod_transfer.json --brief template
iagency pending
iagency decide <gate_id> --choice approve --rationale risk_accepted --text "Vendor is allow-listed." --confidence high --who reviewer
iagency resume <gate_id>
iagency verify
```

## Human loop (web)

```powershell
iagency serve --brief template --host 127.0.0.1 --port 8080
```

Open `http://127.0.0.1:8080`. Submit a `ProposedAction` JSON document, then record a decision on the gate page.

## Optional compressor

| Variable | Meaning |
|----------|---------|
| `XAI_API_KEY` | SpaceXAI / xAI key. If unset, briefs stay on the template |
| `IAGENCY_BRIEF` | `auto` (default), `template`, or `llm` |
| `IAGENCY_MODEL` | Default `grok-4.6` |
| `IAGENCY_BRIEF_TIMEOUT` | Seconds, default `8` |
| `IAGENCY_LEDGER` | SQLite path, default `data/ledger.sqlite` |

Keep keys in a git-ignored `.env` or the process environment. Never commit them.

| Example | Policy result |
|---------|----------------|
| `examples/dev_log_write.json` | auto-allow (`proceed`) |
| `examples/prod_transfer.json` | gate (human required) |
| `examples/exfiltrate.json` | auto-block (`halt`) |

## Out of scope

Slack, Teams, Postgres, SSO, dashboards, and additional model calls. Those are later adapters.
