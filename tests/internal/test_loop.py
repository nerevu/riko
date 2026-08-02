# vim: sw=4:ts=4:expandtab
"""
Phase 1 Loop characterization tests (docs/gameplans/loop-restructure.md).

These pin the *current* behavior of the explicit ``loop`` operator, including the
places where it diverges from the intended Yahoo per-parent contract. They pass
against today's code; the ``# Phase 2 target:`` notes record the intended output
that Phase 2 will switch to (at which point these assertions are updated in the
same commit that changes the behavior).

Every stream uses at least two parent items — a single parent cannot expose the
global-vs-per-parent ``count`` gap.
"""

import riko.modules.loop as loop_module
from riko.modules.loop import pipe as loop
from riko.modules.regex import pipe as regex
from riko.modules.strconcat import pipe as strconcat
from riko.modules.tokenizer import pipe as tokenizer
from riko.types.modules import (
    AnyModuleRawConf,
    ConfArg,
    Embed,
    EmbeddedModule,
    LoopRawConf,
    ModuleName,
    RegexRawConf,
    RegexRawRule,
    StrconcatRawConf,
    TokenizerRawConf,
)

PARENTS = [{"title": "a b"}, {"title": "c d"}]


def _embed(
    module_name: ModuleName,
    conf: AnyModuleRawConf,
    assign: ConfArg | None = None,
    emit: ConfArg | None = None,
    field: ConfArg | None = None,
) -> Embed:

    value = EmbeddedModule({"type": module_name, "id": "sw-x", "conf": conf})

    if assign:
        value["assign"] = assign

    if emit:
        value["emit"] = emit

    if field:
        value["field"] = field

    return Embed({"type": "module", "value": value})


def _tokenizer_embed(**kwargs) -> Embed:
    base = {
        "field": {"type": "text", "value": "title"},
        "conf": {"delimiter": {"type": "text", "value": " "}},
    }
    return _embed("tokenizer", **base, **kwargs)


class TestLoopCharacterization:
    def test_loop_maps_embed_once_per_parent(self):
        rule = RegexRawRule(
            {
                "field": {"type": "text", "value": "title"},
                "match": {"type": "text", "value": " "},
                "replace": {"type": "text", "value": "_"},
            }
        )
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _embed(
                    "regex",
                    emit={"type": "bool", "value": True},
                    conf=RegexRawConf({"rule": rule}),
                ),
            }
        )
        result = list(loop(iter(PARENTS), embed=regex, conf=conf))
        assert result == [{"title": "a_b"}, {"title": "c_d"}]

    def test_loop_count_all_flattens_embedded_results(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(loop(iter(PARENTS), embed=tokenizer, conf=conf))
        assert result == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]

    def test_loop_count_first_per_parent(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "first"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(loop(iter(PARENTS), embed=tokenizer, conf=conf))
        # Phase 2: count="first" keeps the first result *per parent*.
        assert result == [{"content": "a"}, {"content": "c"}]

    def test_loop_assign_count_first_preserves_parent(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "first"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(
            loop(iter(PARENTS), embed=tokenizer, conf=conf, assign="first", emit=False)
        )
        # Phase 2: the first result per parent is assigned onto the preserved parent.
        assert result == [
            {"title": "a b", "first": {"content": "a"}},
            {"title": "c d", "first": {"content": "c"}},
        ]

    def test_loop_assign_count_all_preserves_parent(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(
            loop(iter(PARENTS), embed=tokenizer, conf=conf, assign="x", emit=False)
        )
        # Phase 2: one preserved-parent copy per child result.
        assert result == [
            {"title": "a b", "x": {"content": "a"}},
            {"title": "a b", "x": {"content": "b"}},
            {"title": "c d", "x": {"content": "c"}},
            {"title": "c d", "x": {"content": "d"}},
        ]

    def test_loop_zero_results_emit_skips_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(loop(parents, embed=tokenizer, conf=conf))
        # Phase 2: a parent with no child results emits nothing (emit mode).
        assert result == [{"content": "x"}, {"content": "y"}]

    def test_loop_zero_results_assign_preserves_parent(self):
        parents = iter([{"title": ""}, {"title": "x y"}])
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(loop(parents, embed=tokenizer, conf=conf, assign="w", emit=False))
        # Phase 2: a parent with no child results is yielded unchanged once.
        assert result == [
            {"title": ""},
            {"title": "x y", "w": {"content": "x"}},
            {"title": "x y", "w": {"content": "y"}},
        ]

    def test_loop_level_field_selects_child_input(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _embed(
                    "tokenizer",
                    emit={"type": "bool", "value": True},
                    conf=TokenizerRawConf(
                        {"delimiter": {"type": "text", "value": " "}}
                    ),
                ),
            }
        )
        result = list(loop(iter(PARENTS), embed=tokenizer, conf=conf, field="title"))
        # Phase 2: loop-level `field` is forwarded to the embed (no embed field
        # needed), so the tokenizer operates on parent["title"].
        assert result == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]

    def test_loop_embed_level_field_current_behavior(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(loop(iter(PARENTS), embed=tokenizer, conf=conf))
        assert result == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]

    def test_loop_dynamic_conf_resolves_per_parent(self):
        parents = iter([{"title": "aa"}, {"title": "bb"}])
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _embed(
                    "strconcat",
                    emit={"type": "bool", "value": True},
                    conf=StrconcatRawConf(
                        {
                            "part": [
                                {"type": "text", "subkey": "title"},
                                {"type": "text", "value": "!"},
                            ]
                        }
                    ),
                ),
            }
        )
        result = list(loop(parents, embed=strconcat, conf=conf))
        assert result == ["aa!", "bb!"]

    def test_loop_has_no_async_pipe_current_behavior(self):
        # Current: the loop module is sync-only; async loop is unimplemented.
        # Phase 3 target: an async_pipe with lazy per-parent streaming.
        assert not hasattr(loop_module, "async_pipe")


