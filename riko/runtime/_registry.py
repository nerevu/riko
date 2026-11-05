"""Generic registry for runtime, entry-point, and built-in named entries."""

from functools import cached_property
from importlib.metadata import EntryPoint, entry_points
from typing import ClassVar


def _get_dist_name(ep: EntryPoint) -> str:
    """Gets the name of the plugin declaring ``ep``, or a placeholder."""
    return "an unknown plugin" if ep.dist is None else ep.dist.name


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
        self._loaded: dict[str, T] = {}

    def _key(self, entry: T) -> str:
        msg = f"{type(self).__name__}._key must derive a registry key for {entry!r}"
        raise NotImplementedError(msg)

    def _load(self, ep: EntryPoint) -> T:
        msg = f"{type(self).__name__}._load must handle entry point {ep.name!r}"
        raise NotImplementedError(msg)

    @cached_property
    def _scanned(self) -> tuple[EntryPoint, ...]:
        """Loads the group's entry points once per discovery cache."""
        return tuple(entry_points(group=self.entry_point_group))

    @cached_property
    def _entry_points(self) -> dict[str, EntryPoint]:
        """Maps each entry-point name to the first entry point declaring it."""
        found: dict[str, EntryPoint] = {}

        for ep in self._scanned:
            found.setdefault(ep.name, ep)

        return found

    @cached_property
    def _collisions(self) -> dict[str, list[EntryPoint]]:
        """Groups the distinct entry points that share one name."""
        grouped: dict[str, list[EntryPoint]] = {}

        for ep in self._scanned:
            known = self._entry_points[ep.name]

            if known != ep:
                grouped.setdefault(ep.name, [known]).append(ep)

        return grouped

    def _require_unique(self, name: str) -> None:
        if name in self._collisions:
            dists = sorted(set(map(_get_dist_name, self._collisions[name])))
            msg = f"{self.label} entry point {name!r} is declared by more than one "
            raise ValueError(msg + f"plugin ({', '.join(dists)}); keep one")

    def _load_entry_point(self, name: str) -> T | None:
        """Loads the entry-point tier's entry for ``name`` once, if one declares it."""
        ep = self._entry_points.get(name)

        if name not in self._loaded and ep is not None:
            self._require_unique(name)
            loaded = self._load(ep)

            if (key := self._key(loaded)) != name:
                msg = f"entry point {name!r} declares a {self.label} named {key!r}; "
                raise ValueError(msg + "the two must match")

            self._loaded[name] = loaded

        return self._loaded.get(name)

    def _load_entry(self, name: str) -> T | None:
        """Loads the runtime entry for ``name``, else its entry-point entry."""
        entry = self._runtime.get(name)
        return self._load_entry_point(name) if entry is None else entry

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
        if not (name := self._key(entry)):
            raise ValueError(f"a runtime-registered {self.label} needs a name")

        if name in self._runtime and not replace:
            raise ValueError(f"{self.label} {name!r} is already registered")

        self._runtime[name] = entry

    @property
    def registered_names(self) -> tuple[str, ...]:
        """The sorted runtime-registered names."""
        return tuple(sorted(self._runtime))

    @property
    def discovered_names(self) -> tuple[str, ...]:
        """
        The sorted runtime-registered and entry-point names.

        Excludes built-ins since they are enumerated separately.

        """
        return tuple(sorted({*self._runtime, *self._entry_points}))

    def reset(self) -> None:
        """Drops runtime registrations and the entry-point discovery cache."""
        self._runtime.clear()
        self._loaded.clear()

        for cached in ("_scanned", "_entry_points", "_collisions"):
            self.__dict__.pop(cached, None)


__all__ = ["Registry"]
