"""Parser, wrapper, conversion, and decorator typing contracts."""

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

from ._options import ItemDispatch, Opts
from ._streams import AsyncItems, AsyncStream, ItemOrValue, ItemValue, Stream

if TYPE_CHECKING:
    from riko.coercion._dynamic_conf import DynamicConf
    from riko.runtime.context import Context

    from ._scalars import NumLike, PrimitiveValue
    from ._streams import Cascade, Feed, Item, Items
    from .modules import AnyModuleConf, Conf, ModuleSubtype, ModuleSubtypes, ModuleType

# per-item pipe values
type PipeTuple = tuple[Item, DynamicConf]
type SyncPipeTuples = Iterator[PipeTuple]
type AsyncPipeTuples = AsyncIterator[PipeTuple]
type PipeTuples = SyncPipeTuples | AsyncPipeTuples

# implementation interface
type Interface = Literal["pipe", "async_pipe"]

# Input/Output
type ProcessorParserOutput[O: ItemOrValue] = O | Iterator[O]
type OperatorParserOutput[T: ItemOrValue] = T | Iterator[T] | Stream
type SplitterParserOutput = Cascade
type ParserOutput[T: ItemOrValue] = (
    ProcessorParserOutput[T] | OperatorParserOutput[T] | SplitterParserOutput
)
type ParserMaterializedOutput = list[ItemOrValue]

type SyncProcessorWrapperOutput = Stream
type SyncProcessorWrapperInternalOutput = Iterator[ItemOrValue]
type SyncOperatorWrapperOutput = Stream
type SyncOperatorWrapperInternalOutput = Iterator[ItemOrValue]
type SyncSplitterWrapperOutput = Cascade

type ProcessorWrapperInput = (
    Items | SyncProcessorWrapperOutput | SyncOperatorWrapperOutput | ItemOrValue
)
type SplitterWrapperInput = SyncProcessorWrapperOutput | SyncOperatorWrapperOutput
type WrapperInput = (
    ProcessorWrapperInput | SyncOperatorWrapperInput | SplitterWrapperInput
)

type Caster[T] = Callable[[str | int], T]
type NumericCaster = Callable[[str | NumLike], NumLike]
type ArgCaster[T] = Callable[..., T]


class PreCaster[T](TypedDict):
    default: PrimitiveValue | dict[str, str] | None
    func: Caster[T]


type Dispatcher[T, E] = Callable[[Item, Opts], ItemDispatch[T, E]]

type ConversionOutput = Iterable[str] | StringIO
type ConversionFunc = Callable[..., ConversionOutput]

# Sync
type SyncOperatorWrapperInput = (
    Items | SyncProcessorWrapperOutput | SyncOperatorWrapperOutput
)
type SyncWrapperOutput = SyncProcessorWrapperOutput | SyncOperatorWrapperOutput
type SyncFieldParseFunc = Callable[..., ItemValue]
type SyncConfCastFunc = Callable[..., DynamicConf]
type SyncConfParseFunc = Callable[..., AnyModuleConf | None]
type SyncProcessorParser[I, E, O: ItemOrValue] = Callable[
    [I, E, DynamicConf], ProcessorParserOutput[O]
]
type SyncOperatorParser[T: ItemOrValue, E] = Callable[
    [Stream, E, SyncPipeTuples], OperatorParserOutput[T]
]
type SyncSplitterParser[E] = Callable[[Stream, E, SyncPipeTuples], SplitterParserOutput]
type SyncPipeParser[T: ItemOrValue] = Callable[..., ParserOutput[T]]
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


class SyncSubPipe(ModuleWrapper):
    def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> SyncProcessorWrapperOutput:
        return iter(())


