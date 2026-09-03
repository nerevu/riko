# vim: sw=4:ts=4:expandtab
"""
Extensionless-URL parity tests for async ``fetchdata``.

An HTTP source whose URL carries no file extension must have its format inferred
from the response ``Content-Type``. The sync path already did this via
``Fetch.ext``; these tests lock in the async equivalent, where the content type
is threaded through ``async_url_open`` onto ``NamedTextIOWrapper.ext``.
"""

from types import SimpleNamespace
from typing import cast

import pytest

from riko.bado.io import async_url_open
from riko.modules.fetchdata import async_pipe
from riko.types._streams import Item
from tests import skipif_issync

URL = "https://example.test/data"
JSON = b'{"items": [{"title": "A"}, {"title": "B"}]}'
XML = b"<root><items><title>A</title></items><items><title>B</title></items></root>"


def _async_get(content, content_type):
    async def async_get(url, **_):
        return SimpleNamespace(content=content, headers={"content-type": content_type})

    return async_get


async def _titles(conf):
    items = await async_pipe(conf=conf)
    return [cast(Item, item).get("title") for item in items]


@skipif_issync
class TestExtensionlessAsyncUrlOpen:
    """``async_url_open`` exposes an ``ext`` derived from the content type."""

    @pytest.mark.parametrize(
        ("content_type", "expected"),
        [
            ("application/json; charset=utf-8", "json"),
            ("text/xml", "xml"),
            ("text/html", "html"),
        ],
    )
    @pytest.mark.anyio
    async def test_ext_from_content_type(self, monkeypatch, content_type, expected):
        monkeypatch.setattr("riko.bado.io.async_get", _async_get(b"{}", content_type))
        f = await async_url_open(URL)
        assert f.ext == expected
        assert f.content_type == content_type


@skipif_issync
class TestExtensionlessFetchdata:
    """``fetchdata`` infers the parser for an extensionless HTTP URL."""

    @pytest.mark.parametrize(
        ("content", "content_type"), [(JSON, "application/json"), (XML, "text/xml")]
    )
    @pytest.mark.anyio
    async def test_file_contents(self, monkeypatch, content, content_type):
        monkeypatch.setattr("riko.bado.io.async_get", _async_get(content, content_type))
        result = await _titles({"url": URL, "path": "items"})
        assert result == ["A", "B"]

    @pytest.mark.xfail(
        strict=True,
        reason="splitext keeps the query string in the extension ('json?token=abc'), "
        "so the JSON parser is never selected ",
    )
    @pytest.mark.anyio
    async def test_query_string_does_not_defeat_extension(self, monkeypatch):
        """
        A URL carrying both an extension and a query string must still detect
        its format from the extension alone.
        """
        monkeypatch.setattr(
            "riko.bado.io.async_get", _async_get(JSON, "application/json")
        )
        url = "https://example.test/export.json?token=abc"
        result = await _titles({"url": url, "path": "items"})
        assert result == ["A", "B"]
