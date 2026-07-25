"""Integration tests around the EXISTING, unmodified debate engine
(chains/debater_chain.py), added for Increment 9 (dynamic opposing debate
personas).

These tests exercise the real `get_debater_chain(...)` pipeline
(`process_inputs -> select_prompt -> llm -> StrOutputParser`) end to end,
only replacing the network-calling leaf (`OpenRouterChat._agenerate`) with
a stub that records the messages it was asked to send. This proves two
things without a real OpenRouter call:

1. A generated dynamic persona's `persona_prompt` (built by
   `services.dynamic_persona_generation.build_persona_prompt`) is extracted
   and rendered into the final prompt exactly the way `debater_chain.py`
   already does for fixed celebrity personas -- no changes to
   `chains/debater_chain.py` were needed or made.
2. Existing debate formats/personas (Public Forum, Lincoln-Douglas, the
   "SPEAKING STYLE:" fixed-persona path, and the no-persona default path)
   still function -- the regression coverage requested by the spec.
"""

import pytest
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from chains.debater_chain import OpenRouterChat, get_debater_chain
from services.dynamic_persona_generation import build_persona_prompt, ground_persona_draft

MOCKED_RESPONSE = "# Con – Round 1/5\n### 1. Mocked Argument\nThis is a mocked debate response."


class _CapturingAgenerate:
    """A stand-in for `OpenRouterChat._agenerate` that records every call's
    messages and returns a fixed response, so the real chain pipeline runs
    without a network call.

    Assigned directly as a class attribute (`OpenRouterChat._agenerate =
    stub`), not a plain function, so it is *not* bound as an instance
    method when accessed via `self._agenerate(...)` -- Python's descriptor
    protocol only auto-binds `self` for plain functions. `self._agenerate`
    therefore resolves to this object itself, and `self._agenerate(messages,
    stop=stop, **kwargs)` calls `__call__(messages, stop=stop, **kwargs)`
    with no separate `chat_self` argument.
    """

    def __init__(self):
        self.calls = []

    async def __call__(self, messages, stop=None, **kwargs):
        self.calls.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=MOCKED_RESPONSE))])


@pytest.fixture
def capturing_llm(monkeypatch):
    stub = _CapturingAgenerate()
    monkeypatch.setattr(OpenRouterChat, "_agenerate", stub)
    return stub


def _rendered_text(messages) -> str:
    return "\n".join(getattr(m, "content", str(m)) for m in messages)


def _sample_persona_prompt():
    raw = (
        '{"role": "School district budget director", '
        '"location_context": "overseeing a rural county school district\'s health-services budget", '
        '"interests": ["Predictable funding", "Minimizing new administrative burden"], '
        '"likely_concerns": ["New compliance reporting could strain limited staff time"], '
        '"position": "Cautiously supportive of the funding but concerned about implementation costs", '
        '"section_ids": ["section-8"], '
        '"reason_for_selection": "A budget director weighs implementation cost against funding benefit."}'
    )
    draft = ground_persona_draft(raw, known_section_ids={"section-8"})
    return build_persona_prompt(draft)


# ---------------------------------------------------------------------------
# Dynamic persona wiring: the actual Increment 9 integration point
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dynamic_persona_reaches_final_rendered_prompt(capturing_llm):
    persona_prompt = _sample_persona_prompt()
    chain = get_debater_chain(model_name="openai/gpt-4o-mini", round_num=1, debate_type="topic")

    output = await chain.arun(
        debater_role="Con",
        topic="Test Community Health Access Act",
        bill_description="",
        history="",
        full_transcript="",
        round_num=1,
        persona_prompt=persona_prompt,
        persona="Dynamic Persona",
        prompt=persona_prompt,
        language="en",
    )

    assert output == MOCKED_RESPONSE
    assert len(capturing_llm.calls) == 1
    rendered = _rendered_text(capturing_llm.calls[0])
    assert "School district budget director" in rendered
    assert "Cautiously supportive of the funding" in rendered
    assert "Minimizing new administrative burden" in rendered


@pytest.mark.asyncio
async def test_dynamic_persona_not_truncated_in_final_prompt(capturing_llm):
    """The persona body must survive intact through debater_chain.py's own
    (unmodified) end-marker truncation logic."""
    persona_prompt = _sample_persona_prompt()
    chain = get_debater_chain(model_name="openai/gpt-4o-mini", round_num=1, debate_type="topic")

    await chain.arun(
        debater_role="Con", topic="Test Bill", bill_description="", history="",
        full_transcript="", round_num=1, persona_prompt=persona_prompt,
        persona="Dynamic Persona", prompt=persona_prompt, language="en",
    )

    rendered = _rendered_text(capturing_llm.calls[0])
    # The trailing sentence of the generated persona body must be present --
    # if truncation had fired early, this would be missing.
    assert "Do not assume anything about the other debater" in rendered