class TestProcessorTopLevelCount:
    """
    A direct processor node honors a first-class top-level ``count`` kwarg —
    the runtime enabler for compact-form processor-loop migration.
    """

    def test_count_first_keeps_first(self):
        item = {"title": "a b c"}
        conf = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})
        result = list(
            tokenizer(item, conf=conf, field="title", count="first", emit=True)
        )
        assert result == [{"content": "a"}]

    def test_count_all_keeps_all(self):
        item = {"title": "a b c"}
        conf = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})
        result = list(tokenizer(item, conf=conf, field="title", count="all", emit=True))
        assert result == [{"content": "a"}, {"content": "b"}, {"content": "c"}]

    def test_count_first_assign_preserves_item(self):
        item = {"title": "a b c"}
        conf = TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})
        result = list(
            tokenizer(
                item, conf=conf, field="title", count="first", assign="w", emit=False
            )
        )
        assert result == [{"title": "a b c", "w": {"content": "a"}}]


class TestImplicitLooping:
    """
    A processor stage fed a *stream* maps itself over each item, exactly like
    ``loop(source, embed=<processor>)`` (docs/gameplans/implicit-looping.md).
    """

    def _conf(self):
        return TokenizerRawConf({"delimiter": {"type": "text", "value": " "}})

    def test_maps_over_every_item(self):
        stream = iter([{"title": "a b"}, {"title": "c d"}])
        result = list(tokenizer(stream, conf=self._conf(), field="title", emit=True))
        assert result == [
            {"content": "a"},
            {"content": "b"},
            {"content": "c"},
            {"content": "d"},
        ]

    def test_count_first_is_per_item(self):
        stream = iter([{"title": "a b"}, {"title": "c d"}])
        result = list(
            tokenizer(
                stream, conf=self._conf(), field="title", count="first", emit=True
            )
        )
        assert result == [{"content": "a"}, {"content": "c"}]

    def test_assign_folds_onto_each_item(self):
        stream = iter([{"title": "a b"}, {"title": "c d"}])
        result = list(
            tokenizer(
                stream,
                conf=self._conf(),
                field="title",
                count="first",
                assign="w",
                emit=False,
            )
        )
        assert result == [
            {"title": "a b", "w": {"content": "a"}},
            {"title": "c d", "w": {"content": "c"}},
        ]

    def test_matches_explicit_loop(self):
        parents = [{"title": "a b"}, {"title": "c d"}]
        implicit = list(
            tokenizer(
                iter(parents),
                conf=self._conf(),
                field="title",
                count="first",
                emit=True,
            )
        )
        loop_conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "first"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        explicit = list(loop(iter(parents), embed=tokenizer, conf=loop_conf))
        assert implicit == explicit

    def test_single_item_is_not_double_mapped(self):
        # a loop passes single items to the embedder; the single-item path applies
        item = {"title": "a b"}
        result = list(tokenizer(item, conf=self._conf(), field="title", emit=True))
        assert result == [{"content": "a"}, {"content": "b"}]
