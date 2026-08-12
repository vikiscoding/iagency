from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from iagency.brief import render_brief
from iagency.types import Actor, ProposedAction
from iagency.web import serve


def _action(environment: str = "prod") -> dict:
    return ProposedAction(
        action_id="web-1",
        actor=Actor(id="treasury", kind="agent", name="treasury-agent"),
        verb="deploy",
        object_ref="api",
        environment=environment,
        irreversibility="costly",
        data_class="internal",
        submitted_at=datetime(2026, 8, 12, tzinfo=UTC),
    ).model_dump(mode="json")


def test_web_submit_decide_verify(tmp_path) -> None:
    db = tmp_path / "l.sqlite"
    server = serve(db, host="127.0.0.1", port=0, renderer=render_brief)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    base = f"http://127.0.0.1:{port}"
    try:
        health = json.loads(urlopen(f"{base}/health", timeout=3).read())
        assert health["ok"] is True

        req = Request(
            f"{base}/submit",
            data=urlencode({"action": json.dumps(_action())}).encode(),
            method="POST",
        )
        with urlopen(req, timeout=3) as resp:
            assert resp.status == 200
            page = resp.read().decode()
        assert "GATE" in page
        assert "generator=template" in page
        match = re.search(r"GATE ([0-9a-f]+)", page)
        assert match is not None
        gate_id = match.group(1)

        home = urlopen(f"{base}/", timeout=3).read().decode()
        assert "web-1" in home
        decide_req = Request(
            f"{base}/gates/{gate_id}/decide",
            data=urlencode(
                {
                    "choice": "approve",
                    "rationale": "risk_accepted",
                    "text": "Change window is open.",
                    "confidence": "high",
                    "who": "reviewer",
                }
            ).encode(),
            method="POST",
        )
        with urlopen(decide_req, timeout=3) as resp:
            body = resp.read().decode()
        assert "proceed" in body
        assert "reviewer" not in body or "Recorded" in body
    finally:
        server.shutdown()
        server.server_close()
