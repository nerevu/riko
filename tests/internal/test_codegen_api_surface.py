# vim: sw=4:ts=4:expandtab
"""
Tests the generated API-surface reference document.

The name lists in ``_docs/API_SURFACE.md`` are rendered from the private
``riko.base._api_surface`` contract declaration. The document must stay in sync with
that single source, and every declared surface must appear in it.
"""

import re

import pytest

from riko.base import _api_surface
from riko.cli._gen_api_surface import _BLOCK, _DOC, generate_api_surface

_GROUP_KEYS = (
    "collections",
    "compile",
    "bado",
    "modules",
    "root-exceptions",
    "other",
    "extension",
)


@pytest.fixture
def doc_text() -> str:
    return _DOC.read_text()


def test_api_surface_doc_matches_declaration(doc_text):
    assert generate_api_surface(doc_text) == doc_text


def test_generation_is_idempotent(doc_text):
    once = generate_api_surface(doc_text)
    assert generate_api_surface(once) == once


@pytest.mark.parametrize("key", _GROUP_KEYS)
def test_group_block_present(doc_text, key):
    keys = {match["key"] for match in _BLOCK.finditer(doc_text)}
    assert key in keys


@pytest.mark.parametrize("key", _GROUP_KEYS)
def test_group_block_lists_declared_names(doc_text, key):
    name = key.upper().replace("-", "_")
    rendered = repr(sorted(getattr(_api_surface, name)))
    assert re.search(re.escape(rendered), doc_text)
