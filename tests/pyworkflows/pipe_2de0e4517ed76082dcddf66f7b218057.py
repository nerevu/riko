# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_2de0e4517ed76082dcddf66f7b218057 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.ext import workflow
from riko.modules.fetch import pipe as fetch
from riko.types.modules import FetchRawConf

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {}


@workflow(subtype="source", input_schemas=INPUT_SCHEMAS, dependencies=["fetch"])
def pipe(item: Item | None = None, context: Context | None = None, **_):
    sw_478 = fetch(
        item,
        conf=FetchRawConf(
            {
                "url": {
                    "type": "url",
                    "value": "file://riko/data/feeds.feedburner.com_ouseful.xml",
                }
            }
        ),
        context=context,
    )
    _OUTPUT = sw_478

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
