from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum, auto
from io import StringIO
from time import struct_time
from typing import (
    TYPE_CHECKING,
    Literal,
    NamedTuple,
    NotRequired,
    Optional,
    Protocol,
    TypeAlias,
    TypedDict,
    Union,
)

from twisted.internet.defer import Deferred

from riko.types.compile import LayoutItem, Module, TerminalDataEntry, Wire

if TYPE_CHECKING:
    from riko import Context, Objconf, Objectify
    from riko.dotdict import DotDict


class StreamState(Enum):
    PENDING = auto()
    DONE = auto()


# Values
CurrencyCode: TypeAlias = Mapping[str, str | int | float]
Location: TypeAlias = Mapping[str, str | float]
IPAddress: TypeAlias = Mapping[str, str]
AnyLocation: TypeAlias = Location | IPAddress | CurrencyCode
BasicValue: TypeAlias = str | int
DateLike: TypeAlias = BasicValue | date | datetime | struct_time
DateDict: TypeAlias = Mapping[str, str | int | date | bool]
NumLike: TypeAlias = float | int | Decimal
IntermediateValue: TypeAlias = BasicValue | DateLike | NumLike | bool | None
ComplexValue: TypeAlias = IntermediateValue | AnyLocation
Caster: TypeAlias = Callable[[str | int], ComplexValue]
NumericCaster: TypeAlias = Callable[[str | int | float | Decimal], NumLike]


class PreCaster(TypedDict):
    default: IntermediateValue | Mapping[str, str] | None
    func: Caster


Objconfs: TypeAlias = Sequence["Objconf"]
Extraction: TypeAlias = Union["Objconf", Objconfs]


class StatefulItem(TypedDict):
    state: StreamState


BasicMapping: TypeAlias = Mapping[str, "BasicArg"]
IntermediateMapping: TypeAlias = Union[
    BasicMapping, Mapping[str, "IntermediateArg"], "DotDict"
]
ComplexMapping: TypeAlias = Union[
    IntermediateMapping,
    Mapping[str, "ComplexArg"],
    DateDict,
    Location,
    "Objconf",
    "Objectify",
    StatefulItem,
    Wire,
]
BasicSequence: TypeAlias = Sequence["BasicArg"]
IntermediateSequence: TypeAlias = Sequence["IntermediateArg"]
ComplexSequence: TypeAlias = Sequence["ComplexArg"]
BasicArg: TypeAlias = BasicValue | BasicMapping | BasicSequence
IntermediateArg: TypeAlias = (
    IntermediateValue | IntermediateMapping | IntermediateSequence
)
ComplexArg: TypeAlias = ComplexValue | ComplexMapping | ComplexSequence

BasicDict: TypeAlias = dict[str, "BasicAnyReturn"]
BasicList: TypeAlias = list["BasicAnyReturn"]
BasicAnyReturn: TypeAlias = BasicDict | BasicList | BasicValue

ItemArg: TypeAlias = Union["DotDict", BasicMapping, BasicValue]
Items: TypeAlias = Iterator[ItemArg]
ItemsArg: TypeAlias = Iterable[ItemArg]
ProcessorItems: TypeAlias = (
    Items | ComplexArg | Iterator[BasicArg | BasicMapping | None]
)
OperatorItems: TypeAlias = (
    ItemsArg | NumLike | Iterator[dict[str, StreamState] | ComplexArg]
)
PipeTuple: TypeAlias = tuple[ItemArg, "Objconf"]
PipeTuples: TypeAlias = Iterator[PipeTuple]
ConversionFunc: TypeAlias = Callable[..., ItemsArg | StringIO]

# Opener = Callable[[str], tuple[Optional[str | Reencoder], Optional[str]]]
# TODO: add type hint overloads to Reencoder with decode=True -> str
tuple[str | StringIO | None, str | None]
Opener = Callable[[str], tuple[str | StringIO | None, str | None]]


class Skip(TypedDict):
    field: str
    include: NotRequired[bool]


class PipeDef(TypedDict):
    layout: list[LayoutItem]
    modules: list[Module]
    terminaldata: list[TerminalDataEntry]
    # TODO: json can be either a list or object, so will need to handle both cases in
    # the parser
    wires: list[Wire]


class ParsedPipeDef(TypedDict):
    name: str
    modules: dict[str, Module]
    embed: dict[str, Module]
    graph: dict[str, str | list[str]]
    wires: dict[str, Wire]


class ParsedParam(TypedDict):
    key: str
    value: str


class ParsedInputConf(TypedDict):
    name: str
    prompt: str
    default: NotRequired[str]
    debug: NotRequired[bool]
    param: ParsedParam | Sequence[ParsedParam]


class ObjconfParam:
    key: str
    value: str


@dataclass
class ObjconfRegexRule:
    field: str
    default: str
    casematch: bool | None
    singlelinematch: bool | None
    offset: int | None
    match: str
    replace: str = ""
    seriesmatch: bool = True


