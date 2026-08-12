# AGENTS.md

Operating manual for implementers. Most future changes will be made by automated coding agents. This file is the change protocol. It does not replace `FIRST_PRINCIPLES.md`.

| Read first | Then | Then |
|------------|------|------|
| `FIRST_PRINCIPLES.md` | this file | `README.md` for how to run |

Do not invent architecture. Do not cite or role-play named individuals. Constraints below are the authority.

---

## 1. Mission

Keep the human-gate spine correct, small, and reconstructible without a model.

Critical path:

`ProposedAction` → `evaluate` → `render_brief` (gate only) → `decide` → `ResumeToken`

---

## 2. Non-negotiable

- Layer A (`iagency/policy.py`) and Layer C (`iagency/ledger.py`, decision capture in `iagency/loop.py`) are deterministic. No LLM imports. No network.
- The caller does not define the choice set. Policy does.
- A decision that names a choice id not on the opened gate is invalid and must not be written.
- Silence after the deadline is `timeout` → resume `halt`. Never implicit approve.
- The ledger is append-only. No updates. No deletes.
- `pytest` plus `iagency verify` must reconstruct every verdict with LLM SDKs absent.
- Do not add production modules beyond `types`, `policy`, `brief`, `ledger`, `loop`, `cli` in Phase 0.
- Do not add Slack, Teams, Postgres, SSO, dashboards, or an LLM brief generator unless a later phase is explicitly requested **and** Phase 0 invariants still hold.

---

## 3. Module ownership

| Module | Layer | May call | Must not |
|--------|-------|----------|----------|
| `types.py` | shared | nothing in this package | grow unused types |
| `policy.py` | A | `types` | I/O, clock, brief, ledger, models |
| `brief.py` | B | `types` | invent choices; call policy or ledger |
| `ledger.py` | C | `types` | interpret decisions; call policy or brief |
| `loop.py` | orchestration | policy, brief, ledger, types | skip validation; write model text into the ledger |
| `cli.py` | adapter | loop, ledger, types | contain policy rules |

A new type is allowed only if it changes what a human decides or what the ledger can prove. Changing a field on an existing type is a schema event: update `SCHEMA_VERSION` (if the brief schema changes), fixtures, and tests in the same change.

---

## 4. Where a model may appear later

Only `brief.py`, behind the existing `Brief` schema, with the current template as fallback. One call. It must not edit `choices` or reason codes. It must not be imported by `policy.py` or `ledger.py`.

Do not add model SDKs in Phase 0. `tests/test_no_llm.py` must stay green.

---

## 5. How to change the system

1. State the single output of the change (one sentence).
2. Classify it: critical path, adapter, or test/docs.
3. If it violates an invariant in `FIRST_PRINCIPLES.md` section 3, stop.
4. Implement the smallest diff that preserves the public types.
5. Add or update tests that would fail if the invariant regressed.
6. Run:

```
pytest
ruff check iagency tests
```

7. For ledger or hash changes, also run `iagency verify` against a throwaway database after a submit/decide cycle.

Do not add a rules engine, extra agent loop, or second human channel in Phase 0.

---

## 6. Tests that must remain meaningful

| File | Proves |
|------|--------|
| `tests/test_policy.py` | Predicates are pure and deterministic |
| `tests/test_brief.py` | Choices are copied; length budget holds |
| `tests/test_ledger.py` | Chain verifies; tampering is detected |
| `tests/test_loop.py` | Allow / block / decide / reject / timeout / illegal choice |
| `tests/test_no_llm.py` | Spine imports no model SDK |

Identity strings in tests and examples must be role names (`reviewer`, `treasury-agent`), not personal names.

---

## 7. Documentation rules

- Update `FIRST_PRINCIPLES.md` when an invariant, type, or phase boundary changes.
- Update `README.md` when commands, setup, or examples change.
- Update this file when module ownership or the change protocol changes.
- Write standing system documentation. Do not leave review commentary, conversational framing, or references to named individuals.
- Prefer tables, typed field lists, and commands over narrative.

---

## 8. Commands

```
pytest
ruff check iagency tests
iagency submit examples/prod_transfer.json
iagency verify --db <path>
```
