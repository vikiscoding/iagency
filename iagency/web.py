"""Single web human channel. Stdlib only. Binds to localhost by default."""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from iagency.brief import render_brief
from iagency.ledger import Ledger
from iagency.loop import BriefRenderer, brief_for, decide, resume, submit
from iagency.types import RATIONALE_CODES, HumanIdentity, ProposedAction


def _page(title: str, body: str) -> bytes:
    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light dark; }}
    body {{ font-family: ui-sans-serif, system-ui, sans-serif; max-width: 44rem;
           margin: 2rem auto; padding: 0 1rem; line-height: 1.45; }}
    h1 {{ font-size: 1.25rem; }}
    pre, textarea {{ width: 100%; box-sizing: border-box; font-family: ui-monospace, monospace;
                     font-size: 0.85rem; }}
    textarea {{ min-height: 12rem; }}
    label {{ display: block; margin: 0.6rem 0 0.2rem; font-weight: 600; }}
    .row {{ margin: 0.4rem 0; }}
    .meta {{ color: #555; font-size: 0.9rem; }}
    .err {{ color: #b00020; }}
    button {{ margin-top: 0.8rem; padding: 0.4rem 0.8rem; }}
    a {{ color: inherit; }}
  </style>
</head>
<body>
{body}
</body>
</html>
"""
    return doc.encode("utf-8")


def make_handler(db_path: Path, renderer: BriefRenderer) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _send(
            self,
            code: int,
            body: bytes,
            content_type: str = "text/html; charset=utf-8",
        ) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _ledger(self) -> Ledger:
            return Ledger(db_path)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self._send(200, b'{"ok":true}', "application/json")
                return
            if path == "/":
                self._index()
                return
            if path.startswith("/gates/"):
                gate_id = path.removeprefix("/gates/").strip("/")
                if gate_id:
                    self._show(gate_id)
                    return
            self._send(404, _page("Not found", "<p>Not found.</p><p><a href='/'>Home</a></p>"))

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            form = self._form()
            if path == "/submit":
                self._submit(form)
                return
            if path.startswith("/gates/") and path.endswith("/decide"):
                gate_id = path.removeprefix("/gates/").removesuffix("/decide").strip("/")
                self._decide(gate_id, form)
                return
            self._send(404, _page("Not found", "<p>Not found.</p>"))

        def _form(self) -> dict[str, list[str]]:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length).decode("utf-8") if length else ""
            return parse_qs(raw, keep_blank_values=True)

        def _index(self) -> None:
            ledger = self._ledger()
            rows = ledger.pending_gates()
            ledger.close()
            items = "<p class='meta'>No pending gates.</p>"
            if rows:
                lis = "".join(
                    f"<li><a href='/gates/{html.escape(g)}'>{html.escape(g)}</a> "
                    f"— {html.escape(a)} — deadline {html.escape(d)}</li>"
                    for g, a, d in rows
                )
                items = f"<ul>{lis}</ul>"
            body = f"""
<h1>IAgency</h1>
<p class="meta">Pending gates. Submit a proposed action as JSON to open a new one.</p>
<h2>Pending</h2>
{items}
<h2>Submit action</h2>
<form method="post" action="/submit">
  <label for="action">ProposedAction JSON</label>
  <textarea id="action" name="action" required></textarea>
  <button type="submit">Submit</button>
</form>
"""
            self._send(200, _page("IAgency", body))

        def _show(self, gate_id: str) -> None:
            ledger = self._ledger()
            try:
                brief = brief_for(ledger, gate_id)
                token = resume(ledger, gate_id)
            except KeyError:
                ledger.close()
                self._send(
                    404,
                    _page("Unknown gate", "<p>Unknown gate.</p><p><a href='/'>Home</a></p>"),
                )
                return
            ledger.close()
            if token.status != "pending":
                body = (
                    f"<h1>Gate {html.escape(gate_id)}</h1>"
                    f"<p>Status: <code>{html.escape(token.status)}</code></p>"
                    f"<pre>{html.escape(token.model_dump_json(indent=2))}</pre>"
                    f"<p><a href='/'>Home</a></p>"
                )
                self._send(200, _page("Gate closed", body))
                return
            choices = "".join(
                f"<div class='row'><label>"
                f"<input type='radio' name='choice' value='{html.escape(c.id)}' required> "
                f"<strong>{html.escape(c.label)}</strong> — {html.escape(c.effect)} "
                f"({html.escape(c.resume)})</label></div>"
                for c in brief.choices
            )
            codes = "".join(
                f"<div class='row'><label>"
                f"<input type='checkbox' name='rationale' value='{html.escape(code)}'> "
                f"{html.escape(code)}</label></div>"
                for code in sorted(RATIONALE_CODES)
            )
            rec = ""
            if brief.recommendation or brief.recommended_choice_id:
                rec = (
                    f"<p><strong>Suggested:</strong> "
                    f"{html.escape(brief.recommended_choice_id or '—')} "
                    f"— {html.escape(brief.recommendation or '')}</p>"
                )
            body = f"""
<p><a href="/">Home</a></p>
<h1>Gate {html.escape(gate_id)}</h1>
<p class="meta">generator={html.escape(brief.generator)}</p>
<pre>{html.escape(brief.render())}</pre>
{rec}
<form method="post" action="/gates/{html.escape(gate_id)}/decide">
  <label>Choice</label>
  {choices}
  <label>Rationale codes (at least one)</label>
  {codes}
  <label for="text">Rationale</label>
  <textarea id="text" name="text" required maxlength="500"></textarea>
  <label for="confidence">Confidence</label>
  <select id="confidence" name="confidence" required>
    <option value="low">low</option>
    <option value="medium" selected>medium</option>
    <option value="high">high</option>
  </select>
  <label for="who">Your id</label>
  <input id="who" name="who" required maxlength="128">
  <button type="submit">Record decision</button>
</form>
"""
            self._send(200, _page(f"Gate {gate_id}", body))

        def _submit(self, form: dict[str, list[str]]) -> None:
            raw = (form.get("action") or [""])[0]
            try:
                action = ProposedAction.model_validate(json.loads(raw))
            except Exception as e:
                self._send(
                    400,
                    _page(
                        "Invalid action",
                        f"<p class='err'>{html.escape(str(e))}</p><p><a href='/'>Home</a></p>",
                    ),
                )
                return
            ledger = self._ledger()
            token = submit(ledger, action, renderer=renderer)
            ledger.close()
            if token.status == "pending" and token.gate_id:
                self.send_response(303)
                self.send_header("Location", f"/gates/{token.gate_id}")
                self.end_headers()
                return
            body = (
                f"<h1>Result</h1><pre>{html.escape(token.model_dump_json(indent=2))}</pre>"
                f"<p><a href='/'>Home</a></p>"
            )
            self._send(200, _page("Result", body))

        def _decide(self, gate_id: str, form: dict[str, list[str]]) -> None:
            choice = (form.get("choice") or [""])[0]
            text = (form.get("text") or [""])[0]
            confidence = (form.get("confidence") or [""])[0]
            who = (form.get("who") or [""])[0].strip()
            codes = [c for c in form.get("rationale") or [] if c]
            if not who:
                self._send(400, _page("Invalid", "<p class='err'>Identity is required.</p>"))
                return
            ledger = self._ledger()
            try:
                token = decide(
                    ledger,
                    gate_id=gate_id,
                    choice_id=choice,
                    rationale_codes=codes,
                    rationale_text=text,
                    confidence=confidence,
                    actor=HumanIdentity(id=who, display_name=who, channel="web"),
                )
            except (ValueError, KeyError, TimeoutError) as e:
                ledger.close()
                self._send(
                    400,
                    _page(
                        "Rejected",
                        f"<p class='err'>{html.escape(str(e))}</p><p><a href='/'>Home</a></p>",
                    ),
                )
                return
            ledger.close()
            body = (
                f"<h1>Recorded</h1><pre>{html.escape(token.model_dump_json(indent=2))}</pre>"
                f"<p><a href='/'>Home</a></p>"
            )
            self._send(200, _page("Recorded", body))

    return Handler


def serve(
    db_path: Path,
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    renderer: BriefRenderer | None = None,
) -> ThreadingHTTPServer:
    handler = make_handler(db_path, renderer or render_brief)
    return ThreadingHTTPServer((host, port), handler)
