from __future__ import annotations

from codecs import StreamReader
from collections.abc import (
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
)
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from tempfile import SpooledTemporaryFile
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
    Protocol,
    TypedDict,
    TypeVar,
    overload,
)

from riko.types.modules import ModuleSubtype, ModuleSubtypes, ModuleType
from riko.types.values import (
    AnyLocation,
    BasicArg,
    NumLike,
    PrimitiveValue,
    RikoDict,
    RikoList,
    RikoValue,
    RSSEntry,
    StatefulItem,
)

if TYPE_CHECKING:
    from riko._io import Fetch
    from riko.bado.io import NamedTextIOWrapper
    from riko.cast import BasicCastType
    from riko.context import Context
    from riko.dotdict import DotDict
    from riko.types.configs import DynamicConf
    from riko.types.modules import (
        AnyConfRule,
        AnyModuleConf,
        AnyModuleRawConf,
        CountValues,
        Skip,
        TargetLike,
    )

T = TypeVar("T")

# Values
type Item = RikoDict | dict[str, RikoValue] | RSSEntry | DotDict[RikoValue]
type ItemOrValue = Item | RikoValue
type Items = Iterable[Item]
type ItemsOrValues = Iterable[ItemOrValue]
type ValueStream = Iterator[RikoValue]
type Stream = Iterator[Item]
type StreamOrValueStream = Iterator[ItemOrValue]
type Streams = Iterator[Stream]

type AsyncItems = AsyncIterable[Item]
type AsyncItemsOrValues = AsyncIterable[ItemOrValue]
type AsyncStream = AsyncIterator[Item]
type AsyncStreamOrValueStream = AsyncIterator[ItemOrValue]

type Feed = AsyncItems
type AsyncSource = Items | Feed | Awaitable[Items | Feed]

type ProcessorParserOutput = Stream | ItemOrValue | AnyLocation | Iterator[str]
type OperatorParserOutput = Stream | ItemOrValue | Iterator[StatefulItem]
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
    ProcessorWrapperOutput | OperatorWrapperOutput | ItemOrValue
)
type OperatorWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type SplitterWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type WrapperInput = ProcessorWrapperInput | OperatorWrapperInput | SplitterWrapperInput

type PipeTuple = tuple[Item, DynamicConf]
type PipeTuples = Iterator[PipeTuple]
type Extraction = T
type ConversionFunc = Callable[..., Items | StringIO]
type Caster = Callable[[str | int], PrimitiveValue | AnyLocation]
type NumericCaster = Callable[[str | NumLike], NumLike]
type SkipFunc = Callable[[Item], bool]
type SkipIf = SkipFunc | Skip | Iterable[SkipFunc] | Iterable[Skip]
type Function = Callable[..., object]

# Opener = Callable[[str], tuple[Optional[str | Reencoder], Optional[str]]]
# TODO: add type hint overloads to Reencoder with decode=True -> str
type BinaryFileTypes = (
    BytesIO | RawIOBase | Fetch[Literal[True]] | SpooledTemporaryFile[bytes]
)
type StringFileTypes = (
    Fetch[Literal[False]]
    | NamedTextIOWrapper
    | SpooledTemporaryFile[str]
    | StreamReader
    | StringIO
    | TextIOBase
)
type FileTypes = BinaryFileTypes | StringFileTypes

type Opener = Callable[[str], tuple[FileTypes, str | None]]
type Conf = AnyModuleConf | AnyModuleRawConf


class PreCaster(TypedDict):
    default: PrimitiveValue | dict[str, str] | None
    func: Caster


class Defaults(TypedDict, total=False):
    col_names: list[str] | None
    combine: Literal["and", "or"]
    convert: bool
    count: int
    count_key: str | None
    currency: str  # TODO this should be an enum/literal
    dedupe: bool
    default: BasicArg
    delay: int
    delimiter: str
    encoding: str
    input_key: str
    format: str
    group_key: str | None
    has_header: bool
    join_key: str | None
    length: int
    limit: int
    lower: bool
    max_wait: int
    memoize: bool
    mode: str
    multi: bool
    name: str
    prompt: str
    param: dict[str, str | None]
    parse_key: str
    permit: bool
    precision: int
    pubDate: str
    quotechar: str
    rule: AnyConfRule
    sanitize: bool
    separator: str
    skip_rows: int
    sort: bool
    splits: int
    start: int
    stop: bool
    strict: bool
    sum_key: str
    target: TargetLike
    test: bool
    token_key: str
    type: str
    uniq_key: str
    url: str
    wait: int


