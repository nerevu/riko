# vim: sw=4:ts=4:expandtab
"""
Test observable parity between sync and async pipeline iteration.

Each test builds one ``Pipeline`` definition and iterates it both ways, comparing
output across chaining, assignment, emit, aggregators, and composers.

Lifecycle and close parity lives in ``test_pipe_lifecycle.py`` and
``test_async_pipe_lifecycle.py``; mode propagation in ``test_context_modes.py``.
This file locks *data-output* equivalence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from riko import Pipeline
from riko.types._guards import is_mapping
from riko.types.modules import ItemBuilderConf, StrReplaceConf, StrReplaceConfRule
from tests import aresolve, skipif_issync

if TYPE_CHECKING:
    from collections.abc import Callable

    from riko.types._streams import Items

BUILDER_CONF = ItemBuilderConf({"attrs": {"key": "content", "value": "a,bb,ccc"}})
STRR_CONF = StrReplaceConf({"rule": StrReplaceConfRule(find="c", replace="C")})


def _tokenize() -> Pipeline:
    source = Pipeline.from_module("itembuilder", conf=BUILDER_CONF)
    return source.tokenizer(options={"emit": True})


def _both(build: Callable[[Pipeline], Pipeline]) -> tuple[Items, Items]:
    """Iterate *build*'s pipeline both ways; return ``(sync_result, async_result)``."""
    pipeline = build(_tokenize())
    return list(pipeline), aresolve(pipeline)


@skipif_issync
class TestOutputParity:
    @pytest.mark.smoke
    def test_pipe_chaining(self):
        sync_result, async_result = _both(lambda pipeline: pipeline.count())
        assert sync_result == async_result == [{"count": 3}]

    def test_assignment_preserves_parent(self):
        build = lambda pipeline: pipeline.hash(options={"assign": "h"})
        sync_result, async_result = _both(build)
        expected = ["a", "bb", "ccc"]
        assert sync_result == async_result
        assert [
            item.get("content") for item in sync_result if is_mapping(item)
        ] == expected
        assert all("h" in item for item in sync_result if is_mapping(item))

    @pytest.mark.smoke
    def test_emit_false_assigns_onto_content(self):
        build = lambda pipeline: pipeline.strreplace(
            conf=STRR_CONF, options={"assign": "content"}
        )
        sync_result, async_result = _both(build)
        assert sync_result == async_result
        assert sync_result == [{"content": "a"}, {"content": "bb"}, {"content": "CCC"}]

    def test_aggregator_reverse(self):
        sync_result, async_result = _both(lambda pipeline: pipeline.reverse())
        assert sync_result == async_result
        assert sync_result == [{"content": "ccc"}, {"content": "bb"}, {"content": "a"}]

    def test_aggregator_tail(self):
        conf = {"count": 1}
        sync_result, async_result = _both(lambda pipeline: pipeline.tail(conf=conf))
        assert sync_result == async_result == [{"content": "ccc"}]

    def test_composer_truncate(self):
        build = lambda pipeline: pipeline.truncate(conf={"count": 2})
        sync_result, async_result = _both(build)
        assert sync_result == async_result
        assert sync_result == [{"content": "a"}, {"content": "bb"}]
