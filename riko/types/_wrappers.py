from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from io import StringIO
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol, TypedDict, overload

if TYPE_CHECKING:
    from riko.context import Context

    from ._dynamic_conf import DynamicConf
    from ._locations import AnyLocation
    from ._scalars import NumLike, PrimitiveValue
    from ._streams import (
        Feed,
        Item,
        ItemOrValue,
        Items,
        StatefulItem,
        Stream,
        StreamOrValueStream,
        Streams,
    )
    from .modules import AnyModuleConf, Conf, ModuleSubtype, ModuleSubtypes, ModuleType

# per-item pipeline values
type PipeTuple = tuple[Item, DynamicConf]
type PipeTuples = Iterator[PipeTuple]

# implementation interface
type Interface = Literal["pipe", "async_pipe"]

# Input/Output
type ProcessorParserOutput = Stream | ItemOrValue | AnyLocation | Iterator[str]
type OperatorParserOutput = StreamOrValueStream | ItemOrValue | Iterator[StatefulItem]
type SplitterParserOutput = Streams
type ParserOutput = ProcessorParserOutput | OperatorParserOutput | SplitterParserOutput
type ParserMaterializedOutput = list[StatefulItem | ItemOrValue | AnyLocation | Stream]

type ProcessorWrapperOutput = StreamOrValueStream
type OperatorWrapperOutput = StreamOrValueStream
type SplitterWrapperOutput = SplitterParserOutput
type WrapperOutput = (
    ProcessorWrapperOutput | OperatorWrapperOutput | SplitterWrapperOutput
)

type ProcessorWrapperInput = (
    Items | ProcessorWrapperOutput | OperatorWrapperOutput | ItemOrValue
)
type OperatorWrapperInput = Items | ProcessorWrapperOutput | OperatorWrapperOutput
type SplitterWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type WrapperInput = ProcessorWrapperInput | OperatorWrapperInput | SplitterWrapperInput

type Caster[T] = Callable[[str | int], T]
type NumericCaster = Callable[[str | NumLike], NumLike]
type ArgCaster[T] = Callable[..., T]


class PreCaster(TypedDict):
    default: PrimitiveValue | dict[str, str] | None
    func: Caster


type ConversionFunc = Callable[..., Items | StringIO]

# Sync
type SyncFieldParseFunc = Callable[..., ItemOrValue]
type SyncConfCastFunc = Callable[..., DynamicConf]
type SyncConfParseFunc = Callable[..., AnyModuleConf | None]

type SyncProcessorParser[T, E] = Callable[[T, E, DynamicConf], ProcessorParserOutput]
type SyncOperatorParser[E] = Callable[[Stream, E, PipeTuples], OperatorParserOutput]
type SyncSplitterParser[E] = Callable[[Stream, E, PipeTuples], SplitterParserOutput]

type SyncPipeParser = Callable[..., ParserOutput]


class ParseFuncs(NamedTuple):
    field_parser: SyncFieldParseFunc
    conf_parser: SyncConfParseFunc


class CastFuncs[T, E](NamedTuple):
    field_caster: ArgCaster[T]
    extract_caster: ArgCaster[E]
    conf_caster: SyncConfCastFunc


class ModuleWrapper(Protocol):
    name: str
    type: ModuleType
    subtype: ModuleSubtype
    subtypes: ModuleSubtypes
    pollable: bool
    loopable: bool
    isasync: bool


class SyncProcessorWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        **__: object,
    ) -> ProcessorWrapperOutput:
        _ = (item, conf, context)
        return iter(())


class SyncSubPipe(ModuleWrapper):
    def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> ProcessorWrapperOutput:
        return iter(())


class SyncOperatorWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: OperatorWrapperInput | None = None,
        conf: Conf | None = None,
        embed: SyncProcessorWrapper | SyncSubPipe | None = None,
        context: Context | None = None,
        **__: object,
    ) -> OperatorWrapperOutput:
        _ = (items, conf, embed, context)
        return iter(())


class SyncSplitterWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf | None = None,
        **__: object,
    ) -> SplitterWrapperOutput:
        _ = (items, conf)
        return iter(())


# Async
type AwaitableProcessorParser[T, E] = Callable[
    [T, E, DynamicConf], Awaitable[ProcessorParserOutput]
]
type AwaitableOperatorParser[E] = Callable[
    [Stream, E, PipeTuples], Awaitable[OperatorParserOutput]
]
type AwaitableSplitterParser[E] = Callable[
    [Stream, E, PipeTuples], Awaitable[SplitterParserOutput]
]

type AsyncProcessorParser[T, E] = (
    SyncProcessorParser[T, E] | AwaitableProcessorParser[T, E]
)
type AsyncOperatorParser[E] = SyncOperatorParser[E] | AwaitableOperatorParser[E]
type AsyncSplitterParser[E] = SyncSplitterParser[E] | AwaitableSplitterParser[E]

type AsyncPipeItems = Awaitable[ParserOutput]
type AsyncPipeParser = Callable[..., AsyncPipeItems]


class AsyncProcessorWrapper(ModuleWrapper):
    async def __call__(  # noqa: E704
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        **__: object,
    ) -> ProcessorWrapperOutput:
        _ = (item, conf, context)
        return iter(())


class AsyncSubPipe(ModuleWrapper):
    async def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> ProcessorWrapperOutput:
        return iter(())


class AsyncOperatorWrapper(ModuleWrapper):
    async def __call__(  # noqa: E704
        self,
        items: OperatorWrapperInput | Feed | None = None,
        conf: Conf | None = None,
        embed: AsyncProcessorWrapper | AsyncSubPipe | None = None,
        context: Context | None = None,
        **__: object,
    ) -> OperatorWrapperOutput:
        _ = (items, conf, embed, context)
        return iter(())


class AsyncSplitterWrapper(ModuleWrapper):
    async def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf | None = None,
        **__: object,
    ) -> SplitterWrapperOutput:
        _ = (items, conf)
        return iter(())


# Both
type SubPipe = SyncSubPipe | AsyncSubPipe
type ProcessorParser[T, E] = SyncProcessorParser[T, E] | AsyncProcessorParser[T, E]
type ProcessorWrapper = SyncProcessorWrapper | AsyncProcessorWrapper
type OperatorParser[E] = SyncOperatorParser[E] | AsyncOperatorParser[E]
type OperatorWrapper = SyncOperatorWrapper | AsyncOperatorWrapper
type SplitterParser[E] = SyncSplitterParser[E] | AsyncSplitterParser[E]
type SplitterWrapper = SyncSplitterWrapper | AsyncSplitterWrapper
type SyncModuleWrapper = (
    SyncProcessorWrapper | SyncOperatorWrapper | SyncSplitterWrapper
)
type AsyncModuleWrapper = (
    AsyncProcessorWrapper | AsyncOperatorWrapper | AsyncSplitterWrapper
)
type SyncPipeCallable = SyncPipeParser | SyncModuleWrapper
type AsyncPipeCallable = AsyncPipeParser | AsyncModuleWrapper
type Pipeline = SyncPipeParser | AsyncPipeParser
type ModuleParser = ProcessorParser | OperatorParser | SplitterParser


class Resolver(Protocol):
    """
    Resolves a pipe name + interface to its callable — a ``ModuleRegistry``
    (leaf modules) or a ``PipelineResolver`` (``pipe`` sub-pipelines).
    """

    @overload
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["pipe"]
    ) -> SyncPipeParser: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, interface: Literal["async_pipe"]
    ) -> AsyncPipeParser: ...
    def resolve(  # noqa: E301, E704
        self, name: str, interface: Interface
    ) -> Pipeline: ...
