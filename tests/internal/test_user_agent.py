# vim: sw=4:ts=4:expandtab
"""Contract tests for configurable HTTP user agents."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from riko._io import Fetch, default_user_agent
from riko.bado import _util
from riko.modules import fetchpage
from riko.types._configs import FetchPageObjconf
from tests import async_test

CUSTOM_USER_AGENT = "Special-Agent/1.0"
TARGET = "http://example.com/page.html"


def test_fetch_uses_custom_user_agent():
    response = Mock()
    response.headers = {}

    with patch("riko._io.requests.get", return_value=response) as mock_requests:
        Fetch(TARGET, binary=True, user_agent=CUSTOM_USER_AGENT)

    headers = mock_requests.call_args.kwargs["headers"]
    assert headers["User-Agent"] == CUSTOM_USER_AGENT


@pytest.mark.parametrize(
    ("user_agent", "expected"),
    [(None, default_user_agent()), (CUSTOM_USER_AGENT, CUSTOM_USER_AGENT)],
)
@async_test
async def test_async_get_resolves_user_agent(monkeypatch, user_agent, expected):
    captured = {}
    response = Mock()

    class StubClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def get(self, url, **kwargs):
            captured.update(kwargs)
            return response

    def async_client(**kwargs):
        return StubClient()

    monkeypatch.setattr(_util, "httpx", SimpleNamespace(AsyncClient=async_client))
    result = await _util.async_get(TARGET, user_agent=user_agent)

    assert result is response
    assert captured["headers"]["User-Agent"] == expected


def test_fetchpage_forwards_user_agent(monkeypatch):
    captured = {}

    class StubFetch(StringIO):
        def __init__(self, url, **kwargs):
            captured.update(kwargs)
            super().__init__("body")

    monkeypatch.setattr(fetchpage, "Fetch", StubFetch)
    objconf = FetchPageObjconf(
        {
            "url": TARGET,
            "encoding": "utf-8",
            "start": "",
            "end": "",
            "token": "",
            "detag": False,
            "user_agent": CUSTOM_USER_AGENT,
        }
    )

    assert list(fetchpage.parser({}, None, objconf)) == ["body"]
    assert captured["user_agent"] == CUSTOM_USER_AGENT


@async_test
async def test_async_fetchpage_forwards_user_agent(monkeypatch):
    captured = {}

    async def stub_async_url_read(url, **kwargs):
        captured.update(kwargs)
        return "body"

    monkeypatch.setattr(fetchpage, "async_url_read", stub_async_url_read)
    objconf = FetchPageObjconf(
        {
            "url": TARGET,
            "encoding": "utf-8",
            "start": "",
            "end": "",
            "token": "",
            "detag": False,
            "user_agent": CUSTOM_USER_AGENT,
        }
    )

    assert list(await fetchpage.async_parser({}, None, objconf)) == ["body"]
    assert captured["user_agent"] == CUSTOM_USER_AGENT
