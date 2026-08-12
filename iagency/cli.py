"""CLI human channel. Web serve is the Phase 1 adapter."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from iagency.ledger import Ledger
from iagency.loop import brief_for, decide, resume, submit
from iagency.render import resolve_renderer
from iagency.types import RATIONALE_CODES, HumanIdentity, ProposedAction

DEFAULT_DB = Path(os.environ.get("IAGENCY_LEDGER", "data/ledger.sqlite"))


def _ledger(path: Path) -> Ledger:
    return Ledger(path)


def cmd_submit(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.action).read_text(encoding="utf-8"))
    action = ProposedAction.model_validate(payload)
    ledger = _ledger(args.db)
    token = submit(ledger, action, renderer=resolve_renderer(args.brief))
    if token.status == "pending" and token.gate_id:
        brief = brief_for(ledger, token.gate_id)
        print(brief.render())
        print()
    print(token.model_dump_json(indent=2))
    ledger.close()
    return 0


def cmd_pending(args: argparse.Namespace) -> int:
    ledger = _ledger(args.db)
    rows = ledger.pending_gates()
    if not rows:
        print("no pending gates")
        ledger.close()
        return 0
    for gate_id, action_id, deadline_at in rows:
        print(f"{gate_id}  action={action_id}  deadline={deadline_at}")
    ledger.close()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    ledger = _ledger(args.db)
    print(brief_for(ledger, args.gate_id).render())
    ledger.close()
    return 0


def cmd_decide(args: argparse.Namespace) -> int:
    ledger = _ledger(args.db)
    codes = [c.strip() for c in args.rationale.split(",") if c.strip()]
    unknown = [c for c in codes if c not in RATIONALE_CODES]
    if unknown:
        print(f"unknown rationale codes: {unknown}", file=sys.stderr)
        print(f"allowed: {sorted(RATIONALE_CODES)}", file=sys.stderr)
        return 2
    actor = HumanIdentity(id=args.who, display_name=args.who, channel="cli")
    token = decide(
        ledger,
        gate_id=args.gate_id,
        choice_id=args.choice,
        rationale_codes=codes,
        rationale_text=args.text,
        confidence=args.confidence,
        actor=actor,
    )
    print(token.model_dump_json(indent=2))
    ledger.close()
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    ledger = _ledger(args.db)
    print(resume(ledger, args.gate_id).model_dump_json(indent=2))
    ledger.close()
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    ledger = _ledger(args.db)
    ledger.verify()
    n = ledger.last_seq()
    print(f"ok  records={n}  tip={ledger.last_hash()}")
    ledger.close()
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from iagency.web import serve

    server = serve(
        args.db,
        host=args.host,
        port=args.port,
        renderer=resolve_renderer(args.brief),
    )
    print(f"iagency web on http://{args.host}:{args.port}  db={args.db}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("stopping", file=sys.stderr)
    finally:
        server.server_close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="iagency", description="Human-gate spine")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_db(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--db", type=Path, default=DEFAULT_DB, help="sqlite ledger path")

    def add_brief(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--brief",
            default=None,
            choices=("auto", "template", "llm"),
            help="brief renderer (default: IAGENCY_BRIEF or auto)",
        )

    s = sub.add_parser("submit", help="submit a proposed action JSON file")
    add_db(s)
    add_brief(s)
    s.add_argument("action", type=Path)
    s.set_defaults(func=cmd_submit)

    s = sub.add_parser("pending", help="list open gates")
    add_db(s)
    s.set_defaults(func=cmd_pending)

    s = sub.add_parser("show", help="print the brief for a gate")
    add_db(s)
    s.add_argument("gate_id")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("decide", help="record a human decision")
    add_db(s)
    s.add_argument("gate_id")
    s.add_argument("--choice", required=True)
    s.add_argument("--rationale", required=True, help="comma-separated rationale codes")
    s.add_argument("--text", required=True, help="free-text rationale, <=500 chars")
    s.add_argument("--confidence", required=True, choices=("low", "medium", "high"))
    s.add_argument("--who", required=True, help="human identity string")
    s.set_defaults(func=cmd_decide)

    s = sub.add_parser("resume", help="read the resume token for a gate")
    add_db(s)
    s.add_argument("gate_id")
    s.set_defaults(func=cmd_resume)

    s = sub.add_parser("verify", help="recompute the hash chain")
    add_db(s)
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("serve", help="single web human channel")
    add_db(s)
    add_brief(s)
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, KeyError, TimeoutError) as e:
        print(str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
