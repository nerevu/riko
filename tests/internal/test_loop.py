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
from riko.types.compile import EmbeddedModule
from riko.types.modules import (
    AnyModuleRawConf,
    ConfArg,
    Embed,
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

    def test_loop_count_first_is_global_current_behavior(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "first"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(loop(iter(PARENTS), embed=tokenizer, conf=conf))
        # Current: count="first" applies once to the *flattened* stream.
        # Phase 2 target: per-parent first -> [{"content": "a"}, {"content": "c"}]
        assert result == [{"content": "a"}]

    def test_loop_assign_count_first_drops_parent_current_behavior(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "first"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(
            loop(iter(PARENTS), embed=tokenizer, conf=conf, assign="first", emit=False)
        )
        # Current: assign folds onto an empty dict (parent lost) and count is
        # global, so only one item survives.
        # Phase 2 target:
        #   [{"title": "a b", "first": {"content": "a"}},
        #    {"title": "c d", "first": {"content": "c"}}]
        assert result == [{"first": {"content": "a"}}]

    def test_loop_assign_count_all_drops_parent_current_behavior(self):
        conf = LoopRawConf(
            {
                "count": {"type": "text", "value": "all"},
                "embed": _tokenizer_embed(emit={"type": "bool", "value": True}),
            }
        )
        result = list(
            loop(iter(PARENTS), embed=tokenizer, conf=conf, assign="x", emit=False)
        )
        # Current: every child result becomes {"x": ...} with no parent.
        # Phase 2 target: one parent copy per result, e.g.
        #   [{"title": "a b", "x": {"content": "a"}},
        #    {"title": "a b", "x": {"content": "b"}}, ...]
        assert result == [
            {"x": {"content": "a"}},
            {"x": {"content": "b"}},
            {"x": {"content": "c"}},
            {"x": {"content": "d"}},
        ]

    def test_loop_level_field_is_dropped_current_behavior(self):
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
        # Current: loop-level `field` is not forwarded to the embed, so the
        # tokenizer gets no field and yields nothing.
        # Phase 2 target: field selects child input -> a, b, c, d
        assert result == []

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
