# vim: sw=4:ts=4:expandtab
"""
riko.resources
~~~~~~~~~~~~~~

Execution resources for a pipeline (PRIVATE).

A ``Resource`` is an immutable definition of an external dependency (e.g., an HTTP
client, database session, credential-backed provider handle). riko owns the
lifecycle of an owned resource and opens it during execution preparation. An
``external`` resource is supplied by the caller and never closed by riko. A
``ResourceView`` is the execution-bound mapping of resolved handles passed to
parsers.

This is the thin slice covering owned/external resources, sync/async open and close,
the execution-bound view, and binding normalization. Lazy opening, ``from_factory``
dependency graphs, and cross-mode bridging remain deferred.

Examples:
    Basic usage::

        >>> from riko.resources import Resource, ResourceView
        >>>
        >>> resource = Resource.from_external(object())
        >>> view = ResourceView({"db": resource.open()})
        >>> view.db is view["db"]
        True

"""

from collections.abc import Callable, Iterable, Mapping
from types import MappingProxyType
from typing import Any, Generic, Never, TypeVar

from typing_extensions import TypeVar as TypeVarExt

type ResourcesLike = str | Iterable[str] | Mapping[str, str]

H = TypeVar("H")
C = TypeVarExt("C", default=Never)


class Resource(Generic[H, C]):
    """
    An immutable execution-resource definition.

    Attributes:
        handle: The resolved handle this resource wraps and hands to parsers.
        external: Whether the caller owns the lifecycle (Riko never closes it).
        credential: A credential reference resolved by the connector layer.
        cleanup: Overrides the handle's ``aclose``/``close`` to close an owned handle.
        lazy: Whether opening defers until first use (validated eagerly).

    Examples:
        >>> from riko.resources import Resource
        >>>
        >>> handle = object()
        >>> resource = Resource(handle)
        >>> resource.open() is handle
        True
        >>> resource.close(handle)

    Note:
        When ``cleanup`` is not given, ``C`` is ``Never`` and ``close``/``aclose``
        return ``None``. When ``cleanup`` is given, ``close``/``aclose`` return ``C``.

    """

    external = False

    def __init__(
        self,
        handle: H,
        *,
        credential: str | None = None,
        cleanup: Callable[[H], C] | None = None,
        lazy: bool = False,
    ) -> None:
        self.handle = handle
        self.credential = credential
        self.lazy = lazy
        self._cleanup = cleanup

    @classmethod
    def from_external[T](cls, handle: T) -> "ExternalResource[T]":
        """
        Creates a resource whose lifecycle remains owned by the caller.

        Args:
            handle: The already-resolved external handle.

        Returns:
            A resource that always resolves to ``handle`` and never closes it.

        """
        return ExternalResource(handle)

    def open(self) -> H:
        """
        Resolves this resource's handle.

        Returns:
            The wrapped handle.

        """
        return self.handle

    async def aopen(self) -> H:
        """
        Resolves this resource's handle for an async parser.

        Returns:
            The wrapped handle.

        """
        return self.handle

    def close(self, handle: H) -> C | None:
        """
        Closes an owned ``handle``.

        A ``cleanup`` override supplies the return value; otherwise the handle's own
        ``close()`` is invoked for its side effect and ``None`` is returned.

        Args:
            handle: The opened handle to close.

        Returns:
            The ``cleanup`` result, or ``None`` when there is no override.

        """
        if self._cleanup is not None:
            result = self._cleanup(handle)
        else:
            if (closer := getattr(handle, "close", None)) is not None:
                closer()

            result = None

        return result

    async def aclose(self, handle: H) -> C | None:
        """
        Closes an owned ``handle`` preferring ``aclose()`` then ``close()``.

        A ``cleanup`` override supplies the return value; otherwise the handle's own
        ``aclose()``/``close()`` is invoked for its side effect and ``None`` is
        returned.

        Args:
            handle: The opened handle to close.

        Returns:
            The ``cleanup`` result, or ``None`` when there is no override.

        """
        aclose = getattr(handle, "aclose", None)

        if self._cleanup is not None or aclose is None:
            result = self.close(handle)
        else:
            await aclose()
            result = None

        return result


class ExternalResource[H](Resource[H, Never]):
    """
    A caller-owned resource that resolves to a fixed handle and never closes it.

    Constructed through :meth:`Resource.from_external`. ``open``/``aopen`` return
    the supplied handle unchanged (inherited). ``close``/``aclose`` are no-ops because
    the caller owns the lifecycle.

    Examples:
        >>> from riko.resources import Resource
        >>>
        >>> class Client:
        ...     closed = False
        ...     def close(self):
        ...         self.closed = True
        >>>
        >>> handle = Client()
        >>> external = Resource.from_external(handle)
        >>> external.open() is handle
        True
        >>> external.close(handle)
        >>> handle.closed
        False

    """

    external = True

    def __init__(self, handle: H) -> None:
        super().__init__(handle)

    def close(self, handle: H) -> None:
        return None

    async def aclose(self, handle: H) -> None:
        return None


