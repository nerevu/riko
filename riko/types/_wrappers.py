"""Parser, wrapper, conversion, and decorator typing contracts."""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Iterable,
    Iterator,
)
from io import StringIO
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    NamedTuple,
    Protocol,
    TypedDict,
    TypeGuard,
    Unpack,
    overload,
)

from typing_extensions import TypeIs

from riko.base._config import SUBPIPE_TYPE
from riko.base._exceptions import InvalidPipelineError

from ._options import DecorationOptions, ItemDispatch
from ._streams import (
    AsyncItems,
    AsyncStream,
    ItemOrValue,
    ItemsOrValues,
    ItemValue,
    Stream,
)

if TYPE_CHECKING:
    from riko.coercion._dynamic_conf import DynamicConf
    from riko.definitions._context import Context

    from ._options import RawCallOptions
    from ._scalars import NumLike, PrimitiveValue
    from ._streams import Cascade, Feed, Item, Items
    from .modules import (
        AnyModuleConf,
        Conf,
        MaybeFrozenConf,
        ModuleSubtype,
        ModuleSubtypes,
        ModuleType,
    )

# per-item pipe values
type PipeTuple = tuple[Item, DynamicConf]
type SyncPipeTuples = Iterator[PipeTuple]
type AsyncPipeTuples = AsyncIterator[PipeTuple]
type PipeTuples = SyncPipeTuples | AsyncPipeTuples

# implementation interface
type Interface = Literal["pipe", "async_pipe"]

# Input/Output
type Func[T] = Callable[..., T]
type AsyncFunc[T] = Callable[..., Awaitable[T]]
type CoroutineFunc = Callable[..., Coroutine[object, object, object]]
type ProcessorParserOutput[O: ItemOrValue] = O | Iterator[O]
type OperatorParserOutput[T: ItemOrValue] = T | Iterator[T] | Stream
type SplitterParserOutput = Cascade
type ParserOutput[T: ItemOrValue] = (
    ProcessorParserOutput[T] | OperatorParserOutput[T] | SplitterParserOutput
)
type ParserMaterializedOutput = list[ItemOrValue]
type Caster[T] = Callable[[str | int], T]
type NumericCaster = Callable[[str | NumLike], NumLike]
type ArgCaster[T] = Callable[..., T]


class PreCaster[T](TypedDict):
    default: PrimitiveValue | dict[str, str] | None
    func: Caster[T]


type ItemDispatcher[T, E] = Callable[[Item, DecorationOptions], ItemDispatch[T, E]]
type ConversionOutput = Iterable[str] | StringIO
type ConversionFunc = Callable[..., ConversionOutput]

# Sync
type SyncOperatorWrapperOutput = Stream
type SyncOperatorWrapperInternalOutput = Iterator[ItemOrValue]
type SyncOperatorWrapperInput = (
    Items | SyncProcessorWrapperOutput | SyncOperatorWrapperOutput
)
type SyncProcessorWrapperOutput = Stream
type SyncProcessorWrapperInternalOutput = Iterator[ItemOrValue]
type SyncProcessorWrapperInput = ItemOrValue | ItemsOrValues

type SyncSplitterWrapperOutput = Cascade
type SyncSplitterWrapperInput = SyncProcessorWrapperOutput | SyncOperatorWrapperOutput

type SyncWrapperOutput = SyncProcessorWrapperOutput | SyncOperatorWrapperOutput
type SyncConfCastFunc = Callable[..., DynamicConf]


class SyncProcessorParser[I, E, O: ItemOrValue](Protocol):
    """
    Parses one item's field, extraction, and configuration.

    Its ``**kwargs`` receives the remaining keyword arguments (``inputs``, ``count``,
    ``test``).
    """

    def __call__(  # noqa: E704
        self, item: I, extraction: E, objconf: DynamicConf, /, **kwargs: Any
    ) -> ProcessorParserOutput[O]: ...


class SyncOperatorParser[T: ItemOrValue, E](Protocol):
    """
    Parses a whole stream with its extraction and per-item tuples.

    Its ``**kwargs`` receives the remaining keyword arguments (``inputs``, ``count``).
    """

    def __call__(  # noqa: E704
        self, stream: Stream, extraction: E, tuples: SyncPipeTuples, /, **kwargs: Any
    ) -> OperatorParserOutput[T]: ...


class SyncSplitterParser[E](Protocol):
    """
    Splits a whole stream into branches.

    Its ``**kwargs`` receives the remaining keyword arguments.
    """

    def __call__(  # noqa: E704
        self, stream: Stream, extraction: E, tuples: SyncPipeTuples, /, **kwargs: Any
    ) -> SplitterParserOutput: ...


