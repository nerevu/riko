# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_975789b47f17690a21e89b10a702bcbd fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.ext import resolve_inputs, workflow
from riko.modules.filter import pipe as _filter
from riko.modules.input import pipe as _input
from riko.modules.itembuilder import pipe as itembuilder
from riko.modules.regex import pipe as regex
from riko.modules.rename import pipe as rename
from riko.modules.tokenizer import pipe as tokenizer
from riko.types.modules import (
    FilterRawConf,
    InputRawConf,
    ItemBuilderRawConf,
    RegexRawConf,
    RenameRawConf,
    TokenizerRawConf,
)

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {
    "q": {
        "default": "Here's #: some #hashtags to play #with",
        "description": "Status update",
        "type": "string",
    }
}


@workflow(
    subtype="transformer",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["filter", "input", "itembuilder", "regex", "rename", "tokenizer"],
)
def pipe(item: Item | None = None, context: Context | None = None, **_):
    inputs = resolve_inputs(INPUT_SCHEMAS, None if context is None else context.inputs)
    sw_417 = _input(
        item,
        conf=InputRawConf({"input_key": {"type": "text", "value": "q"}}),
        inputs=inputs,
        context=context,
    )
    sw_424 = itembuilder(
        None,
        conf=ItemBuilderRawConf(
            {
                "attrs": [
                    {
                        "key": {"type": "text", "value": "title"},
                        "value": {"terminal": "attrs_1_value", "type": "text"},
                    }
                ]
            }
        ),
        context=context,
        attrs_1_value=sw_417,
    )
    sw_436 = _filter(
        sw_424,
        conf=FilterRawConf(
            {
                "combine": {"type": "text", "value": "and"},
                "permit": {"type": "bool", "value": True},
                "rule": [
                    {
                        "field": {"type": "text", "value": "title"},
                        "op": {"type": "text", "value": "contains"},
                        "value": {"type": "text", "value": "#"},
                    }
                ],
            }
        ),
        context=context,
    )
    sw_447 = regex(
        sw_436,
        conf=RegexRawConf(
            {
                "rule": [
                    {
                        "field": {"type": "text", "value": "title"},
                        "match": {"type": "text", "value": " [^#]*"},
                        "replace": {"type": "text", "value": " "},
                    },
                    {
                        "field": {"type": "text", "value": "title"},
                        "match": {"type": "text", "value": "^[^#]*"},
                        "replace": {"type": "text", "value": ""},
                    },
                ]
            }
        ),
        emit=True,
        assign="loop:regex",
        count="all",
        context=context,
    )
    sw_470 = tokenizer(
        sw_447,
        conf=TokenizerRawConf({"delimiter": {"type": "text", "value": " "}}),
        emit=True,
        assign="loop:tokenizer",
        field="title",
        count="all",
        context=context,
    )
    sw_490 = _filter(
        sw_470,
        conf=FilterRawConf(
            {
                "combine": {"type": "text", "value": "and"},
                "permit": {"type": "bool", "value": True},
                "rule": [
                    {
                        "field": {"type": "text", "value": "content"},
                        "op": {"type": "text", "value": "matches"},
                        "value": {"type": "text", "value": "#[\\w]"},
                    }
                ],
            }
        ),
        context=context,
    )
    sw_501 = rename(
        sw_490,
        conf=RenameRawConf(
            {
                "rule": [
                    {
                        "field": {"type": "text", "value": "content"},
                        "copy": {"type": "bool", "value": False},
                        "newval": {"type": "text", "value": "title"},
                    }
                ]
            }
        ),
        emit=True,
        assign="loop:rename",
        count="all",
        context=context,
    )
    _OUTPUT = sw_501

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
