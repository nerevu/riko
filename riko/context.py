# vim: sw=4:ts=4:expandtab
"""
riko.context
~~~~~~~~~~~~
The execution context for a pipeline.
"""

from copy import copy
from enum import StrEnum

from riko.types.values import Inputs


class ExecutionMode(StrEnum):
    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


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

    def __init__(
        self,
        mode: ExecutionMode | None = None,
        inputs: Inputs | None = None,
        verbose: bool | None = False,
        test: bool | None = False,
        submodule: bool | None = False,
        **kwargs: object,
    ) -> None:
        self.mode: ExecutionMode = mode or ExecutionMode.RUN
        self.verbose: bool = bool(verbose)
        self.test: bool = bool(test)
        self.inputs: Inputs = inputs or {}
        self.submodule: bool = bool(submodule)

    @property
    def describe_input(self) -> bool:
        return self.mode in {ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE}

    @property
    def describe_dependencies(self) -> bool:
        return self.mode in {
            ExecutionMode.DESCRIBE_DEPENDENCIES,
            ExecutionMode.DESCRIBE,
        }

    def __repr__(self) -> str:
        content = f"mode={self.mode}, verbose={self.verbose}, test={self.test}, "
        content += f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"


def parse_context(
    context: "Context | None" = None,
    mode: "ExecutionMode | None" = None,
    inputs: Inputs | None = None,
    **kwargs: bool | None,
) -> "Context":
    # Prevents mutating caller-supplied Context
    new_context = copy(context) if context else Context(mode, inputs=inputs, **kwargs)
    new_inputs = new_context.inputs if inputs is None else dict(inputs)
    new_context.inputs = new_inputs
    return new_context


__all__ = ["Context", "ExecutionMode", "parse_context"]
