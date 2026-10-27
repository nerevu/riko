from collections.abc import Callable, Iterable, Mapping
from typing import overload

@overload
def merge[V](records: Iterable[Mapping[str, V]]) -> dict[str, V]: ...
@overload
def merge(
    records: Iterable[Mapping[str, object]],
    *,
    pred: str | Callable[..., object],
    op: Callable[..., object],
    default: object = 0,
) -> dict[str, object]: ...
