from collections.abc import Awaitable, Callable, Iterable, Iterator, Mapping, Sequence
from io import StringIO
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
    Optional,
    Protocol,
    TypeAlias,
    TypedDict,
    Union,
)

from riko.types.values import (
    BasicArg,
    ComplexArg,
    ComplexDict,
    ComplexValue,
    IntermediateValue,
    NumLike,
    StatefulItem,
)

if TYPE_CHECKING:
    from riko import Context, Objconf
    from riko.cast import BasicCastType
    from riko.types.modules import AnyConfRule, AnyModuleConf, Skip


# Values
ItemArg: TypeAlias = ComplexArg
Stream: TypeAlias = Iterator[ComplexArg]
Items: TypeAlias = Iterable[ComplexArg]

ProcessorItems: TypeAlias = Stream | ComplexDict | ItemArg
OperatorItems: TypeAlias = Stream | NumLike | Items | Iterator[StatefulItem]
PipeTuple: TypeAlias = tuple[ItemArg, "Objconf"]
PipeTuples: TypeAlias = Iterator[PipeTuple]
Objconfs: TypeAlias = Sequence["Objconf"]
Extraction: TypeAlias = Union["Objconf", Objconfs]
ConversionFunc: TypeAlias = Callable[..., Items | StringIO]
Caster: TypeAlias = Callable[[str | int], ComplexValue]
NumericCaster: TypeAlias = Callable[[str | NumLike], NumLike]
SkipFunc: TypeAlias = Callable[[ItemArg], bool]
SkipIf: TypeAlias = Union[SkipFunc, "Skip", Iterable[SkipFunc], Iterable["Skip"]]

# Opener = Callable[[str], tuple[Optional[str | Reencoder], Optional[str]]]
# TODO: add type hint overloads to Reencoder with decode=True -> str
Opener = Callable[[str], tuple[str | StringIO | None, str | None]]


class PreCaster(TypedDict):
    default: IntermediateValue | Mapping[str, str] | None
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
    field: ItemArg
    extraction: ItemArg
    conf: "AnyModuleConf"


class Dispatched(NamedTuple):
    item: ItemArg
    casted: Casted


# Sync
SyncItemFunc: TypeAlias = Callable[[ItemArg], ItemArg]
SyncProcessorParser: TypeAlias = Callable[
    [ItemArg, ItemArg, "AnyModuleConf"], ProcessorItems
]
SyncOperatorParser: TypeAlias = Callable[[Stream, ItemArg, PipeTuples], OperatorItems]

SyncPipeResult: TypeAlias = ProcessorItems | OperatorItems
SyncPipeParser: TypeAlias = Callable[..., SyncPipeResult]

PipelineDependencies: TypeAlias = Callable[..., list[str]]
Step: TypeAlias = tuple[str, SyncPipeResult] | tuple[str, SyncPipeParser]
Steps: TypeAlias = dict[str, SyncPipeResult | SyncPipeParser]


class SyncProcessorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        item: ItemArg = None,
        conf: Union["AnyModuleConf", None] = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Stream: ...


class SyncOperatorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        items: Stream | None = None,
        conf: Union["AnyModuleConf", None] = None,
        embed: SyncProcessorWrapper | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> OperatorItems: ...


class ParseFuncs(NamedTuple):
    field_parser: SyncItemFunc
    conf_parser: SyncItemFunc


class CastFuncs(NamedTuple):
    field_caster: SyncItemFunc
    extract_caster: SyncItemFunc
    conf_caster: Callable[[ItemArg], "AnyModuleConf"]


# Async
AsyncProcessorParser: TypeAlias = Callable[
    [ItemArg, ItemArg, "AnyModuleConf"], Awaitable[ProcessorItems]
]
AsyncOperatorParser: TypeAlias = Callable[
    [Stream, ItemArg, PipeTuples], Awaitable[OperatorItems]
]
AsyncPipeResult: TypeAlias = Awaitable[SyncPipeResult]
AsyncPipeParser: TypeAlias = Callable[..., AsyncPipeResult]


class AsyncProcessorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        item: ItemArg = None,
        conf: Union["AnyModuleConf", None] = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Awaitable[Stream]: ...


class AsyncOperatorWrapper(Protocol):
    def __call__(  # noqa: E704
        self,
        items: Stream | None = None,
        conf: Union["AnyModuleConf", None] = None,
        embed: AsyncProcessorWrapper | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Awaitable[OperatorItems]: ...


# Both
ProcessorParser: TypeAlias = SyncProcessorParser | AsyncProcessorParser
ProcessorWrapper: TypeAlias = SyncProcessorWrapper | AsyncProcessorWrapper
OperatorParser: TypeAlias = SyncOperatorParser | AsyncOperatorParser
OperatorWrapper: TypeAlias = SyncOperatorWrapper | AsyncOperatorWrapper
Pipeline: TypeAlias = SyncPipeParser | AsyncPipeParser
