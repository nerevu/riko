# vim: sw=4:ts=4:expandtab

from riko.bado import as_async
from riko.bado._backend import run
from riko.collections import AsyncPipe
from riko.context import Context
from tests.pypipelines._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf


async def async_pipe(context: Context | None = None, **_):
    if context and context.describe_input:
        output = []
    elif context and context.describe_dependencies:
        output = ["itembuilder", "rename", "regex"]
    else:
        source = AsyncPipe("itembuilder", context=context, conf=itembuilder_conf)
        output = source.rename(conf=rename_conf).regex(conf=regex_conf)

    async for item in as_async(output):
        yield item


async def _main():
    async for i in async_pipe(context=Context()):
        print(i)


if __name__ == "__main__":
    run(_main)
