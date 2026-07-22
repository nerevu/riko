# vim: sw=4:ts=4:expandtab

import pytest

pytest.importorskip("twisted")

from twisted.internet import defer  # noqa: E402
from twisted.internet.task import react  # noqa: E402

from riko import Context
from riko.collections import AsyncPipe
from riko.types.general import Conf
from tests.pypipelines._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf


async def pipe_async_kazeeki(
    reactor, item=None, conf: Conf = None, context: Context | None = None, **kwargs
):
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
    return defer.ensureDeferred(pipe_async_kazeeki(reactor, context=Context()))


if __name__ == "__main__":
    react(_main)
