# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
# A small hand-written sub-pipeline used to demonstrate a pipe:-loop.

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.modules.strconcat import pipe as strconcat
from riko.runtime._subpipe import mark_subpipe
from riko.types.modules import StrconcatRawConf

if TYPE_CHECKING:
    from riko.runtime.context import Context


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


mark_subpipe(pipe, subtype="transformer")


if __name__ == "__main__":
    for i in pipe():
        print(i)
