# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
Runs the workflow ``../workflows/pipe_679e2c544332e978b15b6b163767975f.json`` describes.

This module's typed configuration classes let a type checker catch a bad node ``conf``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko import ExecutionMode
from riko.modules.itembuilder import pipe as itembuilder
from riko.modules.strreplace import pipe as strreplace
from riko.runtime._workflow_pipes import workflow
from riko.types.modules import ItemBuilderRawConf, StrReplaceRawConf

if TYPE_CHECKING:
    from riko import Context


INPUTS = []
DEPENDENCIES = ["itembuilder", "strreplace"]


@workflow(subtype="source")
def pipe(item=None, context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
        sw_1 = itembuilder(
            item,
            conf=ItemBuilderRawConf(
                {
                    "attrs": [
                        {
                            "key": {"type": "text", "value": "link"},
                            "value": {"type": "text", "value": "www.google.com"},
                        },
                        {
                            "key": {"type": "text", "value": "title"},
                            "value": {"type": "text", "value": "google"},
                        },
                        {
                            "key": {"type": "text", "value": "author"},
                            "value": {"type": "text", "value": "$"},
                        },
                    ]
                }
            ),
            context=context,
        )
        sw_2 = strreplace(
            sw_1,
            conf=StrReplaceRawConf(
                {
                    "rule": [
                        {
                            "find": {"type": "text", "value": "$"},
                            "replace": {"type": "text", "value": "USD"},
                            "param": {"type": "text", "value": "first"},
                        }
                    ]
                }
            ),
            assign="author",
            field="author",
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
