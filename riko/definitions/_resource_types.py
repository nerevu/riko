"""Type aliases for resource definitions, bindings, and resolved values."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any

from riko.types._io import Closeable
from riko.types._resource import AnyContextManager, LifecycleFactory

if TYPE_CHECKING:
    from riko.runtime._resources import ReusableResource


type ReusableResources = Mapping[str, ReusableResource[Any]]
type ResourceDefinition[T] = ReusableResource[T] | LifecycleFactory[T]
type Resources = Mapping[str, ResourceDefinition[Any]]
type ResourcesLike = str | Iterable[str] | Mapping[str, str]
type Values = Mapping[str, Any | Closeable]
type ResolvedValue[T] = T | Closeable
type ResourceValue[T] = ResolvedValue | AnyContextManager[T]
