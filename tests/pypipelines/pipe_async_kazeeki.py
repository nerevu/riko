# vim: sw=4:ts=4:expandtab


from twisted.internet import defer
from twisted.internet.task import react

from riko import Context
from riko.collections import AsyncPipe
from tests.pypipelines._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf


async def pipe_async_kazeeki(reactor, context: Context | None = None):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["rename", "regex"]
    else:
        output = await (
            AsyncPipe("fetchdata", context=context, conf=fetchdata_conf)
            .rename(conf=rename_conf)
            .regex(conf=regex_conf)
            .alist
        )

    return output


def _main(reactor):
    return defer.ensureDeferred(pipe_async_kazeeki(reactor, Context()))


if __name__ == "__main__":
    react(_main)
