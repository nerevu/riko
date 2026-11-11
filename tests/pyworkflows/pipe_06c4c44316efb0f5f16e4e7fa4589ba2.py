# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_06c4c44316efb0f5f16e4e7fa4589ba2 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.ext import resolve_inputs, workflow
from riko.modules.fetch import pipe as fetch
from riko.modules.input import pipe as _input
from riko.modules.sort import pipe as sort
from riko.modules.tail import pipe as tail
from riko.types.modules import FetchRawConf, InputRawConf, SortRawConf, TailRawConf

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {
    "numberinput1": {
        "default": "5",
        "description": "How many items do you want in the feed?",
        "type": "string",
    }
}


@workflow(
    subtype="transformer",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["fetch", "input", "sort", "tail"],
)
def pipe(item: Item | None = None, context: Context | None = None, **_):
    inputs = resolve_inputs(INPUT_SCHEMAS, None if context is None else context.inputs)
    sw_123 = fetch(
        item,
        conf=FetchRawConf(
            {
                "url": {
                    "type": "url",
                    "value": "file://riko/data/news.yahoo.com_rss_topstories.xml",
                }
            }
        ),
        context=context,
    )
    sw_135 = sort(
        sw_123,
        conf=SortRawConf(
            {
                "rule": [
                    {
                        "dir": {"type": "text", "value": "DESC"},
                        "field": {"type": "text", "value": "title"},
                    }
                ]
            }
        ),
        context=context,
    )
    sw_131 = _input(
        None,
        conf=InputRawConf({"input_key": {"type": "text", "value": "numberinput1"}}),
        inputs=inputs,
        context=context,
    )
    sw_106 = tail(
        sw_135,
        conf=TailRawConf({"count": {"terminal": "count", "type": "float"}}),
        context=context,
        count=sw_131,
    )
    _OUTPUT = sw_106

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
