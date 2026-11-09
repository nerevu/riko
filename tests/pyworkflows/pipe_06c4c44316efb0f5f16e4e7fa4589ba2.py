# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_06c4c44316efb0f5f16e4e7fa4589ba2 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.definitions._inputs import resolve_inputs
from riko.modules.fetch import pipe as fetch
from riko.modules.input import pipe as _input
from riko.modules.sort import pipe as sort
from riko.modules.tail import pipe as tail
from riko.runtime._workflow_pipes import workflow
from riko.types._enums import ExecutionMode
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
DEPENDENCIES = ["fetch", "input", "sort", "tail"]


@workflow(subtype="transformer")
def pipe(item: Item | None = None, context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
        inputs = resolve_inputs(
            INPUT_SCHEMAS, None if context is None else context.inputs
        )
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
    elif context.mode is ExecutionMode.DESCRIBE:
        _OUTPUT = iter([{"input_schemas": INPUT_SCHEMAS, "dependencies": DEPENDENCIES}])
    elif context.describe_input:
        _OUTPUT = iter([INPUT_SCHEMAS])
    else:
        _OUTPUT = iter(DEPENDENCIES)

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
