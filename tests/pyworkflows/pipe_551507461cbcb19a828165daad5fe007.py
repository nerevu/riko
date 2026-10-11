# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""Hand-maintained typed probe for the pipe_551507461cbcb19a828165daad5fe007 fixture."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko.modules.fetchsitefeed import pipe as fetchsitefeed
from riko.modules.input import pipe as _input
from riko.modules.truncate import pipe as truncate
from riko.runtime._workflows import mark_subpipe
from riko.types._enums import ExecutionMode
from riko.types.modules import FetchSiteFeedRawConf, InputRawConf, TruncateRawConf

if TYPE_CHECKING:
    from riko import Context


INPUTS = [
    ("", "urlinput1", "Enter a URL", "url", "file://riko/data/www.bbc.co.uk_news.html")
]
DEPENDENCIES = ["fetchsitefeed", "input", "truncate"]


def pipe(item=None, context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
        sw_242 = _input(
            item,
            conf=InputRawConf(
                {
                    "debug": {
                        "type": "url",
                        "value": "file://riko/data/www.bbc.co.uk_news.html",
                    },
                    "default": {
                        "type": "url",
                        "value": "file://riko/data/www.bbc.co.uk_news.html",
                    },
                    "name": {"type": "text", "value": "urlinput1"},
                    "position": {"type": "float", "value": ""},
                    "prompt": {"type": "text", "value": "Enter a URL"},
                }
            ),
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
    elif context.mode is ExecutionMode.DESCRIBE:
        _OUTPUT = {"inputs": INPUTS, "dependencies": DEPENDENCIES}
    elif context.describe_input:
        _OUTPUT = INPUTS
    else:
        _OUTPUT = DEPENDENCIES

    return _OUTPUT


mark_subpipe(pipe, subtype="transformer")


if __name__ == "__main__":
    for i in pipe():
        print(i)