class ResourceView:
    """
    An execution-bound view of resolved handles by local binding name.

    Examples:
        >>> from riko.resources import ResourceView
        >>>
        >>> handle = object()
        >>> view = ResourceView({"db": handle})
        >>> view.db is view["db"] is handle
        True
        >>> "db" in view
        True

    """

    def __init__(self, handles: Mapping[str, object]) -> None:
        object.__setattr__(self, "_handles", dict(handles))

    def __getattr__(self, name: str) -> object:
        handles: Mapping[str, object] = object.__getattribute__(self, "_handles")

        if name not in handles:
            raise AttributeError(name)

        return handles[name]

    def __getitem__(self, name: str) -> object:
        handles: Mapping[str, object] = object.__getattribute__(self, "_handles")
        return handles[name]

    def __contains__(self, name: object) -> bool:
        handles: Mapping[str, object] = object.__getattribute__(self, "_handles")
        return name in handles


def normalize_resources(resources: ResourcesLike) -> Mapping[str, str]:
    """
    Normalizes a declared binding into local-alias-to-Context-name form.

    Args:
        resources: A bare name, an iterable of names (each bound to itself), or
            an explicit local-to-Context mapping.

    Returns:
        An immutable mapping of local alias to Context resource name.

    Examples:
        >>> from riko.resources import normalize_resources
        >>>
        >>> normalize_resources(["db", "cache"])
        mappingproxy({'db': 'db', 'cache': 'cache'})
        >>> normalize_resources({"db": "primary_db"})
        mappingproxy({'db': 'primary_db'})

    """
    if isinstance(resources, str):
        binding = {resources: resources}
    elif isinstance(resources, Mapping):
        binding = dict(resources)
    else:
        binding = {name: name for name in resources}

    return MappingProxyType(binding)


def coerce_binding(raw: object) -> ResourcesLike | None:
    """
    Narrows an untyped decoration option into a resource binding, or ``None``.

    Args:
        raw: The ``resources`` value pulled from a module's opts (typed ``object``).

    Returns:
        The value narrowed to ``ResourcesLike`` without a cast, or ``None`` when
        unset.

    Raises:
        TypeError: When ``raw`` is neither a string, mapping, nor iterable.

    Examples:
        >>> from riko.resources import coerce_binding
        >>>
        >>> coerce_binding("client")
        'client'
        >>> coerce_binding(["db", "cache"])
        ['db', 'cache']
        >>> coerce_binding(None) is None
        True

    """
    if raw is None:
        binding: ResourcesLike | None = None
    elif isinstance(raw, str):
        binding = raw
    elif isinstance(raw, Mapping):
        binding = {str(key): str(value) for key, value in raw.items()}
    elif isinstance(raw, Iterable):
        binding = [str(name) for name in raw]
    else:
        raise TypeError(f"invalid 'resources' binding: {raw!r}")

    return binding


def bind_resources(
    binding: ResourcesLike, resources: Mapping[str, Resource[Any, Any]]
) -> ResourceView:
    """
    Opens a node's declared ``binding`` against the Context resource definitions.

    Each local name resolves to a Context resource, which is opened and exposed
    under that alias.

    Args:
        binding: The node's declared resource binding.
        resources: The Context's resource definitions, keyed by Context name.

    Returns:
        A view exposing each opened handle under its local alias.

    Raises:
        TypeError: When a binding names a resource absent from ``resources``;
            all declared bindings are required.
        NotImplementedError: When a resolved resource is owned — owned-resource
            lifecycle is deferred to the execution layer, so supply it as an
            ``external`` resource for now.

    Examples:
        >>> from riko.resources import Resource, bind_resources
        >>>
        >>> handle = object()
        >>> resources = {"primary": Resource.from_external(handle)}
        >>> bind_resources({"handle": "primary"}, resources).handle is handle
        True

    """
    handles: dict[str, object] = {}

    for local, name in normalize_resources(binding).items():
        resource = resources.get(name)

        if resource is None:
            raise TypeError(f"the pipe requires an unbound resource: {name!r}")

        if not resource.external:
            raise NotImplementedError(
                f"owned resource {name!r} lifecycle is pending the execution layer; "
                "supply it as an external resource for now"
            )

        handles[local] = resource.open()

    return ResourceView(handles)


__all__ = [
    "ExternalResource",
    "Resource",
    "ResourceView",
    "ResourcesLike",
    "bind_resources",
    "coerce_binding",
    "normalize_resources",
]
