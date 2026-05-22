
from typing import Any, Callable, Iterable, Iterator, NamedTuple, TypeAlias, TYPE_CHECKING

from meza.fntools import Objectify
from twisted.internet.defer import Deferred

if TYPE_CHECKING:
    from riko.dotdict import DotDict

Item: TypeAlias = dict[str, Any]
ItemFunc: TypeAlias = Callable[[Item], Any | Objectify]


class BroadcastFuncs(NamedTuple):
    field_func: ItemFunc
    conf_func: ItemFunc


class DispatchFuncs(NamedTuple):
    field_dispatch: ItemFunc
    conf_dispatch: ItemFunc


PipeDef: TypeAlias = dict[str, Any]
ParsedPipeDef: TypeAlias = dict[str, Any]
PipeTuple: TypeAlias = tuple[Item, Any]
PipeTuples: TypeAlias = Iterator[PipeTuple]
Items: TypeAlias = list[Item]
Stream: TypeAlias = Iterator[Item] | Callable[..., Iterator[Item]]

SyncProcessor: TypeAlias = Callable[[str, "DotDict"], Stream | "DotDict"]
AsyncProcessor: TypeAlias = Callable[[str, "DotDict"], Deferred[Stream | "DotDict"]]
Processor: TypeAlias = SyncProcessor | AsyncProcessor

SyncOperator: TypeAlias = Callable[[Stream, "DotDict", PipeTuples], Stream]
AsyncOperator: TypeAlias = Callable[[Stream, "DotDict", PipeTuples], Deferred[Stream]]
Operator: TypeAlias = SyncOperator | AsyncOperator

SyncPipeline: TypeAlias = Callable[..., Stream]
AsyncPipeline: TypeAlias = Callable[..., Deferred[Stream]]
Pipeline: TypeAlias = SyncPipeline | AsyncPipeline

PipelineDependencies: TypeAlias = Callable[..., list[str]]
Step: TypeAlias = tuple[str, Stream | SyncPipeline]
Steps: TypeAlias = dict[str, Stream | SyncPipeline]
