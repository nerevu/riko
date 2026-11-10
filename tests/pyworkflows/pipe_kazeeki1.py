# vim: sw=4:ts=4:expandtab
"""Hand-written sync Kazeeki workflow module (variant 1)."""

from typing import TYPE_CHECKING

from riko import Pipeline
from riko.definitions._context import Context
from riko.ext import workflow
from tests.pyworkflows._pipe_kazeeki import fetchdata_conf, regex_conf, rename_conf

if TYPE_CHECKING:
    from collections.abc import Iterable

INPUT_SCHEMAS: dict = {}


def build() -> Pipeline:
    """Builds the fetchdata variant of the simple kazeeki chain."""
    source = Pipeline.from_module("fetchdata", conf=fetchdata_conf)
    return source.rename(conf=rename_conf).regex(conf=regex_conf)


@workflow(
    subtype="source",
    input_schemas=INPUT_SCHEMAS,
    dependencies=["fetchdata", "rename", "regex"],
)
def pipe(context: Context | None = None, **_):
    context = Context() if context is None else context
    output: Iterable[object] = list(build().with_context(context))

    return output


if __name__ == "__main__":
    items = pipe(context=Context())

    for i in items:
        print(i)
