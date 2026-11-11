# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_551507461cbcb19a828165daad5fe007 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.ext import resolve_inputs, workflow
from riko.modules.fetchsitefeed import pipe as fetchsitefeed
from riko.modules.input import pipe as _input
from riko.modules.truncate import pipe as truncate
from riko.types.modules import FetchSiteFeedRawConf, InputRawConf, TruncateRawConf

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {
    "urlinput1": {
        "default": "file://riko/data/www.bbc.co.uk_news.html",
        "description": "Enter a URL",
        "type": "string",
    }
}


@workflow(
    subtype="transformer",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["fetchsitefeed", "input", "truncate"],
)
def pipe(item: Item | None = None, context: Context | None = None, **_):
    inputs = resolve_inputs(INPUT_SCHEMAS, None if context is None else context.inputs)
    sw_242 = _input(
        item,
        conf=InputRawConf({"input_key": {"type": "text", "value": "urlinput1"}}),
        inputs=inputs,
        context=context,
    )
    sw_234 = fetchsitefeed(
        None,
        conf=FetchSiteFeedRawConf({"url": {"terminal": "1_URL", "type": "url"}}),
        context=context,
        _1_URL=sw_242,
    )
    sw_246 = truncate(
        sw_234,
        conf=TruncateRawConf({"count": {"type": "float", "value": "5"}}),
        context=context,
    )
    _OUTPUT = sw_246

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
