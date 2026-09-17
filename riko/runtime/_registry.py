"""
Generic name registry shared by the module and target registries.

A ``Registry`` resolves names through three tiers with a hybrid lifetime: runtime
registration, then entry point, then built-in. Built-ins are immutable process-global
facts; entry points are discovered by name on first lookup, so no extension imports
until one of its names is resolved; runtime registrations live in a mutable tier that
``reset`` clears for test isolation.

A subclass sets ``entry_point_group`` and ``label``, derives an entry's registry key
via ``_key``, turns a loaded entry point into a concrete entry via ``_load``, and layers
a domain ``resolve`` on top of ``_registered``.

Examples:

    Basic usage::

        >>> from riko.runtime._registry import Registry
        >>>
        >>> class Demo(Registry[int]):
        ...     entry_point_group = "riko.demo"
        ...     label = "demo"
        ...
        ...     def _key(self, entry):
        ...         return str(entry)
        >>>
        >>> demo = Demo()
        >>> demo.register(42)
        >>> demo.registered_names()
        ('42',)

"""

from importlib.metadata import EntryPoint, entry_points
from typing import ClassVar


class Registry[T]:
    """
    A three-tier name registry with a hybrid lifetime.

    Precedence is runtime registration, then entry point, then built-in. Subclasses
    provide the entry-point group, a human ``label`` for messages, and how to turn a
    loaded entry point into a concrete entry.

    """

    entry_point_group: ClassVar[str]
    label: ClassVar[str]

    def __init__(self) -> None:
        self._runtime: dict[str, T] = {}
        self._entry_points: dict[str, EntryPoint] | None = None
        self._loaded: dict[str, T] = {}

    def _key(self, entry: T) -> str:
        raise NotImplementedError(
            f"{type(self).__name__}._key must derive a registry key for {entry!r}"
        )

    def _load(self, ep: EntryPoint) -> T:
        raise NotImplementedError(
            f"{type(self).__name__}._load must handle entry point {ep.name!r}"
        )

    def _discover_entry_points(self) -> dict[str, EntryPoint]:
        if self._entry_points is None:
            eps = entry_points(group=self.entry_point_group)
            self._entry_points = {ep.name: ep for ep in eps}

        return self._entry_points

    def _entry_point(self, name: str) -> T | None:
        if name not in self._loaded and (ep := self._discover_entry_points().get(name)):
            self._loaded[name] = self._load(ep)

        return self._loaded.get(name)

    def _registered(self, name: str) -> T | None:
        return self._runtime.get(name) or self._entry_point(name)

    def register(self, entry: T, *, replace: bool = False) -> None:
        """
        Adds a self-keying entry to the runtime tier that shadows lower tiers.

        The registry key is derived from ``entry`` by ``_key``, so an entry carries
        its own identity rather than being registered under a separate name.

        Args:

            entry: The self-keying entry to register.
            replace: Whether an existing runtime entry with the same key may be
                replaced.

        Raises:

            ValueError: If ``entry`` has no derivable key, or its key is already
                registered and ``replace`` is False.

        """
        name = self._key(entry)

        if not name:
            raise ValueError(f"a runtime-registered {self.label} needs a name")

        if name in self._runtime and not replace:
            raise ValueError(f"{self.label} {name!r} is already registered")

        self._runtime[name] = entry

    def registered_names(self) -> tuple[str, ...]:
        """Collects the sorted runtime-registered names."""
        return tuple(sorted(self._runtime))

    def catalog_names(self) -> tuple[str, ...]:
        """
        Collects the sorted runtime-registered and entry-point names.

        Built-ins are excluded since they are enumerated separately.

        """
        return tuple(sorted({*self._runtime, *self._discover_entry_points()}))

    def reset(self) -> None:
        """Drops runtime registrations and the entry-point discovery cache."""
        self._runtime.clear()
        self._loaded.clear()
        self._entry_points = None


__all__ = ["Registry"]
