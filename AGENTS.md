# AGENTS.md

Operating manual for implementers. Most future changes will be made by automated coding agents. This file is the change protocol. It does not replace `FIRST_PRINCIPLES.md`.

| Read first | Then | Then |
|------------|------|------|
| `FIRST_PRINCIPLES.md` | this file | `README.md` for how to run |

Do not invent architecture. Do not cite or role-play named individuals. Constraints below are the authority.

Work on branch `dev`. Do not commit Phase 1 changes to `prod`. `prod` is the Phase 0 freeze.

---

## 1. Mission

Keep the human-gate spine correct, small, and reconstructible without a model.

Critical path:

`ProposedAction` → `evaluate` → brief renderer (gate only) → `decide` → `ResumeToken`

---

## 2. Non-negotiable

- Layer A (`iagency/policy.py`) and Layer C (`iagency/ledger.py`, decision capture in `iagency/loop.py`) are deterministic. No LLM imports. No network.
- `loop.py` must not import `brief_llm`.
- The caller does not define the choice set. Policy does. The compressor may not add or rewrite choices.
- A decision that names a choice id not on the opened gate is invalid and must not be written.
- Silence after the deadline is `timeout` → resume `halt`. Never implicit approve.
- The ledger is append-only. No updates. No deletes.
- `pytest` plus `iagency verify` must reconstruct every verdict with LLM SDKs absent.
- Do not add Slack, Teams, Postgres, SSO, or a second model call unless a later phase is explicitly requested **and** Phase 0 invariants still hold.

---

## 3. Module ownership

| Module | Layer | May call | Must not |
|--------|-------|----------|----------|
| `types.py` | shared | nothing in this package | grow unused types |
| `policy.py` | A | `types` | I/O, clock, brief, ledger, models |
| `brief.py` | B template | `types` | invent choices; call policy, ledger, or the network |
| `brief_llm.py` | B compressor | `brief`, `types`, stdlib HTTP | be imported by policy, ledger, or loop |
| `render.py` | wiring | `brief`; lazy-import `brief_llm` | contain policy rules |
| `ledger.py` | C | `types` | interpret decisions; call policy or brief |
| `loop.py` | orchestration | policy, brief, ledger, types | import `brief_llm`; skip validation |
| `cli.py` | adapter | loop, ledger, render, types | contain policy rules |
| `web.py` | adapter | loop, ledger, types | contain policy rules; import an LLM SDK |

A new type is allowed only if it changes what a human decides or what the ledger can prove. Changing a field on an existing type is a schema event: update `SCHEMA_VERSION`, fixtures, and tests in the same change.

---

## 4. Model usage

One call, in `brief_llm.py` only. SpaceXAI via `https://api.x.ai/v1/chat/completions`. Env: `XAI_API_KEY`. Optional: `IAGENCY_MODEL` (default `grok-4.6`), `IAGENCY_BRIEF_TIMEOUT` (default 8s), `IAGENCY_BRIEF` (`auto|template|llm`).

The compressor fills `proposed`, `tradeoffs`, `recommendation`, `recommended_choice_id`. It must not edit `choices` or reason codes. Any failure returns the template.

`tests/test_no_llm.py` must stay green. Do not add the `openai` or `xai-sdk` packages to default dependencies.

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

Do not add a rules engine or a second human channel beyond `cli` and `web`.

---

## 6. Tests that must remain meaningful

| File | Proves |
|------|--------|
| `tests/test_policy.py` | Predicates are pure and deterministic |
| `tests/test_brief.py` | Choices are copied; length budget holds |
| `tests/test_brief_llm.py` | Illegal recommended ids are dropped; missing key falls back |
| `tests/test_ledger.py` | Chain verifies; tampering is detected |
| `tests/test_loop.py` | Allow / block / decide / reject / timeout / illegal choice / override |
| `tests/test_web.py` | Web channel can submit and decide |
| `tests/test_no_llm.py` | Spine imports no model SDK and does not import `brief_llm` |

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
iagency submit examples/prod_transfer.json --brief template
iagency serve --brief template --port 8080
iagency verify --db <path>
```