@pytest.mark.asyncio
async def test_persona_skipped_path_still_runs(capturing_llm):
    """"Persona skipped" scenario: an empty persona_prompt must not break
    the chain -- the debate simply proceeds with no persona instructions."""
    chain = get_debater_chain(model_name="openai/gpt-4o-mini", round_num=1, debate_type="topic")

    output = await chain.arun(
        debater_role="Pro", topic="Test Bill", bill_description="", history="",
        full_transcript="", round_num=1, persona_prompt="", persona="Default AI",
        prompt="", language="en",
    )

    assert output == MOCKED_RESPONSE
    assert len(capturing_llm.calls) == 1


# ---------------------------------------------------------------------------
# Regression: existing fixed persona / format logic still works
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_regression_fixed_speaking_style_persona_still_extracted(capturing_llm):
    """Mirrors frontend/src/components/Debate.jsx's fixed-persona format
    (Increment 9 must not modify fixed celebrity personas)."""
    trump_style_prompt = (
        "SPEAKING STYLE: Bold, confident, repetitive rhetoric with superlatives and simple language.\n\n"
        "REQUIRED LANGUAGE PATTERNS:\n- Start with: \"Look,\" \"Listen,\"\n"
        "Adopt this rhetorical style completely for your debate response."
    )
    chain = get_debater_chain(model_name="openai/gpt-4o-mini", round_num=1, debate_type="topic")

    await chain.arun(
        debater_role="Pro", topic="Test Bill", bill_description="", history="",
        full_transcript="", round_num=1, persona_prompt=trump_style_prompt,
        persona="Donald Trump", prompt=trump_style_prompt, language="en",
    )

    rendered = _rendered_text(capturing_llm.calls[0])
    assert "Bold, confident, repetitive rhetoric" in rendered


@pytest.mark.asyncio
async def test_regression_public_forum_format_still_works(capturing_llm):
    chain = get_debater_chain(
        model_name="openai/gpt-4o-mini", round_num=1, debate_type="bill", debate_format="public-forum",
        speaking_order="pro-first",
    )

    output = await chain.arun(
        debater_role="Pro", topic="Test Bill", bill_description="Section 1: test bill text.",
        history="", full_transcript="", round_num=1, persona_prompt="", persona="Default AI",
        prompt="", language="en",
    )

    assert output == MOCKED_RESPONSE
    rendered = _rendered_text(capturing_llm.calls[0])
    assert "Public Forum" in rendered


@pytest.mark.asyncio
async def test_regression_lincoln_douglas_format_still_works(capturing_llm):
    chain = get_debater_chain(
        model_name="openai/gpt-4o-mini", round_num=1, debate_type="bill", debate_format="lincoln-douglas",
    )

    output = await chain.arun(
        debater_role="Affirmative", topic="Test Bill", bill_description="Section 1: test bill text.",
        history="", full_transcript="", round_num=1, persona_prompt="", persona="Default AI",
        prompt="", language="en",
    )

    assert output == MOCKED_RESPONSE
    rendered = _rendered_text(capturing_llm.calls[0])
    assert "Lincoln-Douglas" in rendered


@pytest.mark.asyncio
async def test_regression_default_bill_debate_format_still_works(capturing_llm):
    chain = get_debater_chain(model_name="openai/gpt-4o-mini", round_num=1, debate_type="bill")

    output = await chain.arun(
        debater_role="Con", topic="Test Bill", bill_description="Section 1: test bill text.",
        history="", full_transcript="", round_num=1, persona_prompt="", persona="Default AI",
        prompt="", language="en",
    )

    assert output == MOCKED_RESPONSE
    rendered = _rendered_text(capturing_llm.calls[0])
    assert "5‑round structured debate" in rendered or "5" in rendered


@pytest.mark.asyncio
async def test_regression_detailed_frontend_prompt_bypasses_templates(capturing_llm):
    """AI-vs-AI Public Forum sends a fully pre-built prompt containing
    "CRITICAL WORD COUNT" -- process_inputs must still route this straight
    through as a direct prompt, unaffected by Increment 9's changes."""
    detailed_prompt = (
        "CRITICAL WORD COUNT: write between 550 and 600 words.\n" + ("Detailed constructive content. " * 40)
    )
    chain = get_debater_chain(model_name="openai/gpt-4o-mini", round_num=1, debate_type="bill", debate_format="public-forum")

    output = await chain.arun(
        debater_role="Pro", topic="Test Bill", bill_description="", history="",
        full_transcript="", round_num=1, persona_prompt="", persona="Default AI",
        prompt=detailed_prompt, language="en",
    )

    assert output == MOCKED_RESPONSE
    rendered = _rendered_text(capturing_llm.calls[0])
    assert "CRITICAL WORD COUNT" in rendered
