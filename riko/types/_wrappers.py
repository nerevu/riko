from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Generator,
    Iterable,
    Iterator,
)
from io import StringIO
from typing import TYPE_CHECKING, Literal, NamedTuple, Protocol, TypedDict, overload

from riko.types._streams import AsyncStreamOrValueStream

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

# per-item pipe values
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

type ProcessorWrapperInput = (
    Items | ProcessorWrapperOutput | OperatorWrapperOutput | ItemOrValue
)
type OperatorWrapperInput = Items | ProcessorWrapperOutput | OperatorWrapperOutput
type SplitterWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type WrapperInput = ProcessorWrapperInput | OperatorWrapperInput | SplitterWrapperInput

type Caster[T] = Callable[[str | int], T]
type NumericCaster = Callable[[str | NumLike], NumLike]
type ArgCaster[T] = Callable[..., T]


class PreCaster[T](TypedDict):
    default: PrimitiveValue | dict[str, str] | None
    func: Caster[T]


type ConversionOutput = Iterable[str] | StringIO
type ConversionFunc = Callable[..., ConversionOutput]

# Sync
type SyncWrapperOutput = (
    ProcessorWrapperOutput | OperatorWrapperOutput | SplitterWrapperOutput
)
type SyncFieldParseFunc = Callable[..., ItemOrValue]
type SyncConfCastFunc = Callable[..., DynamicConf]
type SyncConfParseFunc = Callable[..., AnyModuleConf | None]

type SyncProcessorParser[T, E] = Callable[[T, E, DynamicConf], ProcessorParserOutput]
type SyncOperatorParser[E] = Callable[[Stream, E, PipeTuples], OperatorParserOutput]
type SyncSplitterParser[E] = Callable[[Stream, E, PipeTuples], SplitterParserOutput]

type SyncPipeParser = Callable[..., ParserOutput]
type SyncPipeWrapper = Callable[..., SyncWrapperOutput]


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
type AsyncProcessorWrapperOutput = AsyncStreamOrValueStream
type AsyncOperatorWrapperOutput = AsyncStreamOrValueStream
type AsyncSplitterWrapperOutput = AsyncIterator[Stream]
type AsyncWrapperOutput = (
    AsyncProcessorWrapperOutput
    | AsyncOperatorWrapperOutput
    | AsyncSplitterWrapperOutput
)

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
type AsyncPipeWrapper = Callable[..., AsyncWrapperOutput]


class AsyncWrapperStream[Y, A](Protocol):
    """
    Dual-protocol result of an async ``processor``/``splitter`` call.

    Async-iterating it consumes the parser's stream item by item (``Y``) with no
    outer await (the default ``async for item in async_pipe(...)`` path); awaiting it
    runs the parser and returns the whole stream (``A``, the advanced
    ``await async_pipe(...)`` path).
    """

    def __await__(self) -> Generator[object, None, A]: ...  # noqa: E704
    def __aiter__(self) -> AsyncIterator[Y]: ...  # noqa: E301, E704
    def __anext__(self) -> Awaitable[Y]: ...  # noqa: E301, E704


class AsyncProcessorWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        **__: object,
    ) -> AsyncWrapperStream[ItemOrValue, ProcessorWrapperOutput]:
        _ = (item, conf, context)
        raise NotImplementedError


class AsyncSubPipe(ModuleWrapper):
    def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> AsyncWrapperStream[ItemOrValue, ProcessorWrapperOutput]:
        raise NotImplementedError


async def _empty_async_stream() -> AsyncOperatorWrapperOutput:
    if False:
        yield


class AsyncOperatorWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: OperatorWrapperInput | Feed | None = None,
        conf: Conf | None = None,
        embed: AsyncProcessorWrapper | AsyncSubPipe | None = None,
        context: Context | None = None,
        **__: object,
    ) -> AsyncOperatorWrapperOutput:
        _ = (items, conf, embed, context)
        return _empty_async_stream()


class AsyncSplitterWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf | None = None,
        **__: object,
    ) -> AsyncWrapperStream[Stream, SplitterWrapperOutput]:
        _ = (items, conf)
        raise NotImplementedError


# Both
type WrapperOutput = SyncWrapperOutput | AsyncWrapperOutput
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
type SyncPipeCallable = SyncPipeWrapper | SyncModuleWrapper
type AsyncPipeCallable = AsyncPipeWrapper | AsyncModuleWrapper
type PipeCallable = SyncPipeCallable | AsyncPipeCallable
type Pipe = SyncPipeWrapper | AsyncPipeWrapper
type Pipeline = Pipe
type ModuleParser = ProcessorParser | OperatorParser | SplitterParser


class Resolver(Protocol):
    """
    Resolves a pipe name + interface to its callable — a ``ModuleRegistry``
    (leaf modules) or a ``PipelineResolver`` (``pipe`` sub-pipelines).
    """

    @overload
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncPipeWrapper: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncPipeWrapper: ...
    def resolve(  # noqa: E301, E704
        self, name: str, is_async: bool = False
    ) -> Pipe: ...
