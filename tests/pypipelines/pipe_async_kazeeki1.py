# vim: sw=4:ts=4:expandtab

from riko.bado._backend import run
from riko.collections import AsyncPipe
from riko.context import Context
from tests.pypipelines._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf


async def async_pipe(context: Context | None = None, **_):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["fetchdata", "rename", "regex"]
    else:
        source = AsyncPipe("fetchdata", context=context, conf=fetchdata_conf)
        output = await source.rename(conf=rename_conf).regex(conf=regex_conf)

    return list(output)


async def _main():
    pipeline = await async_pipe(context=Context())

    for i in pipeline:
        print(i)


if __name__ == "__main__":
    run(_main)
