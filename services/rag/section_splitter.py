"""Canonical bill-section splitter for the RAG pipeline.

This is the one place bill text is split into discrete, addressable chunks
for retrieval. `main.py`'s `extract_key_bill_sections` is a separate, lossy
helper that truncates oversized bills into a single string to fit an LLM's
context window -- it returns prose, not a list of chunks, and is not reused
or duplicated here.
"""

import re
from typing import List, Optional

from models.lesson_models import BillSection

# Matches lines like "SECTION 1. SHORT TITLE." or "SEC. 4A. Eligibility."
_SECTION_HEADER_RE = re.compile(
    r"^\s*(SEC(?:TION)?\.?\s*(\d+[A-Za-z]?))\.?\s*(.*)$",
    re.IGNORECASE,
)


def _clean_heading(raw_trailing_text: str, fallback: str) -> str:
    heading = raw_trailing_text.strip(" .:-—")
    if not heading:
        return fallback
    if heading.isupper():
        heading = heading.title()
    return heading


def split_bill_into_sections(bill_text: str, bill_id: str) -> List[BillSection]:
    """Split raw bill text into a list of `BillSection` chunks.

    Sections are detected via standard legislative markers ("SECTION 1.",
    "SEC. 2.", ...). Bills with no detectable markers are returned as a
    single "Full Bill Text" section rather than raising, so short or
    unusually formatted bills still retrieve. Blank/whitespace-only chunks
    are dropped.
    """
    if not bill_text or not bill_text.strip():
        return []

    lines = bill_text.splitlines()

    raw_chunks: List[tuple] = []  # (header_match or None, body_lines)
    current_header: Optional[re.Match] = None
    current_body: List[str] = []

    for line in lines:
        match = _SECTION_HEADER_RE.match(line)
        if match:
            if current_header is not None or current_body:
                raw_chunks.append((current_header, current_body))
            current_header = match
            current_body = []
        else:
            current_body.append(line)

    if current_header is not None or current_body:
        raw_chunks.append((current_header, current_body))

    no_markers_found = all(header is None for header, _ in raw_chunks)

    sections: List[BillSection] = []
    for header_match, body_lines in raw_chunks:
        body_text = "\n".join(body_lines).strip()

        if header_match is not None:
            number = header_match.group(2)
            trailing = header_match.group(3)
            heading = _clean_heading(trailing, fallback=f"Section {number}")
            full_text = header_match.group(0).strip()
            if body_text:
                full_text = f"{full_text}\n{body_text}"
        else:
            heading = "Full Bill Text" if no_markers_found else "Preamble"
            full_text = body_text

        if not full_text.strip():
            continue

        order = len(sections)
        sections.append(
            BillSection(
                section_id=f"section-{order + 1}",
                bill_id=bill_id,
                heading=heading,
                text=full_text,
                order=order,
            )
        )

    return sections