type SyncWrapperInput = (
    SyncProcessorWrapperInput | SyncOperatorWrapperInput | SyncSplitterWrapperInput
)


class SyncFieldParseFunc(Protocol):
    """Reads a module's configured field from one item."""

    def __call__(self, item: ItemOrValue, /, **kwargs: Any) -> ItemValue: ...  # noqa: E704


class SyncConfParseFunc(Protocol):
    """Resolves a module's prepared configuration against one item."""

    def __call__(  # noqa: E704
        self, item: ItemOrValue, /, **kwargs: Any
    ) -> AnyModuleConf | None: ...


class ParseFuncs(NamedTuple):
    field_parser: SyncFieldParseFunc
    conf_parser: SyncConfParseFunc


class CastFuncs[T, E](NamedTuple):
    field_caster: ArgCaster[T]
    extract_caster: ArgCaster[E]
    conf_caster: SyncConfCastFunc


# A keyword argument name each item call supplies, which a configuration's
# ``terminal`` reference may name.
type ExtraName = str
type ExtraNames = tuple[ExtraName, ...]
type PrepareConf = MaybeFrozenConf | DynamicConf


class PreparedCall(Protocol):
    """
    A module call with its configuration and call options already applied.

    It is called once per item, or once per stream for a module that takes a
    whole stream. Each call supplies the ``context`` and any secondary input
    streams, resources, or embed.
    """

    def __call__(  # noqa: E704
        self, item: Any = None, *, context: Context | None = None, **extra: object
    ) -> WrapperOutput | SplitterWrapperOutput: ...


class Preparer(Protocol):
    """
    Prepares a call's configuration and call options once for reuse over many items.

    Every module wrapper carries one as its ``prepare``. The ``context`` and any
    secondary input streams, resources, or embed are supplied with each item call
    rather than fixed here.
    """

    def __call__(  # noqa: E704
        self,
        *extras: ExtraName,
        conf: PrepareConf | None = None,
        **options: Unpack[RawCallOptions],
    ) -> PreparedCall: ...


class WrapperMeta(Protocol):
    """A callable stamped with the discovery metadata every module wrapper carries."""

    __name__: str
    __qualname__: str

    def __call__(  # noqa: E301, E704
        self, *args: Any, **kwargs: Any
    ) -> WrapperOutput | SplitterWrapperOutput: ...

    name: str
    type: ModuleType
    subtype: ModuleSubtype
    subtypes: ModuleSubtypes
    pollable: bool
    loopable: bool
    isasync: bool
    sequential_inputs: bool


class ModuleWrapper(WrapperMeta, Protocol):
    """A module wrapper: the discovery metadata plus a ``prepare`` for its calls."""

    prepare: Preparer


WRAPPER_META: tuple[str, ...] = (
    "name",
    "type",
    "subtype",
    "subtypes",
    "pollable",
    "loopable",
    "isasync",
)


def is_wrapper_meta(value: object) -> TypeIs[WrapperMeta]:
    """
    Reports whether ``value`` is callable and carries every ``WRAPPER_META`` attribute.

    Args:

        value: The object to check.

    Returns:

        Whether ``value`` is a callable carrying the wrapper metadata.

    Examples:

        >>> from riko.modules.hash import pipe
        >>>
        >>> is_wrapper_meta(pipe), is_wrapper_meta(len)
        (True, False)

    """
    return callable(value) and all(hasattr(value, attr) for attr in WRAPPER_META)


def require_wrapper_meta(value: object, what: str | None = "pipe", **_) -> WrapperMeta:
    """
    Requires ``value`` to be a callable carrying every ``WRAPPER_META`` attribute.

    Args:

        value: The object to check.
        what: How to name ``value`` in the error.

    Returns:

        ``value``, narrowed to the wrapper metadata it carries.

    Raises:

        TypeError: If ``value`` lacks the wrapper metadata a module decorator stamps.

    Examples:

        >>> from riko.modules.hash import pipe
        >>>
        >>> require_wrapper_meta(pipe).name
        'hash'
        >>> require_wrapper_meta(len, "example.pipe")
        Traceback (most recent call last):
            ...
        TypeError: example.pipe has no module metadata...

    """
    if not is_wrapper_meta(value):
        msg = f"{what} has no module metadata; decorate it with a module decorator"
        raise TypeError(msg)

    return value


