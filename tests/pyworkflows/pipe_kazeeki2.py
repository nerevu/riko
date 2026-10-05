# vim: sw=4:ts=4:expandtab
"""Hand-written sync Kazeeki workflow module (variant 2)."""

from riko import Pipeline
from riko.execution._execution import SyncExecution
from riko.execution.context import Context
from riko.runtime._execution_plan import build_execution_plan
from tests.pyworkflows._pipe_kazeeki import itembuilder_conf, regex_conf, rename_conf


def build() -> Pipeline:
    """Builds the itembuilder variant of the simple kazeeki chain."""
    source = Pipeline.from_module("itembuilder", conf=itembuilder_conf)
    return source.rename(conf=rename_conf).regex(conf=regex_conf)


def pipe(context: Context | None = None, **_):
    output: list = []

    if context and context.describe_dependencies:
        output = ["itembuilder", "rename", "regex"]
    elif not (context and context.describe_input):
        pipeline = build()
        plan = build_execution_plan(pipeline.workflow)

        with SyncExecution(context=context or Context()) as execution:
            output = list(execution.run(plan, source=pipeline.source))

    return output


if __name__ == "__main__":
    pipeline = pipe(context=Context())

    for i in pipeline:
        print(i)