class ObjconfRule:
    field: str
    value: BasicArg
    op: Literal[
        "contains",
        "doesnotcontain",
        "matches",
        "is",
        "isnot",
        "truthy",
        "falsy",
        "greater",
        "less",
        "after",
        "before",
        "atleast",
        "atmost",
    ]
    dir: str | None
    type: str | None
    newval: str | None
    copy: bool | None


class Defaults(TypedDict, total=False):
    combine: Literal["and", "or"]
    convert: bool
    count_key: str
    currency: str
    default: BasicArg
    delay: int
    delimiter: str
    encoding: str
    format: str
    max_wait: int
    multi: bool
    permit: bool
    quotechar: str
    test: bool
    type: str
    wait: int


class Opts(TypedDict, total=False):
    assign: str
    count: Literal["first", "all"]
    emit: bool
    extract: str
    field: str
    ftype: str
    listize: bool
    objectify: bool
    parse: bool
    ptype: str


class ParsedConf(Defaults, total=False):
    attrs: Sequence[str]
    base: str
    col_names: Sequence[str]
    debug: bool
    detag: bool
    embed: Module
    end: str
    group_key: str
    html5: bool
    join_key: str
    length: int
    limit: int
    lower: bool
    max_len: int
    name: str
    other: str
    other_join_key: str
    param: ParsedParam | Sequence[ParsedParam]
    parse_key: str
    part: str
    path: str
    precision: int
    prompt: str
    skip_rows: int
    sort: bool
    start: str
    stop: str
    strict: bool
    stringify: bool
    sum_key: str
    times: int
    token: str
    unique_key: str
    url: str
    xpath: str


class Casted(NamedTuple):
    field: ComplexArg
    extraction: ComplexArg
    conf: ComplexArg


class Dispatched(NamedTuple):
    item: ItemArg
    casted: Casted


# Sync
SyncItemFunc: TypeAlias = Callable[[ItemArg | None], ComplexArg]
SyncAnyFunc: TypeAlias = Callable[[ComplexArg], ComplexArg]

SyncProcessorParser: TypeAlias = Callable[
    [ComplexArg, ComplexArg, ComplexArg], ProcessorItems
]
SyncOperatorParser: TypeAlias = Callable[[Items, ComplexArg, PipeTuples], OperatorItems]

SyncPipeResult: TypeAlias = ProcessorItems | OperatorItems
SyncPipeline: TypeAlias = Callable[..., SyncPipeResult]

PipelineDependencies: TypeAlias = Callable[..., list[str]]
Step: TypeAlias = tuple[str, SyncPipeResult] | tuple[str, SyncPipeline]
Steps: TypeAlias = dict[str, SyncPipeResult | SyncPipeline]


class SyncProcessorWrapper(Protocol):
    def __call__(
        self,
        item: ItemArg | None = None,
        conf: BasicMapping | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Items: ...


class SyncOperatorWrapper(Protocol):
    def __call__(
        self,
        items: Items | None = None,
        conf: BasicMapping | None = None,
        embed: SyncProcessorWrapper | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Items: ...


class ParseFuncs(NamedTuple):
    field_parser: SyncItemFunc
    conf_parser: SyncItemFunc


class CastFuncs(NamedTuple):
    field_caster: SyncAnyFunc
    extract_caster: SyncAnyFunc
    conf_caster: SyncAnyFunc


# Async
AsyncProcessorParser: TypeAlias = Callable[
    [ComplexArg, ComplexArg, ComplexArg], Deferred[ProcessorItems]
]
AsyncOperatorParser: TypeAlias = Callable[
    [Deferred[Items], ComplexArg, PipeTuples], Deferred[OperatorItems]
]

AsyncPipeResult: TypeAlias = Deferred[ProcessorItems] | Deferred[OperatorItems]
AsyncPipeline: TypeAlias = Callable[..., AsyncPipeResult]


class AsyncProcessorWrapper(Protocol):
    def __call__(
        self,
        item: ItemArg | None = None,
        conf: BasicMapping | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Deferred[Items]: ...


class AsyncOperatorWrapper(Protocol):
    def __call__(
        self,
        items: Items | None = None,
        conf: BasicMapping | None = None,
        embed: AsyncProcessorWrapper | None = None,
        context: Optional["Context"] = None,
        **kwargs,
    ) -> Deferred[Items]: ...


# Both
ItemsResult: TypeAlias = Items | Deferred[Items]
StreamResult: TypeAlias = Items | Deferred[Items]
ProcessorParser: TypeAlias = SyncProcessorParser | AsyncProcessorParser
ProcessorWrapper: TypeAlias = SyncProcessorWrapper | AsyncProcessorWrapper
OperatorParser: TypeAlias = SyncOperatorParser | AsyncOperatorParser
OperatorWrapper: TypeAlias = SyncOperatorWrapper | AsyncOperatorWrapper
Pipeline: TypeAlias = SyncPipeline | AsyncPipeline
