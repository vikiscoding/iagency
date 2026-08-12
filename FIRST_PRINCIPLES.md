# IAgency — System Architecture

| Field | Value |
|-------|--------|
| Status | Locked for Phase 0 |
| Date | 2026-08-12 |
| Audience | Implementers (primarily automated agents) and reviewers |
| Related | `README.md` (operations), `AGENTS.md` (change protocol) |

This document is the architecture source of truth. Implementation must follow it. Conversational drafts, personal notes, and named-individual opinions are not authority.

---

## 1. Purpose

IAgency records a human verdict on a proposed automated action and returns a resume token the caller can act on.

When a system reaches a point where the cost of a wrong autonomous action is high, the product must:

1. Insert a human.
2. Give that human the minimum context required to exercise judgment.
3. Record the judgment in a form that can be reconstructed later without trusting a model.
4. Resume the caller with an explicit `proceed` or `halt`.

That loop is the product. Transports (Slack, Teams, web UI), stores (Postgres), and identity providers (SSO) are adapters. They attach to this spine. They do not replace it.

---

## 2. Architecture

Three layers with hard boundaries.

| Layer | Name | Determinism | LLM allowed |
|-------|------|-------------|-------------|
| A | Gate trigger and policy | Required | No |
| B | Predicament brief | Phase 0: required. Phase 1: one constrained call | Phase 1 only, same `Brief` schema |
| C | Decision capture and ledger | Required | No |

```
ProposedAction
    │
    ▼
Layer A  policy.evaluate()          # pure, versioned, no LLM
    │
    ├─ allow  ──► ledger.append(auto_allow)  ──► ResumeToken(proceed)
    ├─ block  ──► ledger.append(auto_block)  ──► ResumeToken(halt)
    └─ gate   ──► ledger.append(gate_opened)
                      │
                      ▼
                 Layer B  render_brief()     # Phase 0: template
                      │                      # Phase 1: one LLM call, same schema
                      ▼
                 human is shown the brief
                      │
                      ▼
                 Layer C  capture Decision   # structured, no LLM
                      │
                      ├─ on time  ──► ledger.append(decision) ──► ResumeToken(choice.resume)
                      └─ silence  ──► ledger.append(timeout)  ──► ResumeToken(halt)
```

If this path fails when every model is removed, the product does not exist.

---

## 3. Invariants

These are not preferences. A change that violates one is rejected.

1. **The caller is untrusted.** An agent, workflow, or human may propose an action. Proposal is not authorization.
2. **Policy owns the choice set.** After a gate opens, no component may add, remove, or rewrite choices. A decision that names an unknown choice id is invalid and is not written.
3. **The brief is disposable.** If the brief is lost, a human can still decide from the gate record (action + reasons + choices). The brief is compression, not source of truth.
4. **The ledger is authoritative.** Walking the chain from genesis reconstructs every verdict without a model, a chat API, or a UI.
5. **The ledger records every verdict**, not only human decisions: `auto_allow`, `auto_block`, `gate_opened`, `decision`, `timeout`.
6. **Every gate has a deadline.** Silence is recorded as `timeout` and resumes `halt`. Implicit approve is forbidden.
7. **Resume is a contract.** Callers consume `ResumeToken.status` only. Free text is not a control signal.
8. **Hash chain and signature are separate.** The hash chain proves tamper-evidence of the log. Signatures prove who wrote a record. Phase 0 implements the chain plus an identity string. Cryptographic signatures and SSO are Phase 2.
9. **Gate latency is dominated by human thinking time**, not system time.
10. **A brief that exceeds 1,500 rendered characters has failed** the communication requirement.

---

## 4. Object model

These are the only types on the critical path. A new type is allowed only if it changes what a human decides or what the ledger can prove. Field changes are schema events; update `SCHEMA_VERSION` and tests in the same change.

### ProposedAction

What the untrusted caller wants to do.

