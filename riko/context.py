# vim: sw=4:ts=4:expandtab
"""
riko.context
~~~~~~~~~~~~
The execution context for a pipeline.
"""

from enum import StrEnum


class ExecutionMode(StrEnum):
    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


def _mode_from_kwargs(kwargs) -> ExecutionMode:
    inputs = bool(kwargs.get("describe_input"))
    dependencies = bool(kwargs.get("describe_dependencies"))

    if inputs and dependencies:
        mode = ExecutionMode.DESCRIBE
    elif inputs:
        mode = ExecutionMode.DESCRIBE_INPUTS
    elif dependencies:
        mode = ExecutionMode.DESCRIBE_DEPENDENCIES
    else:
        mode = ExecutionMode.RUN

    return mode


class Context:
    """
    The context of a pipeline
    mode = whether to run the pipeline or describe its inputs/dependencies
    verbose = debug printing during compilation and running
    test = takes input values from default (skips the console prompt)
    inputs = a dictionary of values that overrides the defaults
        e.g. {'name one': 'test value1'}
    submodule = takes input values from inputs (or default)
    """

    def __init__(self, mode: ExecutionMode | None = None, **kwargs):
        self.mode = mode or _mode_from_kwargs(kwargs)
        self.verbose = bool(kwargs.get("verbose"))
        self.test = bool(kwargs.get("test"))
        self.inputs = dict(kwargs.get("inputs") or {})
        self.submodule = kwargs.get("submodule", False)

    @property
    def describe_input(self) -> bool:
        return self.mode in {ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE}

    @property
    def describe_dependencies(self) -> bool:
        return self.mode in {
            ExecutionMode.DESCRIBE_DEPENDENCIES,
            ExecutionMode.DESCRIBE,
        }

    def __repr__(self):
        content = f"mode={self.mode}, verbose={self.verbose}, test={self.test}, "
        content += f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"


__all__ = ["Context", "ExecutionMode"]
