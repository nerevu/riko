# vim: sw=4:ts=4:expandtab
"""Hand-written sync Kazeeki workflow module (variant 2)."""

from riko import Pipeline
from riko.definitions._context import Context
from riko.types._enums import ExecutionMode
from tests.pyworkflows._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf

INPUTS: list = []
DEPENDENCIES = ["itembuilder", "rename", "regex"]


def build() -> Pipeline:
    """Builds the itembuilder variant of the simple kazeeki chain."""
    source = Pipeline.from_module("itembuilder", conf=itembuilder_conf)
    return source.rename(conf=rename_conf).regex(conf=regex_conf)


def pipe(context: Context | None = None, **_):
    if context is None or context.mode is ExecutionMode.RUN:
        context = Context() if context is None else context
        output: list | dict = list(build().with_context(context))
    elif context.mode is ExecutionMode.DESCRIBE:
        output = {"inputs": INPUTS, "dependencies": DEPENDENCIES}
    elif context.describe_input:
        output = INPUTS
    else:
        output = DEPENDENCIES

    return output


if __name__ == "__main__":
    items = pipe(context=Context())

    for i in items:
        print(i)
