# vim: sw=4:ts=4:expandtab
"""
Extensionless-URL parity tests for async ``fetchdata``.

An HTTP source whose URL carries no file extension must have its format inferred
from the response ``Content-Type``. The sync path already did this via
``Fetch.ext``; these tests lock in the async equivalent, where the content type
is threaded through ``async_url_open`` onto ``NamedTextIOWrapper.ext``.
"""

from types import SimpleNamespace

import pytest

from riko.bado import run
from riko.bado.io import async_url_open
from riko.modules.fetchdata import async_pipe
from tests import skipif_issync

URL = "https://example.test/data"
JSON = b'{"items": [{"title": "A"}, {"title": "B"}]}'
XML = b"<root><items><title>A</title></items><items><title>B</title></items></root>"


def _fake_get(content, content_type):
    async def _get(url, **kwargs):
        return SimpleNamespace(content=content, headers={"content-type": content_type})

    return _get


def _titles(conf):
    captured = []

    async def main():
        captured.extend(await async_pipe(conf=conf))

    run(main)
    return [item["title"] for item in captured]


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
    def test_ext_from_content_type(self, monkeypatch, content_type, expected):
        monkeypatch.setattr("riko.bado.io.async_get", _fake_get(b"{}", content_type))
        captured = {}

        async def main():
            f = await async_url_open(URL)
            captured["ext"] = f.ext
            captured["content_type"] = f.content_type

        run(main)
        assert captured["ext"] == expected
        assert captured["content_type"] == content_type


@skipif_issync
class TestExtensionlessFetchdata:
    """``fetchdata`` infers the parser for an extensionless HTTP URL."""

    def test_json(self, monkeypatch):
        monkeypatch.setattr(
            "riko.bado.io.async_get", _fake_get(JSON, "application/json")
        )
        assert _titles({"url": URL, "path": "items"}) == ["A", "B"]

    def test_xml(self, monkeypatch):
        monkeypatch.setattr("riko.bado.io.async_get", _fake_get(XML, "text/xml"))
        assert _titles({"url": URL, "path": "items"}) == ["A", "B"]
