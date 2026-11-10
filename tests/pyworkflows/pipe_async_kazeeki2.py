# vim: sw=4:ts=4:expandtab
"""Hand-written async Kazeeki workflow module (variant 2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from riko import Pipeline
from riko.bado._backend import run
from riko.definitions._context import Context
from riko.ext import workflow
from tests.pyworkflows._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

INPUT_SCHEMAS: dict = {}


def build() -> Pipeline:
    """Builds the itembuilder variant of the simple kazeeki chain."""
    source = Pipeline.from_module("itembuilder", conf=itembuilder_conf)
    return source.rename(conf=rename_conf).regex(conf=regex_conf)


@workflow(
    subtype="source",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["itembuilder", "rename", "regex"],
    isasync=True,
)
def async_pipe(context: Context | None = None, **_) -> AsyncIterator:
    stream = aiter(build().with_context(Context() if context is None else context))

    return stream


async def _main():
    async for i in async_pipe(context=Context()):
        print(i)


if __name__ == "__main__":
    run(_main)