| Field | Constraint |
|-------|------------|
| `action_id` | Caller-supplied, unique per attempt |
| `actor` | `id`, `kind` (`agent \| workflow \| human \| system`), `name` |
| `verb` | Normalized act (`transfer`, `delete`, `deploy`, …) |
| `object_ref` | Target of the act |
| `params` | Structured, ≤ 8 KiB canonical JSON |
| `environment` | `dev \| staging \| prod` |
| `irreversibility` | `reversible \| costly \| irreversible` |
| `estimated_cost` | Integer cents + ISO currency, or none |
| `data_class` | `public \| internal \| sensitive \| restricted` |
| `raw_context` | Evidence only, ≤ 16 KiB. Not a choice. Not a policy override |
| `submitted_at` | UTC, timezone-aware |

### Choice

One legal move the human may make.

- `id`, `label`, `effect`
- `resume` — `proceed | halt`

Policy emits this list. The brief copies it. The decision must reference one of these ids.

### PolicyVerdict (Layer A output)

- `decision` — `allow | block | gate`
- `policy_id`, `policy_version`
- `reasons` — `{code, fact}` pairs. Never model-generated prose.
- `choices` — empty unless `decision == gate`
- `deadline_seconds`
- `default_on_timeout` — `halt` in Phase 0

### Brief (Layer B output)

| Field | Constraint |
|-------|------------|
| `gate_id` | Matches the opened gate |
| `title` | ≤ 80 characters |
| `proposed` | ≤ 280 characters |
| `why_human` | Verdict reasons, restated at most |
| `choices` | Copied from the verdict. Never invented |
| `tradeoffs` | Optional, ≤ 3 lines |
| `recommendation` | `None` in Phase 0 |
| `deeper_refs` | Pointers, not a dump of `raw_context` |
| `generator` | `template \| llm` |
| `schema_version` | Current brief schema |

Rendered length must stay under 1,500 characters. If a fixture exceeds this, the renderer failed.

### Decision (canonical human record)

- `decision_id`, `gate_id`
- `choice_id` — must be in the opened gate’s choices
- `rationale_codes` — closed set
- `rationale_text` — ≤ 500 characters
- `confidence` — `low | medium | high`
- `overrides_recommendation` — `false` in Phase 0
- `actor` — human identity (Phase 0: id, display name, channel `cli`)
- `decided_at`
- `brief_hash`, `request_hash` — what was shown, what was asked

### LedgerRecord

- `seq`, `prev_hash`, `hash`
- `record_type` — `auto_allow | auto_block | gate_opened | decision | timeout`
- `body` — typed payload
- `recorded_at`

```
hash = SHA-256( prev_hash || "\n" || canonical_json(seq, prev_hash, record_type, recorded_at, body) )
```

Genesis `prev_hash` is 64 zero hex characters. Canonical JSON is UTF-8, sorted keys, no insignificant whitespace, datetimes as ISO-8601 UTC.

### ResumeToken

| Field | Notes |
|-------|--------|
| `action_id` | Always set |
| `gate_id` | Null for auto-allow / auto-block |
| `status` | `proceed \| halt \| pending \| expired` |
| `choice_id`, `decision_id` | Set after a human decision |
| `ledger_hash` | Tip of the chain after this event |
| `policy_version` | Policy that produced the verdict |

---

## 5. Layer rules

### Layer A — Policy

Pure function: `evaluate(action) -> PolicyVerdict`.

- No I/O.
- No wall clock. Deadline is a duration on the verdict, not a timestamp computed inside policy.
- No LLM.
- Versioned by a string stored on every record.

Phase 0 predicates (fixed, testable):

1. Verb in the always-block set (`exfiltrate`, `disable_audit`) → **block**
2. `environment == prod` → **gate**
3. `irreversibility == irreversible` → **gate**
4. `data_class == restricted` → **gate**
5. `estimated_cost.cents >= 100_000` → **gate**
6. Else → **allow**

Gated choice set is always:

- `approve` → resume `proceed`
- `reject` → resume `halt`

Do not introduce a rule DSL or external rules file in Phase 0. Five predicates are the policy.

