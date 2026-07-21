"""Shared JSON-parsing helper for LLM responses (lesson + vocabulary generation)."""

import json
import re


def extract_json_object(raw_text: str) -> dict:
    """Parse a model's response as JSON, tolerating ```json ... ``` fences.

    Raises `ValueError` (not a domain-specific exception) so each caller can
    wrap it in its own error type with its own context.
    """
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model did not return valid JSON: {e}") from e
