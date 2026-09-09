# vim: sw=4:ts=4:expandtab
"""
riko.context
~~~~~~~~~~~~

Provides the execution context for a pipeline.

Examples:

    Basic usage::

        >>> from riko.context import Context, ExecutionMode
        >>>
        >>> context = Context(ExecutionMode.DESCRIBE, inputs={"count": 2})
        >>> context.describe_input
        True
        >>> context.inputs
        {'count': 2}
        >>> context = context.augment(inputs={"limit": 5})
        >>> context.describe_input
        True
        >>> context.inputs
        {'limit': 5}

"""

from collections.abc import Mapping
from copy import copy
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, Self, overload

from riko.resources import Resource, ReusableResource
from riko.types._collections import Inputs
from riko.types._guards import is_lifecycle_factory, is_mapping
from riko.types._resource import LifecycleFactory, ResourceDefinition, ReusableResources


class ExecutionMode(StrEnum):
    """Whether a run executes the pipeline or only describes it."""

    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


INPUT_MODES = {ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE}
DEPENDENCY_MODES = {ExecutionMode.DESCRIBE_DEPENDENCIES, ExecutionMode.DESCRIBE}


class Context:
    """
    A pipeline execution context.

    Attributes:

        mode: Whether to run or describe the pipeline.
        verbose: Whether to print debug output.
        test: Whether to use defaults instead of prompting.
        inputs: Values that override input defaults.
        submodule: Whether inputs come from a parent pipeline.
        resources: Keyed by name and populated only via ``with_resource``.

    """

    def __init__(
        self,
        mode: ExecutionMode | None = None,
        inputs: Inputs | None = None,
        verbose: bool | None = False,
        test: bool | None = False,
        submodule: bool | None = False,
    ) -> None:
        self.mode: ExecutionMode = mode or ExecutionMode.RUN
        self.verbose: bool = bool(verbose)
        self.test: bool = bool(test)
        self.inputs: Inputs = dict(inputs or {})
        self.submodule: bool = bool(submodule)
        self.resources: ReusableResources = MappingProxyType({})

    def __getstate__(self) -> dict[str, object]:
        return {**self.__dict__, "resources": dict(self.resources)}

    def __setstate__(self, state: Mapping[str, object]) -> None:
        raw = state.get("resources")
        resources = raw if is_mapping(raw) else {}
        self.__dict__.update({**state, "resources": MappingProxyType(dict(resources))})

    def _normalize_def[T](
        self,
        definition: ResourceDefinition[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> ReusableResource[T]:
        if isinstance(definition, ReusableResource):
            if lazy or credential is not None:
                msg = "'credential'/'lazy' apply to a LifecycleFactory, not a "
                msg += f"{type(definition)}."
                raise TypeError(msg)

            resource: ReusableResource[T] = definition
        elif is_lifecycle_factory(definition):
            resource = Resource.from_factory(
                definition, credential=credential, lazy=lazy
            )
        else:
            msg = f"Invalid resource factory: {type(definition)}. Interpreted as "
            msg += "one-shot and cannot be stored in reusable Context. If you know this"
            msg += " callable is a resource lifecycle factory, use "
            msg += "Resource.from_factory(...). If this callable's lifecycle is "
            msg += "externally managed, use Resource.from_external(...)."
            raise TypeError(msg)

        return resource

    def _duplicate(self) -> Self:
        """Copies this Context with independent inputs."""
        context = copy(self)
        context.inputs = dict(self.inputs)
        return context

    def augment(
        self,
        *,
        mode: ExecutionMode | None = None,
        inputs: Inputs | None = None,
        verbose: bool | None = None,
        test: bool | None = None,
        submodule: bool | None = None,
    ) -> Self:
        """
        Augments a new copy of this Context with independent inputs and resources.

        Creates a fresh ``context`` copy with modified attributes so a shared Context
        is safe to reuse. To modify ``resources``, use ``with_resource`` instead of
        passing a ``resources`` argument.

        """
        context = self._duplicate()
        context.mode = context.mode if mode is None else mode
        context.inputs = context.inputs if inputs is None else dict(inputs)
        context.verbose = context.verbose if verbose is None else verbose
        context.test = context.test if test is None else test
        context.submodule = context.submodule if submodule is None else submodule
        return context

    @overload
    def with_resource[T](  # noqa: E704
        self,
        name: str,
        definition: LifecycleFactory[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    @overload  # noqa: E301
    def with_resource[T](  # noqa: E704
        self,
        name: str,
        definition: ReusableResource[T],
        *,
        credential: None = ...,
        lazy: Literal[False] = ...,
    ) -> Self: ...
    def with_resource[T](  # noqa: E301
        self,
        name: str,
        definition: ResourceDefinition[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> Self:
        """
        Binds a resource ``definition`` to ``name`` in a new copy of this Context.

        The ``definition`` is either a ``ReusableResource`` or ``LifecycleFactory``. A
        factory is stored here, but only entered in the execution layer. So
        ``credential``/``lazy`` apply only to a factory.

        Args:

            name: The Context name the resource is bound to.
            definition: A ``Resource``/``LifecycleFactory`` that wraps a resource value.
            credential: A credential reference for a factory.
            lazy: Whether a factory defers entry until first use.

        Returns:

            A new Context; the original is left unchanged.

        Raises:

            TypeError: When ``credential``/``lazy`` accompany a ``Resource`` (they
                belong on a ``LifecycleFactory``).

        """
        resource = self._normalize_def(definition, credential=credential, lazy=lazy)
        context = self._duplicate()
        context.resources = MappingProxyType({**context.resources, name: resource})
        return context

    @property
    def describe_input(self) -> bool:
        """Whether the run reports the pipeline's inputs."""
        return self.mode in INPUT_MODES

    @property
    def describe_dependencies(self) -> bool:
        """Whether the run reports the pipeline's module dependencies."""
        return self.mode in DEPENDENCY_MODES

    def __repr__(self) -> str:
        content = f"mode={self.mode}, verbose={self.verbose}, test={self.test}, "
        content += f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"


__all__ = ["Context", "ExecutionMode"]