### Layer B — Brief

**Phase 0:** Deterministic template. Same action + verdict → same brief except `gate_id`.

**Phase 1:** One schema-constrained model call. Low temperature. Output parsed into the same `Brief` type. On parse failure, fall back to the template and set `generator=template`. The human still decides. A failed model call must not halt the gate.

The model may fill `proposed`, `tradeoffs`, and `recommendation`. It must not add, remove, or rewrite `choices`. It must not change `why_human` reason codes.

### Layer C — Ledger and capture

Present the brief. Capture a `Decision`. Validate. Append. Never update. Never delete.

Identity, authorization, routing, hashing, and serialization are code. Model output must not be written as the decision record or as a substitute for the hash chain.

---

## 6. AI usage policy

Future implementation is expected to be mostly automated. That does not move the model onto the critical path.

**Allowed later (not in Phase 0):**

- Compress `raw_context` into `proposed` and `tradeoffs`.
- Produce a recommendation the human can override.
- Offline: cluster past `rationale_codes` to propose better codes.
- Offline: propose *candidate* policy predicates. A human versions accepted predicates into Layer A.

**Forbidden on the critical path:**

- Deciding whether a gate is required when a predicate already matches.
- Defining or mutating the choice set.
- Writing the decision record.
- Authentication, authorization, or routing.
- Hashing, signing, or verifying the log.
- Setting `ResumeToken.status`.

If a step’s nondeterminism would prevent answering “what happened?” from the ledger alone, that step does not belong there.

---

## 7. Phase 0 scope

Phase 0 proves that a human (or a test acting as one) can:

1. Submit a proposed action.
2. Receive allow, block, or a pending gate with a short brief.
3. Decide with a structured form.
4. Leave an immutable, hash-chained record.
5. Receive a resume token.
6. Verify the entire chain with no network and no model.

**Out of scope**

- Slack, Teams, web UI
- Postgres, object storage, queues
- SSO, signatures, multi-party approval, escalation
- LLM brief generator
- Outcome linking, learning loops, external ITSM or agent-framework adapters
- Dashboards

**Complexity budget**

| Metric | Budget |
|--------|--------|
| Production modules | `types`, `policy`, `brief`, `ledger`, `loop`, `cli` |
| LLM SDKs imported | 0 |
| Network required to run tests | 0 |
| Human-channel implementations | 1 (`cli`) |

The critical path must remain small enough that an implementer can hold it in context without additional abstraction layers.

---

## 8. Later phases

Start a later phase only when Phase 0 has been used on a real proposed action and the measured bottleneck is the brief or an adapter, not the ledger.

**Phase 1 — one compression step**  
Same `Brief` schema, filled by one constrained model call, template fallback. One additional human channel (Slack *or* a single web page, not both). Policy remains the Phase 0 predicates unless fixtures justify a versioned predicate change.

**Phase 2 — production attachments**  
SSO identity mapped onto `Decision.actor`. Ed25519 signatures on records. Multi-party / escalation / custom deadlines. HTTP API and webhook resume. Postgres adapter behind the same ledger interface. Replay and query that only read the chain.

**Phase 3 — leverage**  
Outcome linking after `proceed`. Offline learning from decisions into better briefs and candidate rules. Self-hosted / air-gapped deployment. Additional adapters.

---

## 9. Change acceptance

A change is accepted only if it does at least one of the following, without a larger penalty in the others:

- Shortens the critical path.
- Shrinks a failure domain.
- Raises the fraction of the system that is deterministically verifiable.
- Raises the rate of correct human judgment.

Every change must answer:

1. What is the single most important output of this change?
2. Does it sit on the critical path, or is it a renderer, store, or adapter?
3. Is this step deterministic? If not, why is uncertainty irreducible here?
4. If every LLM is removed, does the spine still run?
5. Can a competent human decide from the brief in 30–60 seconds?

---

## 10. Verification

```
pytest
iagency verify
```

The spine remains a product if those two commands reconstruct every decision after any future `llm` module is deleted.
