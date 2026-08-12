"""Physics check: the spine does not load a model stack."""

from __future__ import annotations

import sys

BANNED = {
    "openai",
    "anthropic",
    "litellm",
    "groq",
    "langchain",
    "langgraph",
    "llama_index",
    "instructor",
}


def test_importing_spine_loads_no_llm_sdk() -> None:
    before = set(sys.modules)
    import iagency.brief  # noqa: F401
    import iagency.cli  # noqa: F401
    import iagency.ledger  # noqa: F401
    import iagency.loop  # noqa: F401
    import iagency.policy  # noqa: F401

    loaded = set(sys.modules) - before
    hits = {name for name in loaded if name.split(".")[0] in BANNED}
    assert not hits, f"LLM SDK leaked onto the spine: {hits}"
