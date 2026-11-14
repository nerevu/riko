# vim: sw=4:ts=4:expandtab
"""
The immutable environment a module runs in.

Examples:

    Basic usage::

        >>> from riko import Context
        >>>
        >>> base = Context({"count": 2}, test=True)
        >>> derived = base.replace(inputs={"limit": 5})
        >>> base.inputs["count"]
        2
        >>> derived.test
        True
        >>> dict(derived.inputs)
        {'limit': 5}

"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, overload

from attrs import define, evolve, field

from riko.types._frozendict import FrozenDict, instances_freezer, mapping_converter
from riko.types._resource import is_lifecycle_factory

from ._inputs import freeze_inputs
from ._resource_definition import Resource, ReusableResource

if TYPE_CHECKING:
    from collections.abc import Mapping

    from riko.types._frozendict import FrozenInputs
    from riko.types._resource import LifecycleFactory
    from riko.types._workflow import ResourceName

    from ._resource_definition import ResourceDefinition, ReusableResources
    from ._workflow_definition import Inputs

type ResourcesInput = Mapping[str, ReusableResource[object]]

EMPTY_RESOURCES: ReusableResources = FrozenDict()

_freezer = instances_freezer(ReusableResource, "Context resource", error=TypeError)
_resources_converter = mapping_converter(
    _freezer, ResourcesInput, what="Context 'resources'", error=TypeError
)


@define(frozen=True, slots=True, eq=False, repr=False)
class Context:
    """
    An immutable environment a module runs in.

    Attributes:

        inputs: Read-only JSON input values keyed by input name. They fill the
            workflow's inputs and are what an ``input`` module reads in place of its
            default. When not given, an ``input`` module whose input has no schema
            prompts unless ``test`` is set; given ``{}``, it uses its default instead
            of prompting.

        test: Whether to use defaults instead of prompting.

        resources: Read-only, keyed by name, and populated only via ``with_resource``.

    """

    inputs: FrozenInputs | None = field(default=None, converter=freeze_inputs)
    test: bool = field(default=False, converter=bool)
    resources: ReusableResources = field(
        default=EMPTY_RESOURCES,
        converter=_resources_converter,
        alias="_resources",
        kw_only=True,
    )

    def __repr__(self) -> str:
        inputs = None if self.inputs is None else dict(self.inputs)
        return f"Context(inputs={inputs}, test={self.test})"

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
        self, *, inputs: Inputs | None = None, test: bool | None = None
    ) -> Self:
        """
        Derives a fresh Context snapshot with the given fields overridden.

        A shared Context is safe to reuse because derivation never mutates the
        original. To modify ``resources``, use ``with_resource`` instead of passing
        a ``resources`` argument.

        Kwargs:

            inputs: Replacement input overrides, or ``None`` to keep the current ones.
            test: Replacement test flag, or ``None`` to keep the current one.

        Returns:

            A new Context; the original is left unchanged.

        """
        return evolve(
            self,
            inputs=self.inputs if inputs is None else inputs,
            test=self.test if test is None else test,
        )

    @overload
    def with_resource[T](
        self,
        name: ResourceName,
        definition: LifecycleFactory[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    @overload
    def with_resource[T](
        self,
        name: ResourceName,
        definition: ReusableResource[T],
        *,
        credential: None = ...,
        lazy: Literal[False] = ...,
    ) -> Self: ...
    @overload
    def with_resource[T](
        self,
        name: ResourceName,
        definition: ResourceDefinition[T],
        *,
        credential: str | None = ...,
        lazy: bool = ...,
    ) -> Self: ...
    def with_resource[T](
        self,
        name: ResourceName,
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

        Kwargs:

            credential: A credential reference for a factory. Not yet honored: a run
                never resolves it, so the factory receives no credential.

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


__all__ = ["Context"]
