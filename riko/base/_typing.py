# vim: sw=4:ts=4:expandtab
"""Runtime type-hint helpers: PEP 563 resolution and alias/union decomposition."""

from __future__ import annotations

from types import ModuleType, UnionType
from typing import (
    TYPE_CHECKING,
    Annotated,
    Any,
    TypeAliasType,
    Union,
    get_args,
    get_origin,
    get_type_hints,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping


def resolve_alias(annotation: object) -> object:
    """
    Resolves a ``type`` alias to the annotation it names.

    An alias may name another alias (``type A = B``; ``type B = int``), so this
    follows the chain to its end. Any other annotation passes through.

    Args:

        annotation: The annotation to resolve.

    Returns:

        The annotation the alias chain ends at, or ``annotation`` itself.

    Examples:

        >>> type Count = int
        >>> type Total = Count
        >>> resolve_alias(Total), resolve_alias(str)
        (<class 'int'>, <class 'str'>)

    """
    while isinstance(annotation, TypeAliasType):
        annotation = annotation.__value__

    return annotation


def gen_union_members(annotation: object) -> Iterator[object]:
    """
    Generates the arms of an annotation once aliases, unions, and ``Annotated`` go.

    Aliases are resolved and unions flattened at every level, and ``Annotated[T, ...]``
    yields the arms of ``T``. Anything else is one arm.

    Args:

        annotation: The annotation to decompose.

    Yields:

        Each arm in declaration order.

    Examples:

        >>> from typing import Annotated
        >>>
        >>> type Number = int | float
        >>> list(gen_union_members(Annotated[Number, "units"] | str))
        [<class 'int'>, <class 'float'>, <class 'str'>]

    """
    annotation = resolve_alias(annotation)
    origin = get_origin(annotation)

    if origin is Union or origin is UnionType:
        for arg in get_args(annotation):
            yield from gen_union_members(arg)
    elif origin is Annotated:
        yield from gen_union_members(get_args(annotation)[0])
    else:
        yield annotation


def resolve_type_hints(
    obj: object,
    *namespaces: ModuleType | Mapping[str, object],
    include_extras: bool = False,
) -> dict[str, Any]:
    """
    Resolves an object's type hints, supplementing the lookup namespace.

    ``get_type_hints`` evaluates PEP 563 (``from __future__ import annotations``)
    string annotations against the defining module's globals, so a name imported
    only under ``TYPE_CHECKING`` fails to resolve. Each entry in ``namespaces``,
    a module or a mapping, is merged into the local namespace in order (later
    entries win) so those forward references resolve.

    Args:

        obj: The module, class, or callable whose hints to resolve.
        namespaces: Modules or mappings whose names supplement the local namespace.
        include_extras: Whether to keep ``Annotated`` metadata.

    Returns:

        The resolved ``name -> type`` mapping.

    Examples:

        >>> from collections.abc import Iterator
        >>> import collections.abc as abc
        >>>
        >>> def pipe(items) -> "Iterator[int]":
        ...     return iter(items)
        >>>
        >>> resolve_type_hints(pipe, abc)["return"]
        collections.abc.Iterator[int]

    """
    localns: dict[str, object] = {}

    for namespace in namespaces:
        localns.update(
            vars(namespace) if isinstance(namespace, ModuleType) else namespace
        )

    return get_type_hints(obj, localns=localns, include_extras=include_extras)
