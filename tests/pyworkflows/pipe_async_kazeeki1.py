# vim: sw=4:ts=4:expandtab
"""Hand-written async Kazeeki workflow module (variant 1)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko import Pipeline
from riko.bado import as_async
from riko.bado._backend import run
from riko.definitions._context import Context
from riko.types._enums import ExecutionMode
from tests.pyworkflows._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def build() -> Pipeline:
    """Builds the fetchdata variant of the simple kazeeki chain."""
    source = Pipeline.from_module("fetchdata", conf=fetchdata_conf)
    return source.rename(conf=rename_conf).regex(conf=regex_conf)


INPUTS: list = []
DEPENDENCIES = ["fetchdata", "rename", "regex"]


def async_pipe(context: Context | None = None, **_) -> AsyncIterator:
    if context is None or context.mode is ExecutionMode.RUN:
        stream = aiter(build().with_context(Context() if context is None else context))
    elif context.mode is ExecutionMode.DESCRIBE:
        stream = as_async([{"inputs": INPUTS, "dependencies": DEPENDENCIES}])
    elif context.describe_input:
        stream = as_async(INPUTS)
    else:
        stream = as_async(DEPENDENCIES)

    return stream


async def _main():
    async for i in async_pipe(context=Context()):
        print(i)


if __name__ == "__main__":
    run(_main)
