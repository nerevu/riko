# vim: sw=4:ts=4:expandtab
"""
Sync/async parity: the differences between ``SyncPipe`` and ``AsyncPipe`` are execution
mechanics, not observable pipeline semantics. Each test builds the *same* pipeline spec
on both engines and asserts identical output: chaining, assignment, emit, aggregators,
one-shot re-iteration, and chain-after-partial-run.

Lifecycle/close/split/export parity lives in ``test_pipe_lifecycle.py`` and
``test_collections.py`` (mirrored sync/async classes); mode propagation in
``test_context_modes.py``. This file locks *data-output* equivalence.
"""

from riko.collections import AsyncPipe, SyncPipe
from riko.types._streams import Item
from riko.types.modules import ItemBuilderConf, StrReplaceConf, StrReplaceConfRule
from tests import PipeBuilder, aresolve, skipif_issync

BUILDER_CONF = ItemBuilderConf({"attrs": {"key": "content", "value": "a,bb,ccc"}})
STRR_CONF = StrReplaceConf({"rule": StrReplaceConfRule(find="c", replace="C")})


def _both[P: (SyncPipe, AsyncPipe), T](
    build: PipeBuilder,
) -> tuple[list[Item], list[Item]]:
    """
    Run *build* on both engines; return ``(sync_result, async_result)``.
    """
    sync_result = list(build(SyncPipe))
    async_result = aresolve(build(AsyncPipe))
    return sync_result, async_result


def _tokenize[P: (SyncPipe, AsyncPipe)](pipe: type[P]) -> P:
    return pipe("itembuilder", conf=BUILDER_CONF).tokenizer(emit=True)


@skipif_issync
class TestOutputParity:
    def test_pipe_chaining(self):
        sync_result, async_result = _both(lambda pipe: _tokenize(pipe).count())
        assert sync_result == async_result == [{"count": 3}]

    def test_assignment_preserves_parent(self):
        sync_result, async_result = _both(lambda pipe: _tokenize(pipe).hash(assign="h"))
        assert sync_result == async_result
        assert [item.get("content") for item in sync_result] == ["a", "bb", "ccc"]
        assert all("h" in item for item in sync_result)

    def test_emit_false_assigns_onto_content(self):
        build = lambda pipe: _tokenize(pipe).strreplace(
            conf=STRR_CONF, assign="content"
        )
        sync_result, async_result = _both(build)
        assert sync_result == async_result
        assert sync_result == [{"content": "a"}, {"content": "bb"}, {"content": "CCC"}]

    def test_aggregator_reverse(self):
        sync_result, async_result = _both(lambda pipe: _tokenize(pipe).reverse())
        assert sync_result == async_result
        assert sync_result == [{"content": "ccc"}, {"content": "bb"}, {"content": "a"}]

    def test_aggregator_tail(self):
        conf = {"count": 1}
        sync_result, async_result = _both(lambda pipe: _tokenize(pipe).tail(conf=conf))
        assert sync_result == async_result == [{"content": "ccc"}]

    def test_composer_truncate(self):
        sync_result, async_result = _both(
            lambda pipe: _tokenize(pipe).truncate(conf={"count": 2})
        )
        assert sync_result == async_result
        assert sync_result == [{"content": "a"}, {"content": "bb"}]