class SyncProcessorWrapper(ModuleWrapper):
    def __call__(  # noqa: E301
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> SyncProcessorWrapperOutput:
        _ = (item, conf, context, emit)
        return iter(())


class SyncOperatorWrapper(ModuleWrapper):
    def __call__(  # noqa: E301
        self,
        items: SyncOperatorWrapperInput | None = None,
        conf: Conf | None = None,
        embed: SyncProcessorWrapper | SyncSubPipe | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> SyncOperatorWrapperOutput:
        _ = (items, conf, embed, context, emit)
        return iter(())


class SyncSplitterWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf | None = None,
        **__: object,
    ) -> SyncSplitterWrapperOutput:
        _ = (items, conf)
        return iter(())


type SyncModuleWrapper = (
    SyncProcessorWrapper | SyncOperatorWrapper | SyncSplitterWrapper
)
type SyncPipeCallable = SyncPipeWrapper | SyncModuleWrapper


# Async
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


type AsyncSplitterWrapperOutput = AsyncWrapperStream[Stream, SyncSplitterWrapperOutput]
type AsyncProcessorWrapperOutput = AsyncWrapperStream[Item, SyncProcessorWrapperOutput]
type AsyncOperatorWrapperOutput = AsyncStream
type AsyncOperatorWrapperInternalOutput = AsyncIterator[ItemOrValue]
type AsyncOperatorWrapperInput = AsyncItems | SyncOperatorWrapperInput
type AsyncWrapperOutput = AsyncProcessorWrapperOutput | AsyncOperatorWrapperOutput
type AwaitableProcessorParser[I, E, O: ItemOrValue] = Callable[
    [I, E, DynamicConf], Awaitable[ProcessorParserOutput[O]]
]
type AwaitableOperatorParser[T: ItemOrValue, E] = Callable[
    [Feed, E, PipeTuples], Awaitable[OperatorParserOutput[T]]
]
type AwaitableSplitterParser[E] = Callable[
    [Stream, E, SyncPipeTuples], Awaitable[SplitterParserOutput]
]
type AsyncProcessorParser[I, E, O: ItemOrValue] = (
    SyncProcessorParser[I, E, O] | AwaitableProcessorParser[I, E, O]
)
type AsyncOperatorParser[T: ItemOrValue, E] = (
    SyncOperatorParser[T, E] | AwaitableOperatorParser[T, E]
)
type AsyncSplitterParser[E] = SyncSplitterParser[E] | AwaitableSplitterParser[E]
type AwaitableParserOutput[T: ItemOrValue] = Awaitable[ParserOutput[T]]
type AsyncPipeParser[T: ItemOrValue] = Callable[..., AwaitableParserOutput[T]]
type AsyncPipeWrapper = Callable[..., AsyncWrapperOutput]


class AsyncProcessorWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> AsyncProcessorWrapperOutput:
        _ = (item, conf, context)
        raise NotImplementedError


class AsyncSubPipe(ModuleWrapper):
    def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> AsyncProcessorWrapperOutput:
        raise NotImplementedError


class AsyncOperatorWrapper(ModuleWrapper):
    def __call__(  # noqa: E301
        self,
        items: AsyncOperatorWrapperInput | None = None,
        conf: Conf | None = None,
        embed: AsyncProcessorWrapper | AsyncSubPipe | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> AsyncOperatorWrapperOutput:
        _ = (items, conf, embed, context, emit)
        raise NotImplementedError


class AsyncSplitterWrapper(ModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf | None = None,
        **__: object,
    ) -> AsyncSplitterWrapperOutput:
        _ = (items, conf)
        raise NotImplementedError


type AsyncModuleWrapper = (
    AsyncProcessorWrapper | AsyncOperatorWrapper | AsyncSplitterWrapper
)
type AsyncPipeCallable = AsyncPipeWrapper | AsyncModuleWrapper

# Both
type WrapperOutput = SyncWrapperOutput | AsyncWrapperOutput
type SubPipe = SyncSubPipe | AsyncSubPipe
type ProcessorParser[I, E, O: ItemOrValue] = (
    SyncProcessorParser[I, E, O] | AsyncProcessorParser[I, E, O]
)
type ProcessorWrapper = SyncProcessorWrapper | AsyncProcessorWrapper
type OperatorParser[T: ItemOrValue, E] = (
    SyncOperatorParser[T, E] | AsyncOperatorParser[T, E]
)
type OperatorWrapper = SyncOperatorWrapper | AsyncOperatorWrapper
type SplitterParser[E] = SyncSplitterParser[E] | AsyncSplitterParser[E]
type SplitterWrapper = SyncSplitterWrapper | AsyncSplitterWrapper
type PipeCallable = SyncPipeCallable | AsyncPipeCallable
type Pipe = SyncPipeWrapper | AsyncPipeWrapper
type Pipeline = Pipe
type ModuleParser = ProcessorParser | OperatorParser | SplitterParser


class Resolver(Protocol):
    """
    Resolve a pipe name and interface to its callable.

    Leaf modules use ``ModuleRegistry``; ``pipe`` sub-pipelines use
    ``PipelineResolver``.
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