class SyncModuleWrapper(ModuleWrapper, Protocol):
    isasync = False

    def __call__(  # noqa: E301, E704
        self, *args: Any, **kwargs: Any
    ) -> SyncWrapperOutput | SyncSplitterWrapperOutput: ...


class SyncSubPipe(SyncModuleWrapper):
    def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> SyncProcessorWrapperOutput:
        return iter(())


class SyncProcessorWrapper(SyncModuleWrapper):
    def __call__(  # noqa: E301
        self,
        item: SyncProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> SyncProcessorWrapperOutput:
        _ = (item, conf, context, emit)
        return iter(())


class SyncOperatorWrapper(SyncModuleWrapper):
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


class SyncSplitterWrapper(SyncModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: SyncSplitterWrapperInput | None = None,
        conf: Conf | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> SyncSplitterWrapperOutput:
        _ = (items, conf)
        return iter(())


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


type AsyncOperatorWrapperOutput = AsyncStream
type AsyncOperatorWrapperInternalOutput = AsyncIterator[ItemOrValue]
type AsyncOperatorWrapperInput = AsyncItems | SyncOperatorWrapperInput

type AsyncProcessorWrapperOutput = AsyncWrapperStream[Item, SyncProcessorWrapperOutput]
type AsyncProcessorWrapperInternalOutput = (
    SyncProcessorWrapperInternalOutput | AsyncIterator[ItemOrValue]
)
type AsyncProcessorWrapperInput = SyncProcessorWrapperInput

type AsyncSplitterWrapperOutput = AsyncWrapperStream[Stream, SyncSplitterWrapperOutput]
type AsyncSplitterWrapperInput = SyncSplitterWrapperInput

type AsyncWrapperOutput = AsyncProcessorWrapperOutput | AsyncOperatorWrapperOutput
type AsyncModuleWrapperOutput[T] = (
    AsyncWrapperStream[T, Iterator[T]]
    | AsyncWrapperStream[Iterator[T], Iterator[Iterator[T]]]
)


class AwaitableProcessorParser[I, E, O: ItemOrValue](Protocol):
    """
    Parses one item's field, extraction, and configuration asynchronously.

    Its ``**kwargs`` receives the remaining keyword arguments (``inputs``, ``count``,
    ``test``).
    """

    def __call__(  # noqa: E704
        self, item: I, extraction: E, objconf: DynamicConf, /, **kwargs: Any
    ) -> Awaitable[ProcessorParserOutput[O]]: ...


class AwaitableOperatorParser[T: ItemOrValue, E](Protocol):
    """
    Parses a whole sync or async stream asynchronously.

    Its ``**kwargs`` receives the remaining keyword arguments (``inputs``, ``count``).
    """

    def __call__(  # noqa: E704
        self, stream: Feed, extraction: E, tuples: PipeTuples, /, **kwargs: Any
    ) -> Awaitable[OperatorParserOutput[T]]: ...


class AwaitableSplitterParser[E](Protocol):
    """
    Splits a whole stream into branches asynchronously.

    Its ``**kwargs`` receives the remaining keyword arguments.
    """

    def __call__(  # noqa: E704
        self, stream: Stream, extraction: E, tuples: SyncPipeTuples, /, **kwargs: Any
    ) -> Awaitable[SplitterParserOutput]: ...


type AsyncProcessorParser[I, E, O: ItemOrValue] = (
    SyncProcessorParser[I, E, O] | AwaitableProcessorParser[I, E, O]
)
type AsyncOperatorParser[T: ItemOrValue, E] = (
    SyncOperatorParser[T, E] | AwaitableOperatorParser[T, E]
)
type AsyncSplitterParser[E] = SyncSplitterParser[E] | AwaitableSplitterParser[E]


class AsyncModuleWrapper(ModuleWrapper, Protocol):
    isasync = True

    def __call__(  # noqa: E301, E704
        self, *args: Any, **kwargs: Any
    ) -> AsyncWrapperOutput | AsyncSplitterWrapperOutput: ...


class AsyncProcessorWrapper(AsyncModuleWrapper):
    def __call__(  # noqa: E704
        self,
        item: AsyncProcessorWrapperInput | None = None,
        conf: Conf | DynamicConf | None = None,
        context: Context | None = None,
        *,
        emit: bool = False,
        **__: object,
    ) -> AsyncProcessorWrapperOutput:
        _ = (item, conf, context)
        raise NotImplementedError


class AsyncSubPipe(AsyncModuleWrapper):
    def __call__(  # noqa: E704
        self, *_: object, **__: object
    ) -> AsyncProcessorWrapperOutput:
        raise NotImplementedError


class AsyncOperatorWrapper(AsyncModuleWrapper):
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


class AsyncSplitterWrapper(AsyncModuleWrapper):
    def __call__(  # noqa: E704
        self,
        items: AsyncSplitterWrapperInput | None = None,
        conf: Conf | None = None,
        **__: object,
    ) -> AsyncSplitterWrapperOutput:
        _ = (items, conf)
        raise NotImplementedError


# Both
type WrapperOutput = SyncWrapperOutput | AsyncWrapperOutput

type OperatorParser[T: ItemOrValue, E] = (
    SyncOperatorParser[T, E] | AsyncOperatorParser[T, E]
)
type OperatorWrapper = SyncOperatorWrapper | AsyncOperatorWrapper

type ProcessorParser[I, E, O: ItemOrValue] = (
    SyncProcessorParser[I, E, O] | AsyncProcessorParser[I, E, O]
)
type ProcessorWrapper = SyncProcessorWrapper | AsyncProcessorWrapper
type ProcessorWrapperInput = SyncProcessorWrapperInput | AsyncProcessorWrapperInput

type SplitterParser[E] = SyncSplitterParser[E] | AsyncSplitterParser[E]
type SplitterWrapper = SyncSplitterWrapper | AsyncSplitterWrapper
type SplitterWrapperOutput = SyncSplitterWrapperOutput | AsyncSplitterWrapperOutput
type SplitterWrapperInput = SyncSplitterWrapperInput | AsyncSplitterWrapperInput

type SubPipe = SyncSubPipe | AsyncSubPipe
type AnyModuleWrapper = SyncModuleWrapper | AsyncModuleWrapper
type ModuleParser = ProcessorParser | OperatorParser | SplitterParser


def is_subpipe[T: SubPipe](val: T | ModuleWrapper) -> TypeGuard[T]:
    return callable(val) and getattr(val, "type", None) == SUBPIPE_TYPE


def is_splitter(pipe: ModuleWrapper) -> TypeIs[SplitterWrapper]:
    """
    Reports whether ``pipe`` was decorated as a multi-output splitter.

    The check reads the module kind stamped on the wrapper at decoration, not
    the shape of anything the pipe yields.

    Args:

        pipe: A resolved pipe wrapper.

    Returns:

        ``True`` when the pipe yields a stream of streams.

    Examples:

        >>> from riko.modules.count import pipe as count
        >>> from riko.modules.split import pipe as split
        >>> is_splitter(split), is_splitter(count)
        (True, False)

    """
    return getattr(pipe, "type", None) == "splitter"


def require_single_output(
    value: ModuleWrapper, what: str | None = "pipe", **_
) -> ModuleWrapper:
    """
    Rejects a multi-output splitter until port-keyed fan-out delivery is executable.

    Args:

        value: A resolved pipe wrapper.
        what: How to name the pipe's holder in the error.

    Returns:

        ``value`` unchanged.

    Raises:

        InvalidPipelineError: If ``value`` is a splitter.

    """
    if is_splitter(value):
        msg = f"{what} contains splitter: {value.name!r}. These are not yet executable."
        raise InvalidPipelineError(msg)

    return value


class Resolver(Protocol):
    """
    Resolves a module name or ``pipe_<id>`` name to its pipe callable and interfaces.

    Modules such as ``fetch`` use ``ModuleRegistry``. Stored workflows
    (``WorkflowStore`` entries looked up by their ``pipe_<id>`` name) use
    ``WorkflowResolver``.
    """

    @overload
    def require(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper: ...
    @overload  # noqa: E301
    def require(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper: ...
    def require(  # noqa: E301, E704
        self, name: str, is_async: bool = False
    ) -> ModuleWrapper: ...

    def is_compatible(self, name: str) -> bool: ...  # noqa: E704
    def require_interfaces(self, name: str) -> frozenset[Interface]: ...  # noqa: E704


class Dispatcher(Protocol):
    """
    Finds a module's or stored workflow's pipe by name for execution planning.

    Names are module names such as ``fetch`` or stored workflows' ``pipe_<id>``
    names.
    """

    def validate(self, name: str) -> None: ...  # noqa: E704

    @overload
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[False] = ...
    ) -> SyncModuleWrapper | None: ...
    @overload  # noqa: E301
    def resolve(  # noqa: E704
        self, name: str, is_async: Literal[True]
    ) -> AsyncModuleWrapper | None: ...
    def resolve(  # noqa: E301, E704
        self, name: str, is_async: bool = False
    ) -> ModuleWrapper | None: ...
