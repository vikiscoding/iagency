"""Resolve the Layer B renderer. Lazy-imports the compressor."""

from __future__ import annotations

import os
from collections.abc import Callable

from iagency.brief import render_brief
from iagency.types import Brief, PolicyVerdict, ProposedAction

BriefRenderer = Callable[[str, ProposedAction, PolicyVerdict], Brief]


def resolve_renderer(mode: str | None = None) -> BriefRenderer:
    chosen = (mode or os.environ.get("IAGENCY_BRIEF") or "auto").strip().lower()
    if chosen == "template":
        return render_brief
    if chosen == "llm":
        from iagency.brief_llm import render_brief_llm

        return render_brief_llm
    if chosen == "auto":
        if os.environ.get("XAI_API_KEY", "").strip():
            from iagency.brief_llm import render_brief_llm

            return render_brief_llm
        return render_brief
    raise ValueError("brief mode must be auto, template, or llm")
