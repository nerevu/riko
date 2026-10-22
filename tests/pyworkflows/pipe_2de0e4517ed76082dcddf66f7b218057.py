# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_2de0e4517ed76082dcddf66f7b218057 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.modules.fetch import pipe as fetch
from riko.runtime._workflow_pipes import workflow
from riko.types._enums import ExecutionMode
from riko.types.modules import FetchRawConf

if TYPE_CHECKING:
    from riko import Context
    from riko.types import Item


INPUTS = []
DEPENDENCIES = ["fetch"]


@workflow(subtype="source")
def pipe(item: Item | None = None, context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
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
