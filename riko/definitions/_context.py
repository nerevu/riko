# vim: sw=4:ts=4:expandtab
"""
The immutable environment a module runs in.

Examples:

    Basic usage::

        >>> from riko import Context, ExecutionMode
        >>>
        >>> base = Context(ExecutionMode.DESCRIBE, inputs={"count": 2})
        >>> derived = base.replace(inputs={"limit": 5})
        >>> base.inputs["count"]
        2
        >>> derived.describe_input
        True
        >>> dict(derived.inputs)
        {'limit': 5}

"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Literal, Self, overload

from attrs import define, evolve, field

from riko.base._guards import require_mapping
from riko.base._require_guards import def_from_require
from riko.base._typing import resolve_enum
from riko.types._enums import ExecutionMode
from riko.types._frozendict import (
    FrozenDict,
    freeze,
    instances_freezer,
    mapping_converter,
)
from riko.types._resource import is_lifecycle_factory

from ._resource_definition import Resource, ReusableResource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._resource import LifecycleFactory
    from riko.types._values import Inputs

    from ._resource_definition import ResourceDefinition, ReusableResources

type ResourcesInput = Mapping[str, ReusableResource[object]]

INPUT_MODES = {ExecutionMode.DESCRIBE_INPUTS, ExecutionMode.DESCRIBE}
DEPENDENCY_MODES = {ExecutionMode.DESCRIBE_DEPENDENCIES, ExecutionMode.DESCRIBE}
EMPTY_RESOURCES: ReusableResources = FrozenDict()

_normalize_mode = partial(
    resolve_enum, ExecutionMode, default=ExecutionMode.RUN, error=ValueError
)
_input_converter = [
    def_from_require(require_mapping, what="Context 'inputs'", error=TypeError),
    freeze,
]
_freezer = instances_freezer(ReusableResource, "Context resource", error=TypeError)
_resources_converter = mapping_converter(
    _freezer, ResourcesInput, what="Context 'resources'", error=TypeError
)


@define(frozen=True, slots=True, eq=False, repr=False)
class Context:
    """
    An immutable environment a module runs in.

    Attributes:

        mode: Whether a workflow module's pipe runs its workflow or only describes it
            (a ``Pipeline`` always runs).

        inputs: Read-only input values an ``input`` module reads in place of its
            default, or ``None`` when none were given (an ``input`` module then
            prompts unless ``test``).

        test: Whether to use defaults instead of prompting.

        resources: Read-only, keyed by name, and populated only via ``with_resource``.

    """

    mode: ExecutionMode = field(default=ExecutionMode.RUN, converter=_normalize_mode)
    inputs: Inputs | None = field(default=None, converter=_input_converter)
    test: bool = field(default=False, converter=bool)
    resources: ReusableResources = field(
        default=EMPTY_RESOURCES,
        converter=_resources_converter,
        alias="_resources",
        kw_only=True,
    )

    def __repr__(self) -> str:
        content = f"mode={self.mode}, test={self.test}, "
        inputs = None if self.inputs is None else dict(self.inputs)
        content += f"inputs={inputs}"
        return f"Context({content})"

    def _normalize_definition[T](
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

    def replace(
        self,
        *,
        mode: ExecutionMode | None = None,
        inputs: Inputs | None = None,
        test: bool | None = None,
    ) -> Self:
        """
        Derives a fresh Context snapshot with the given fields overridden.

        A shared Context is safe to reuse because derivation never mutates the
        original. To modify ``resources``, use ``with_resource`` instead of passing
        a ``resources`` argument.

        Args:

            mode: Replacement execution mode, or ``None`` to keep the current one.
            inputs: Replacement input overrides, or ``None`` to keep the current ones.
            test: Replacement test flag, or ``None`` to keep the current one.

        Returns:

            A new Context; the original is left unchanged.

        """
        return evolve(
            self,
            mode=self.mode if mode is None else mode,
            inputs=self.inputs if inputs is None else inputs,
            test=self.test if test is None else test,
        )

    @overload
    def with_resource[T](
        self,
        name: str,
        definition: LifecycleFactory[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    @overload
    def with_resource[T](
        self,
        name: str,
        definition: ReusableResource[T],
        *,
        credential: None = ...,
        lazy: Literal[False] = ...,
    ) -> Self: ...
    @overload
    def with_resource[T](
        self,
        name: str,
        definition: ResourceDefinition[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    def with_resource[T](
        self,
        name: str,
        definition: ResourceDefinition[T],
        *,
        credential: str | None = None,
        lazy: bool = False,
    ) -> Self:
        """
        Provides a resource ``definition`` under ``name`` in a new Context snapshot.

        The ``definition`` is either a ``ReusableResource`` or ``LifecycleFactory``. A
        factory is stored here, but only entered in the execution layer. So
        ``credential``/``lazy`` apply only to a factory.

        Args:

            name: The Context name the resource is provided under.
            definition: A ``Resource``/``LifecycleFactory`` that wraps a resource value.
            credential: A credential reference for a factory.
            lazy: Whether entry should defer until first use. Not yet honored: a run
                acquires every resource its nodes bind, whether or not it is used.

        Returns:

            A new Context; the original is left unchanged.

        Raises:

            TypeError: When ``credential``/``lazy`` accompany a ``Resource`` (they
                belong on a ``LifecycleFactory``).

        """
        resource = self._normalize_definition(
            definition, credential=credential, lazy=lazy
        )
        return evolve(self, _resources={**self.resources, name: resource})

    @property
    def describe_input(self) -> bool:
        """Whether a workflow module's pipe reports its input declarations instead."""
        return self.mode in INPUT_MODES

    @property
    def describe_dependencies(self) -> bool:
        """Whether a workflow module's pipe reports what its workflow uses instead."""
        return self.mode in DEPENDENCY_MODES


__all__ = ["Context", "ExecutionMode"]
