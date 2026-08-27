# vim: sw=4:ts=4:expandtab
"""
riko.context
~~~~~~~~~~~~

Provides the execution context for a pipeline.

Examples:
    Basic usage::

        >>> from riko.context import Context, ExecutionMode, parse_context
        >>>
        >>> context = Context(ExecutionMode.DESCRIBE, test=True)
        >>> context.describe_input
        True
        >>> parse_context(context, inputs={"limit": 5}).inputs
        {'limit': 5}

"""

from copy import copy
from enum import StrEnum

from riko.types.values import Inputs


class ExecutionMode(StrEnum):
    """Whether a run executes the pipeline or only describes it."""

    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


class Context:
    """
    A pipeline execution context.

    Attributes:
        mode: Whether to run or describe the pipeline.
        verbose: Whether to print debug output.
        test: Whether to use defaults instead of prompting.
        inputs: Values that override input defaults.
        submodule: Whether inputs come from a parent pipeline.

    """

    def __init__(
        self,
        mode: ExecutionMode | None = None,
        inputs: Inputs | None = None,
        verbose: bool | None = False,
        test: bool | None = False,
        submodule: bool | None = False,
        **_: object,
    ) -> None:
        self.mode: ExecutionMode = mode or ExecutionMode.RUN
        self.verbose: bool = bool(verbose)
        self.test: bool = bool(test)
        self.inputs: Inputs = inputs or {}
        self.submodule: bool = bool(submodule)

    @property
    def describe_input(self) -> bool:
        """Whether the run reports the pipeline's inputs."""
        return self.mode in {ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE}

    @property
    def describe_dependencies(self) -> bool:
        """Whether the run reports the pipeline's module dependencies."""
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
    """
    Returns a Context with its own inputs withoout mutating the caller's.

    Copies a supplied ``context`` (or builds a fresh one) so a shared Context is
    safe to reuse, then substitutes ``inputs`` when given.

    """
    new_context = copy(context) if context else Context(mode, inputs=inputs, **kwargs)
    new_inputs = new_context.inputs if inputs is None else dict(inputs)
    new_context.inputs = new_inputs
    return new_context


__all__ = ["Context", "ExecutionMode", "parse_context"]
