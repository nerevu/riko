# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-written stored-workflow fixture that a ``loop`` embeds to shout each item."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.modules.strconcat import pipe as strconcat
from riko.runtime._workflow_pipes import workflow
from riko.types.modules import StrconcatRawConf

if TYPE_CHECKING:
    from riko.definitions._context import Context


@workflow(subtype="transformer")
def pipe(item=None, context: Context | None = None, **_):
    sw_1 = strconcat(
        item,
        conf=StrconcatRawConf(
            {
                "part": [
                    {"subkey": "title", "type": "text"},
                    {"type": "text", "value": "!"},
                ]
            }
        ),
        context=context,
    )
    _OUTPUT = sw_1

    return _OUTPUT


if __name__ == "__main__":
    for i in pipe():
        print(i)