class Opts(TypedDict, total=False):
    ftype: BasicCastType
    ptype: BasicCastType
    assign: str
    count: CountValues
    emit: bool
    extract: str
    field: str
    listize: bool
    objectify: bool
    parse: bool
    pollable: bool
    debug: bool
    skip_if: SkipIf


class Casted(NamedTuple):
    field: T
    extraction: Extraction
    conf: DynamicConf


class ItemDispatch(NamedTuple):
    item: Item | RikoDict
    casted: Casted


class ValueDispatch(NamedTuple):
    item: PrimitiveValue | RikoList
    casted: Casted


type ItemOrValueDispatch = ItemDispatch | ValueDispatch


# Sync
type SyncItemParseFunc = Callable[..., ItemOrValue]
type SyncArgFunc = Callable[..., ItemOrValue]
type SyncConfCastFunc = Callable[..., DynamicConf]
type SyncConfParseFunc = Callable[..., AnyModuleConf | None]

type SyncProcessorParser = Callable[[T, Extraction, DynamicConf], ProcessorParserOutput]
type SyncOperatorParser = Callable[
    [Stream, Extraction, PipeTuples], OperatorParserOutput
]
type SyncSplitterParser = Callable[
    [Stream, Extraction, PipeTuples], SplitterParserOutput
]

type SyncPipeParser = Callable[..., ParserOutput]
type SyncPipelineDependencies = Callable[..., list[str]]
type SyncStep = tuple[str, ParserOutput | SyncPipeParser]
type SyncSteps = dict[str, ParserOutput | SyncPipeParser]
type SyncPyInput = list[str | tuple[str, ...]]


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


class ParseFuncs(NamedTuple):
    field_parser: SyncItemParseFunc
    conf_parser: SyncConfParseFunc


class CastFuncs(NamedTuple):
    field_caster: SyncArgFunc
    extract_caster: SyncArgFunc
    conf_caster: SyncConfCastFunc


# Async
type AsyncProcessorParser = Callable[
    [T, Extraction, DynamicConf],
    ProcessorParserOutput | Awaitable[ProcessorParserOutput],
]
type AsyncOperatorParser = Callable[
    [Stream, Extraction, PipeTuples],
    OperatorParserOutput | Awaitable[OperatorParserOutput],
]
type AsyncSplitterParser = Callable[
    [Stream, Extraction, PipeTuples],
    SplitterParserOutput | Awaitable[SplitterParserOutput],
]
type AsyncPipeItems = Awaitable[ParserOutput]
type AsyncPipeParser = Callable[..., AsyncPipeItems]
type AsyncPipelineDependencies = Callable[..., Awaitable[list[str]]]
type AsyncStep = tuple[str, AsyncPipeItems | AsyncPipeParser]
type AsyncSteps = dict[str, AsyncPipeItems | AsyncPipeParser]
type AsyncPyInput = Awaitable[list[str]]


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
type Interface = Literal["pipe", "async_pipe"]
type ProcessorParser = SyncProcessorParser | AsyncProcessorParser
type ProcessorWrapper = SyncProcessorWrapper | AsyncProcessorWrapper
type SubPipe = SyncSubPipe | AsyncSubPipe
type OperatorParser = SyncOperatorParser | AsyncOperatorParser
type OperatorWrapper = SyncOperatorWrapper | AsyncOperatorWrapper
type SplitterParser = SyncSplitterParser | AsyncSplitterParser
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
type PipelineDependencies = SyncPipelineDependencies | AsyncPipelineDependencies
type StepValue = ParserOutput | Pipeline | AsyncPipeItems
type Step = tuple[str, StepValue]
type Steps = dict[str, StepValue]
type PyInput = SyncPyInput | AsyncPyInput


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
