# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
Runs the workflow ``../workflows/pipe_timezone.json`` describes.

This module's typed configuration classes let a type checker catch a bad node ``conf``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko import ExecutionMode
from riko.modules.dateformat import pipe as dateformat
from riko.modules.itembuilder import pipe as itembuilder
from riko.runtime._workflow_pipes import workflow
from riko.types.modules import DateFormatRawConf, ItemBuilderRawConf

if TYPE_CHECKING:
    from riko import Context


INPUTS = []
DEPENDENCIES = ["dateformat", "itembuilder"]


@workflow(subtype="source")
def pipe(item=None, context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
        sw_1 = itembuilder(
            item,
            conf=ItemBuilderRawConf(
                {
                    "attrs": [
                        {
                            "key": {"type": "text", "value": "date"},
                            "value": {"type": "text", "value": "5/4/1982"},
                        }
                    ]
                }
            ),
            context=context,
        )
        sw_2 = dateformat(
            sw_1,
            conf=DateFormatRawConf(
                {
                    "format": {"type": "text", "value": "%B %d, %Y %Z"},
                    "timezone": {"type": "text", "value": "EST"},
                }
            ),
            field="date",
            context=context,
        )
        _OUTPUT = sw_2
    elif context.mode is ExecutionMode.DESCRIBE:
        _OUTPUT = {"inputs": INPUTS, "dependencies": DEPENDENCIES}
    elif context.describe_input:
        _OUTPUT = INPUTS
    else:
        _OUTPUT = DEPENDENCIES

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
