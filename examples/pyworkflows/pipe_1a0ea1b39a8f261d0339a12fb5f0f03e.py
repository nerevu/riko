# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
Runs the workflow ``../workflows/pipe_1a0ea1b39a8f261d0339a12fb5f0f03e.json`` describes.

This module's typed configuration classes let a type checker catch a bad node ``conf``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.ext import workflow
from riko.modules.datebuilder import pipe as datebuilder
from riko.modules.dateformat import pipe as dateformat
from riko.modules.itembuilder import pipe as itembuilder
from riko.types.modules import DateFormatRawConf, ItemBuilderRawConf

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUT_SCHEMAS = {}


@workflow(
    subtype="source",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["datebuilder", "dateformat", "itembuilder"],
)
def pipe(item: Item | None = None, context: Context | None = None, **_):
    sw_1 = itembuilder(
        item,
        conf=ItemBuilderRawConf(
            {
                "attrs": [
                    {
                        "key": {"type": "text", "value": "content"},
                        "value": {"type": "text", "value": "12/2/2014"},
                    }
                ]
            }
        ),
        context=context,
    )
    sw_2 = datebuilder(sw_1, conf={}, assign="date", context=context)
    sw_3 = dateformat(
        sw_2,
        conf=DateFormatRawConf({"format": {"type": "text", "value": "%B %d, %Y"}}),
        emit=True,
        field="date",
        context=context,
    )
    sw_4 = itembuilder(
        None,
        conf=ItemBuilderRawConf(
            {
                "attrs": [
                    {
                        "key": {"type": "text", "value": "date"},
                        "value": {"terminal": "attrs_1_value", "type": "text"},
                    },
                    {
                        "key": {"type": "text", "value": "year"},
                        "value": {"type": "text", "value": "1201"},
                    },
                ]
            }
        ),
        context=context,
        attrs_1_value=sw_3,
    )
    _OUTPUT = sw_4

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
