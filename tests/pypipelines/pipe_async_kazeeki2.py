# vim: sw=4:ts=4:expandtab
"""Hand-written async Kazeeki pipeline fixture (variant 2)."""

from riko import Pipeline
from riko.bado import as_async
from riko.bado._backend import run
from riko.execution._execution import AsyncExecution
from riko.execution.context import Context
from riko.runtime._execution_plan import build_execution_plan
from tests.pypipelines._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf


def build() -> Pipeline:
    """Builds the itembuilder variant of the simple kazeeki chain."""
    source = Pipeline.from_module("itembuilder", conf=itembuilder_conf)
    return source.rename(conf=rename_conf).regex(conf=regex_conf)


async def async_pipe(context: Context | None = None, **_):
    if context and context.describe_input:
        async for item in as_async([]):
            yield item
    elif context and context.describe_dependencies:
        async for item in as_async(["itembuilder", "rename", "regex"]):
            yield item
    else:
        pipeline = build()
        plan = build_execution_plan(pipeline.workflow)

        async with AsyncExecution(context=context or Context()) as execution:
            stream = await execution.run(plan, source=pipeline.source)

            async for item in stream:
                yield item


async def _main():
    async for i in async_pipe(context=Context()):
        print(i)


if __name__ == "__main__":
    run(_main)
