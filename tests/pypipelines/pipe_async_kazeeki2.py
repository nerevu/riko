# vim: sw=4:ts=4:expandtab

from riko import Context
from riko.bado import run
from riko.collections import AsyncPipe
from riko.types.general import Conf
from tests.pypipelines._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf


async def pipe_async_kazeeki2(
    item=None, conf: Conf = None, context: Context | None = None, **kwargs
):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["itembuilder", "rename", "regex"]
    else:
        source = AsyncPipe("itembuilder", context=context, conf=itembuilder_conf)
        output = await source.rename(conf=rename_conf).regex(conf=regex_conf)

    return list(output)


async def _main():
    pipeline = await pipe_async_kazeeki2(context=Context())

    for i in pipeline:
        print(i)


if __name__ == "__main__":
    run(_main)
