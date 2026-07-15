from codecs import StreamReader
from collections.abc import Awaitable, Callable, Iterable, Iterator, Sequence
from io import BytesIO, RawIOBase, StringIO, TextIOBase
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
    Optional,
    Protocol,
    TypedDict,
    TypeVar,
)

from riko.types.values import (
    AnyLocation,
    BasicArg,
    NumLike,
    PrimitiveValue,
    RikoDict,
    RikoValue,
    RSSEntry,
    StatefulItem,
)

if TYPE_CHECKING:
    from riko import Context, DotDict, Objconf
    from riko.bado.io import NamedTextIOWrapper
    from riko.cast import BasicCastType
    from riko.types.modules import AnyConfRule, AnyModuleConf, AnyModuleRawConf, Skip
    from riko.utils import Fetch

T = TypeVar("T")

# Values
type Item = RikoDict | dict[str, RikoValue] | RSSEntry | DotDict[RikoValue]
type ItemOrValue = Item | RikoValue
type Items = Iterable[Item]
type ValueStream = Iterator[RikoValue]
type Stream = Iterator[Item]
type StreamOrValueStream = Iterator[ItemOrValue]
type Streams = Iterator[Stream]

type ProcessorParserOutput = Stream | ItemOrValue | AnyLocation | Iterator[str]
type OperatorParserOutput = Stream | ItemOrValue | Iterator[StatefulItem]
type SplitterParserOutput = Streams
type ParserOutput = ProcessorParserOutput | OperatorParserOutput | SyncSplitterParser

type ProcessorWrapperOutput = StreamOrValueStream
type OperatorWrapperOutput = StreamOrValueStream
type SplitterWrapperOutput = SplitterParserOutput
type WrapperOutput = (
    ProcessorWrapperOutput | OperatorWrapperOutput | SplitterWrapperOutput
)

type ProcessorWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type OperatorWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type SplitterWrapperInput = ProcessorWrapperOutput | OperatorWrapperOutput
type WrapperInput = ProcessorWrapperInput | OperatorWrapperInput | SplitterWrapperInput

type PipeTuple = tuple[Item, "Objconf"]
type PipeTuples = Iterator[PipeTuple]
type Objconfs = Sequence["Objconf"]
type Extraction = T
type ConversionFunc = Callable[..., Items | StringIO]
type Caster = Callable[[str | int], PrimitiveValue | AnyLocation]
type NumericCaster = Callable[[str | NumLike], NumLike]
type SkipFunc = Callable[[Item], bool]
type SkipIf = SkipFunc | "Skip" | Iterable[SkipFunc] | Iterable["Skip"]

# Opener = Callable[[str], tuple[Optional[str | Reencoder], Optional[str]]]
# TODO: add type hint overloads to Reencoder with decode=True -> str
type BinaryFileTypes = BytesIO | RawIOBase
type StringFileTypes = StringIO | StreamReader | TextIOBase | "NamedTextIOWrapper"
type FileTypes = BinaryFileTypes | StringFileTypes | "Fetch"
type Opener = Callable[[str], tuple[FileTypes, str | None]]
type Conf = "AnyModuleConf" | "AnyModuleRawConf" | None


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
    multi: bool
    name: str
    param: dict[str, str | None]
    parse_key: str
    permit: bool
    precision: int
    pubDate: str
    quotechar: str
    rule: "AnyConfRule"
    sanitize: bool
    separator: str
    skip_rows: int
    sort: bool
    splits: int
    start: int
    strict: bool
    sum_key: str
    test: bool
    token_key: str
    type: str
    uniq_key: str
    url: str
    wait: int


class Opts(TypedDict, total=False):
    ftype: "BasicCastType"
    ptype: "BasicCastType"
    assign: str
    count: Literal["first", "all"]
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
    conf: Conf


class Dispatched(NamedTuple):
    item: "DotDict"
    casted: Casted


# Sync
type SyncItemParseFunc = Callable[..., ItemOrValue]
type SyncArgFunc = Callable[..., ItemOrValue]
type SyncConfCastFunc = Callable[..., Conf]
type SyncConfParseFunc = Callable[..., Conf | dict[str, Conf] | list[Conf] | None]

type SyncProcessorParser = Callable[[T, Extraction, Conf], ProcessorParserOutput]
type SyncOperatorParser = Callable[
    [Stream, Extraction, PipeTuples], OperatorParserOutput
]
type SyncSplitterParser = Callable[
    [Stream, Extraction, PipeTuples], SplitterParserOutput
]

type SyncPipeParser = Callable[..., ParserOutput]

type PipelineDependencies = Callable[..., list[str]]
type Step = tuple[str, ParserOutput] | tuple[str, SyncPipeParser]
type Steps = dict[str, ParserOutput | SyncPipeParser]


class SyncProcessorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> ProcessorWrapperOutput: ...


class SyncOperatorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        items: OperatorWrapperInput | None = None,
        conf: Conf = None,
        embed: SyncProcessorWrapper | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> OperatorWrapperOutput: ...


class SyncSplitterWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf = None,
        **kwargs,
    ) -> SplitterWrapperOutput: ...


class ParseFuncs(NamedTuple):
    field_parser: SyncItemParseFunc
    conf_parser: SyncConfParseFunc


class CastFuncs(NamedTuple):
    field_caster: SyncArgFunc
    extract_caster: SyncArgFunc
    conf_caster: SyncConfCastFunc


# Async
type AsyncProcessorParser = Callable[
    [T, Extraction, Conf], ProcessorParserOutput | Awaitable[ProcessorParserOutput]
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


class AsyncProcessorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        item: ProcessorWrapperInput | None = None,
        conf: Conf = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Awaitable[ProcessorWrapperOutput]: ...


class AsyncOperatorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        items: OperatorWrapperInput | None = None,
        conf: Conf = None,
        embed: AsyncProcessorWrapper | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Awaitable[OperatorWrapperOutput]: ...


class AsyncSplitterWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        items: SplitterWrapperInput | None = None,
        conf: Conf = None,
        **kwargs,
    ) -> Awaitable[SplitterWrapperOutput]: ...


# Both
type ProcessorParser = SyncProcessorParser | AsyncProcessorParser
type ProcessorWrapper = SyncProcessorWrapper | AsyncProcessorWrapper
type OperatorParser = SyncOperatorParser | AsyncOperatorParser
type OperatorWrapper = SyncOperatorWrapper | AsyncOperatorWrapper
type SplitterParser = SyncSplitterParser | AsyncSplitterParser
type SplitterWrapper = SyncSplitterWrapper | AsyncSplitterWrapper
type Pipeline = SyncPipeParser | AsyncPipeParser
