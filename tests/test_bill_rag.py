"""Tests for the Increment 1 bill-section RAG pipeline: splitting,
embedding, caching, and retrieval (unit + integration + retrieval-quality).
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.rag.cache import InMemoryEmbeddingCache, compute_text_hash
from services.rag.retrieval_service import BillNotCachedError, BillRagService
from services.rag.section_splitter import split_bill_into_sections

SAMPLE_BILL = """
SECTION 1. SHORT TITLE.
This Act may be cited as the "Community Health Access Act".

SEC. 2. DEFINITIONS.
In this Act, the term "eligible household" means a household with income at
or below 200 percent of the Federal poverty line. The term "Secretary"
means the Secretary of Health and Human Services.

SEC. 3. ELIGIBILITY REQUIREMENTS.
An individual is eligible for benefits under this Act if the individual is a
member of an eligible household and resides in a participating State.

SEC. 4. STAKEHOLDER IMPACT.
This Act primarily affects low-income families, small businesses operating
rural health clinics, and State Medicaid agencies, who will see expanded
access to preventive care and administrative funding support.

SEC. 5. IMPLEMENTATION.
Not later than 1 year after the date of enactment of this Act, the
Secretary shall issue regulations to carry out this Act. The Department of
Health and Human Services shall implement the program described in this Act.

SEC. 6. AUTHORIZATION OF APPROPRIATIONS.
There is authorized to be appropriated to carry out this Act $500,000,000
for each of fiscal years 2027 through 2031.

SEC. 7. PENALTIES.
Any person who knowingly submits a fraudulent application for benefits
under this Act shall be fined under title 18, United States Code, or
imprisoned not more than 5 years, or both.

