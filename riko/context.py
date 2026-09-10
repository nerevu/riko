# vim: sw=4:ts=4:expandtab
"""
riko.context
~~~~~~~~~~~~

Provides the execution context for a pipeline.

An immutable definition-layer snapshot. Its fields cannot be reassigned, its
``inputs``/``resources`` mappings are read-only containers, and every derivation
(``augment``/``with_resource``/unpickling) constructs a fresh snapshot rather than
mutating an existing one. Immutability is structural: riko does not recursively freeze
arbitrary values referenced by an input or a resource.

Examples:

    Basic usage::

        >>> from riko.context import Context, ExecutionMode
        >>>
        >>> context = Context(ExecutionMode.DESCRIBE, inputs={"count": 2})
        >>> context.describe_input
        True
        >>> context.inputs["count"]
        2
        >>> context = context.augment(inputs={"limit": 5})
        >>> context.describe_input
        True
        >>> "count" in context.inputs
        False
        >>> context.inputs["limit"]
        5

"""

from collections.abc import Callable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Literal, NamedTuple, Self, overload

from riko.resources import Resource, ReusableResource
from riko.types._collections import Inputs
from riko.types._guards import is_lifecycle_factory
from riko.types._resource import LifecycleFactory, ResourceDefinition, ReusableResources


class ExecutionMode(StrEnum):
    """Whether a run executes the pipeline or only describes it."""

    RUN = "run"
    DESCRIBE_INPUTS = "describe_inputs"
    DESCRIBE_DEPENDENCIES = "describe_dependencies"
    DESCRIBE = "describe"


INPUT_MODES = {ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE}
DEPENDENCY_MODES = {ExecutionMode.DESCRIBE_DEPENDENCIES, ExecutionMode.DESCRIBE}


def _immutable_mapping[K, V](value: Mapping[K, V]) -> Mapping[K, V]:
    """Copies ``value`` into a read-only mapping detached from its source."""
    return MappingProxyType(dict(value))


class ContextTuple(NamedTuple):
    mode: ExecutionMode
    inputs: Inputs
    verbose: bool
    test: bool
    submodule: bool
    resources: ReusableResources


class Context:
    """
    An immutable pipeline execution context.

    Attributes:

        mode: Whether to run or describe the pipeline.
        inputs: Read-only values that override input defaults.
        verbose: Whether to print debug output.
        test: Whether to use defaults instead of prompting.
        submodule: Whether inputs come from a parent pipeline.
        resources: Read-only, keyed by name, and populated only via ``with_resource``.

    """

    __slots__ = ("_inputs", "_mode", "_resources", "_submodule", "_test", "_verbose")

    def __init__(
        self,
        mode: ExecutionMode | None = None,
        inputs: Inputs | None = None,
        verbose: bool | None = False,
        test: bool | None = False,
        submodule: bool | None = False,
    ) -> None:
        self._mode = mode or ExecutionMode.RUN
        self._inputs = MappingProxyType(dict(inputs or {}))
        self._verbose = bool(verbose)
        self._test = bool(test)
        self._submodule = bool(submodule)
        self._resources = MappingProxyType({})

    def __reduce__(self) -> tuple[Callable[[ContextTuple], "Context"], ContextTuple]:
        context_tuple = ContextTuple(
            mode=self.mode,
            inputs=dict(self.inputs),
            verbose=self.verbose,
            test=self.test,
            submodule=self.submodule,
            resources=dict(self.resources),
        )
        return (_restore_context, context_tuple)

    @property
    def mode(self) -> ExecutionMode:
        return self._mode

    @property
    def inputs(self) -> Inputs:
        return self._inputs

    @property
    def verbose(self) -> bool:
        return self._verbose

    @property
    def test(self) -> bool:
        return self._test

    @property
    def submodule(self) -> bool:
        return self._submodule

    @property
    def resources(self) -> ReusableResources:
        return self._resources

    @classmethod
    def _from_parts(cls, context_tuple: ContextTuple) -> Self:
        resources = _immutable_mapping(context_tuple.resources)
        inputs = _immutable_mapping(context_tuple.inputs)

        context = cls.__new__(cls)
        context._mode = context_tuple.mode
        context._inputs = inputs
        context._verbose = context_tuple.verbose
        context._test = context_tuple.test
        context._submodule = context_tuple.submodule
        context._resources = resources
        return context

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
        Derives a fresh Context snapshot with the given fields overridden.

        A shared Context is safe to reuse because derivation never mutates the
        original. To modify ``resources``, use ``with_resource`` instead of passing
        a ``resources`` argument.

        Args:

            mode: Replacement execution mode, or ``None`` to keep the current one.
            inputs: Replacement input overrides, or ``None`` to keep the current ones.
            verbose: Replacement verbose flag, or ``None`` to keep the current one.
            test: Replacement test flag, or ``None`` to keep the current one.
            submodule: Replacement submodule flag, or ``None`` to keep the current one.

        Returns:

            A new Context; the original is left unchanged.

        """
        context_tuple = ContextTuple(
            mode=self.mode if mode is None else mode,
            inputs=self.inputs if inputs is None else inputs,
            verbose=self.verbose if verbose is None else verbose,
            test=self.test if test is None else test,
            submodule=self.submodule if submodule is None else submodule,
            resources=self.resources,
        )
        return type(self)._from_parts(context_tuple)

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
        Binds a resource ``definition`` to ``name`` in a new Context snapshot.

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
        context_tuple = ContextTuple(
            mode=self.mode,
            inputs=self.inputs,
            verbose=self.verbose,
            test=self.test,
            submodule=self.submodule,
            resources={**self.resources, name: resource},
        )
        return type(self)._from_parts(context_tuple)

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
        content += f"inputs={dict(self.inputs)}, submodule={self.submodule}"
        return f"Context({content})"


def _restore_context(*args) -> Context:
    """Rebuilds a pickled Context through the immutable derivation path."""
    context_tuple = ContextTuple(*args)
    return Context()._from_parts(context_tuple)


__all__ = ["Context", "ExecutionMode"]
