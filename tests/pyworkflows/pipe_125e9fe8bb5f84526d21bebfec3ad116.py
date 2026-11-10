# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_125e9fe8bb5f84526d21bebfec3ad116 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.ext import resolve_inputs, workflow
from riko.modules.fetchdata import pipe as fetchdata
from riko.modules.input import pipe as _input
from riko.modules.itembuilder import pipe as itembuilder
from riko.modules.loop import pipe as loop
from riko.modules.rename import pipe as rename
from riko.modules.urlbuilder import pipe as urlbuilder
from riko.types.modules import (
    FetchDataRawConf,
    InputRawConf,
    ItemBuilderRawConf,
    RenameRawConf,
    UrlBuilderRawConf,
)

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {
    "textinput1": {"default": "defunkt", "description": "Enter Text", "type": "string"}
}


@workflow(
    subtype="transformer",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["fetchdata", "input", "itembuilder", "loop", "rename", "urlbuilder"],
)
def pipe(item: Item | None = None, context: Context | None = None, **_):
    inputs = resolve_inputs(INPUT_SCHEMAS, None if context is None else context.inputs)
    sw_479 = _input(
        item,
        conf=InputRawConf({"input_key": {"type": "text", "value": "textinput1"}}),
        inputs=inputs,
        context=context,
    )
    sw_467 = itembuilder(
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
        attrs_1_value=sw_479,
    )
    sw_61 = loop(
        sw_467,
        conf=UrlBuilderRawConf(
            {
                "base": {"type": "text", "value": "api.github.com_search_users"},
                "param": [
                    {
                        "key": {"type": "text", "value": "q"},
                        "value": {"subkey": "title", "type": "text"},
                    }
                ],
                "ext": {"type": "text", "value": "json"},
            }
        ),
        emit=False,
        assign="api",
        count="all",
        context=context,
        embed=urlbuilder,
    )
    sw_142 = fetchdata(
        sw_61,
        conf=FetchDataRawConf(
            {
                "url": {"subkey": "api", "type": "url"},
                "path": {"type": "text", "value": "items"},
            }
        ),
        emit=False,
        assign="info",
        count="first",
        context=context,
    )
    sw_351 = rename(
        sw_142,
        conf=RenameRawConf(
            {
                "rule": [
                    {
                        "field": {"type": "text", "value": "info.user_view_type"},
                        "newval": {"type": "text", "value": "description"},
                        "copy": {"type": "bool", "value": True},
                    }
                ]
            }
        ),
        context=context,
    )
    _OUTPUT = sw_351

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