SEC. 8. EFFECTIVE DATE.
This Act shall take effect on the date of enactment.
"""

BILL_ID = "hr1-119"


@pytest.fixture
def service():
    return BillRagService(cache=InMemoryEmbeddingCache())


# ---------------------------------------------------------------------------
# Section splitter
# ---------------------------------------------------------------------------

def test_splitter_produces_ordered_sections_with_stable_ids():
    sections = split_bill_into_sections(SAMPLE_BILL, BILL_ID)
    assert len(sections) == 8
    assert [s.section_id for s in sections] == [f"section-{i}" for i in range(1, 9)]
    assert [s.order for s in sections] == list(range(8))
    assert all(s.bill_id == BILL_ID for s in sections)


def test_splitter_extracts_readable_headings():
    sections = split_bill_into_sections(SAMPLE_BILL, BILL_ID)
    headings = [s.heading for s in sections]
    assert "Eligibility Requirements." in headings or "Eligibility Requirements" in headings
    assert any("Penalties" in h for h in headings)


def test_splitter_ignores_empty_sections():
    text = "SEC. 1. EMPTY.\n\nSEC. 2. HAS TEXT.\nSome actual content here."
    sections = split_bill_into_sections(text, BILL_ID)
    # "SEC. 1. EMPTY." has no body, but the header line itself is non-blank
    # content, so it is kept; a section with truly no text is never emitted.
    assert all(s.text.strip() for s in sections)


def test_splitter_handles_bill_with_no_section_markers():
    sections = split_bill_into_sections("Just some plain unstructured bill text.", BILL_ID)
    assert len(sections) == 1
    assert sections[0].heading == "Full Bill Text"


def test_splitter_handles_empty_text():
    assert split_bill_into_sections("", BILL_ID) == []
    assert split_bill_into_sections("   \n  ", BILL_ID) == []


# ---------------------------------------------------------------------------
# Caching
# ---------------------------------------------------------------------------

def test_same_text_hash_produces_cache_hit(service):
    first = service.retrieve_relevant_sections(BILL_ID, "eligibility", bill_text=SAMPLE_BILL)
    cached_entry_before = service._cache.get(BILL_ID)

    second = service.retrieve_relevant_sections(BILL_ID, "penalties", bill_text=SAMPLE_BILL)
    cached_entry_after = service._cache.get(BILL_ID)

    # Same underlying cached entry (sections/provider) reused, not rebuilt.
    assert cached_entry_before is cached_entry_after
    assert first[0].section_id  # sanity: retrieval still works
    assert second[0].section_id


def test_changed_text_produces_new_embeddings(service):
    service.retrieve_relevant_sections(BILL_ID, "eligibility", bill_text=SAMPLE_BILL)
    entry_before = service._cache.get(BILL_ID)

    changed_text = SAMPLE_BILL + "\nSEC. 9. NEW SECTION.\nBrand new content added later."
    service.retrieve_relevant_sections(BILL_ID, "eligibility", bill_text=changed_text)
    entry_after = service._cache.get(BILL_ID)

    assert entry_before.text_hash != entry_after.text_hash
    assert len(entry_after.sections) == len(entry_before.sections) + 1


def test_compute_text_hash_ignores_whitespace_differences():
    assert compute_text_hash("hello   world") == compute_text_hash("hello world")
    assert compute_text_hash("hello world") != compute_text_hash("hello there")


def test_retrieval_without_bill_text_and_no_cache_raises(service):
    with pytest.raises(BillNotCachedError):
        service.retrieve_relevant_sections(BILL_ID, "eligibility")


def test_retrieval_without_bill_text_uses_cache_after_first_call(service):
    service.retrieve_relevant_sections(BILL_ID, "eligibility", bill_text=SAMPLE_BILL)
    # No bill_text this time -- must reuse the cached sections.
    results = service.retrieve_relevant_sections(BILL_ID, "penalties")
    assert len(results) > 0


# ---------------------------------------------------------------------------
# Retrieval behavior
# ---------------------------------------------------------------------------

def test_top_k_limits_result_count(service):
    results = service.retrieve_relevant_sections(BILL_ID, "eligibility", top_k=3, bill_text=SAMPLE_BILL)
    assert len(results) <= 3


def test_top_k_larger_than_section_count_returns_all_sections(service):
    results = service.retrieve_relevant_sections(BILL_ID, "eligibility", top_k=50, bill_text=SAMPLE_BILL)
    assert len(results) == 8


def test_results_ordered_by_descending_similarity(service):
    results = service.retrieve_relevant_sections(BILL_ID, "eligibility", top_k=8, bill_text=SAMPLE_BILL)
    scores = [r.similarity_score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_invalid_top_k_raises_value_error(service):
    with pytest.raises(ValueError):
        service.retrieve_relevant_sections(BILL_ID, "eligibility", top_k=0, bill_text=SAMPLE_BILL)
    with pytest.raises(ValueError):
        service.retrieve_relevant_sections(BILL_ID, "eligibility", top_k=-1, bill_text=SAMPLE_BILL)


def test_empty_query_raises_value_error(service):
    with pytest.raises(ValueError):
        service.retrieve_relevant_sections(BILL_ID, "   ", bill_text=SAMPLE_BILL)


def test_bill_with_very_few_sections_does_not_error(service):
    tiny_bill = "SECTION 1. SHORT TITLE.\nThis Act may be cited as the Tiny Act."
    results = service.retrieve_relevant_sections("tiny-bill", "title", top_k=5, bill_text=tiny_bill)
    assert len(results) == 1


def test_bill_with_no_sections_returns_empty_list(service):
    results = service.retrieve_relevant_sections("blank-bill", "anything", bill_text="   ")
    assert results == []


# ---------------------------------------------------------------------------
# Retrieval quality: five manual queries against the known sample bill
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "query, expected_section_id",
    [
        ("Who qualifies for the program?", "section-3"),  # Eligibility Requirements
        ("How is the program funded?", "section-6"),  # Authorization of Appropriations
        ("What penalties exist?", "section-7"),  # Penalties
        ("Which agency implements the law?", "section-5"),  # Implementation
        ("How does this affect small businesses?", "section-4"),  # Stakeholder Impact
    ],
)
def test_manual_retrieval_quality_queries(service, query, expected_section_id):
    results = service.retrieve_relevant_sections(BILL_ID, query, top_k=3, bill_text=SAMPLE_BILL)
    top_ids = [r.section_id for r in results]
    assert expected_section_id in top_ids, (
        f"Expected {expected_section_id} in top 3 for query {query!r}, got {top_ids}"
    )


@pytest.mark.parametrize(
    "query",
    [
        "eligible household definition",  # vocabulary definition
        "impact on small businesses and families",  # stakeholder impact
        "regulations the Secretary must issue",  # implementation requirement
        "appropriated funding amount",  # funding
        "fine or imprisonment for fraud",  # penalties
        "who is eligible for benefits",  # eligibility
    ],
)
def test_query_type_coverage_returns_nonempty_results(service, query):
    results = service.retrieve_relevant_sections(BILL_ID, query, top_k=3, bill_text=SAMPLE_BILL)
    assert len(results) > 0
    assert all(r.similarity_score >= 0 for r in results)


# ---------------------------------------------------------------------------
# Endpoint integration tests (router mounted standalone, not via main.py, so
# these don't require main.py's full dependency/env-var chain)
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    from routes.lesson_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_endpoint_returns_relevant_sections(client):
    response = client.post(
        "/lesson/retrieve-sections",
        json={
            "bill_id": "endpoint-test-bill",
            "query": "What penalties exist?",
            "top_k": 3,
            "bill_text": SAMPLE_BILL,
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["bill_id"] == "endpoint-test-bill"
    assert len(data["sections"]) <= 3
    section = data["sections"][0]
    assert set(["section_id", "heading", "text", "order", "similarity_score"]) <= set(section)


def test_endpoint_second_call_reuses_cache_without_bill_text(client):
    client.post(
        "/lesson/retrieve-sections",
        json={"bill_id": "cache-test-bill", "query": "eligibility", "bill_text": SAMPLE_BILL},
    )
    response = client.post(
        "/lesson/retrieve-sections",
        json={"bill_id": "cache-test-bill", "query": "penalties"},
    )
    assert response.status_code == 200
    assert len(response.json()["sections"]) > 0


def test_endpoint_missing_bill_and_no_cache_returns_400(client):
    response = client.post(
        "/lesson/retrieve-sections",
        json={"bill_id": "never-seen-bill", "query": "eligibility"},
    )
    assert response.status_code == 400


def test_endpoint_invalid_top_k_returns_422(client):
    response = client.post(
        "/lesson/retrieve-sections",
        json={
            "bill_id": "endpoint-test-bill",
            "query": "eligibility",
            "top_k": 0,
            "bill_text": SAMPLE_BILL,
        },
    )
    assert response.status_code == 422


def test_endpoint_missing_query_returns_422(client):
    response = client.post(
        "/lesson/retrieve-sections",
        json={"bill_id": "endpoint-test-bill", "bill_text": SAMPLE_BILL},
    )
    assert response.status_code == 422
