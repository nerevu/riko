# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab

from twisted.internet.task import react
from typing_extensions import Optional

from riko import Context
from riko.collections import AsyncPipe
from riko.bado import coroutine, return_value

from tests.pypipelines._pipe_kazeeki import fetchdata_conf, rename_conf, regex_conf


@coroutine
def pipe_async_kazeeki(reactor, context: Optional[Context] = None):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["rename", "regex"]
    else:
        output = yield (
            AsyncPipe("fetchdata", context=context, conf=fetchdata_conf)
            .rename(conf=rename_conf)
            .regex(conf=regex_conf)
            .alist
        )

    return_value(output)


if __name__ == "__main__":
    react(pipe_async_kazeeki, [Context()])
