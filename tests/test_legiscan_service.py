"""Tests for LegiScanService.search_bills's response parsing.

Regression coverage for a bug where getSearchRaw's `searchresult` (a dict
keyed by "summary" plus numeric string indices, not a list) was sliced
directly as a list, raising a silent TypeError and always returning [].
"""
import pytest

from legiscan_service import LegiScanService


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = payload

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


class FakeSession:
    def __init__(self, payload, status=200):
        self._payload = payload
        self._status = status

    def get(self, url):
        return FakeResponse(self._status, self._payload)


GET_SEARCH_PAYLOAD = {
    "status": "OK",
    "searchresult": {
        "summary": {"page": "1 of 1", "count": 2, "relevancy": "100% - 90%"},
        "0": {
            "relevance": 90,
            "bill_id": 222,
            "bill_number": "AB2",
            "title": "Second bill",
            "last_action": "Referred to committee.",
            "last_action_date": "2026-01-02",
            "url": "https://legiscan.com/CA/bill/AB2/2025",
        },
        "1": {
            "relevance": 100,
            "bill_id": 111,
            "bill_number": "SB1",
            "title": "Top bill",
            "last_action": "Chaptered.",
            "last_action_date": "2026-01-01",
            "url": "https://legiscan.com/CA/bill/SB1/2025",
        },
    },
}


@pytest.mark.asyncio
async def test_search_bills_parses_dict_shaped_searchresult():
    service = LegiScanService(api_key="fake-key", session=FakeSession(GET_SEARCH_PAYLOAD))

    bills = await service.search_bills("CA", "education", limit=5)

    assert [b["number"] for b in bills] == ["SB1", "AB2"]


@pytest.mark.asyncio
async def test_search_bills_sorts_by_relevance_before_applying_limit():
    service = LegiScanService(api_key="fake-key", session=FakeSession(GET_SEARCH_PAYLOAD))

    bills = await service.search_bills("CA", "education", limit=1)

    assert len(bills) == 1
    assert bills[0]["number"] == "SB1"


@pytest.mark.asyncio
async def test_search_bills_skips_summary_key_and_non_dict_entries():
    service = LegiScanService(api_key="fake-key", session=FakeSession(GET_SEARCH_PAYLOAD))

    bills = await service.search_bills("CA", "education", limit=5)

    assert all("count" not in b for b in bills)
    assert len(bills) == 2


@pytest.mark.asyncio
async def test_search_bills_returns_empty_list_on_api_error_status():
    payload = {"status": "ERROR", "alert": "invalid query"}
    service = LegiScanService(api_key="fake-key", session=FakeSession(payload))

    bills = await service.search_bills("CA", "", limit=5)

    assert bills == []


@pytest.mark.asyncio
async def test_search_bills_caches_by_state_query_and_limit():
    service = LegiScanService(api_key="fake-key", session=FakeSession(GET_SEARCH_PAYLOAD))

    first = await service.search_bills("CA", "education", limit=5)
    # Swap in a session that would raise if actually called, to prove the
    # cached result is served instead of firing a second request.
    service.session = FakeSession({"status": "ERROR", "alert": "should not be called"})
    second = await service.search_bills("CA", "education", limit=5)

    assert first == second
