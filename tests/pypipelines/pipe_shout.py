# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
# A small hand-written sub-pipeline used to demonstrate a pipe:-loop.

from riko import Context
from riko.modules._subpipe import mark_subpipe
from riko.modules.strconcat import pipe as strconcat
from riko.types.modules import StrconcatRawConf


def pipe_shout(item=None, context: Context | None = None, **_):
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


mark_subpipe(pipe_shout, subtype="transformer")


if __name__ == "__main__":
    for i in pipe_shout():
        print(i)
