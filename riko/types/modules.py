from collections.abc import Sequence
from typing import Literal, NotRequired, TypeAlias, TypedDict

Sentinal: TypeAlias = Literal["terminal"]
ModuleName = Literal["fetch", "input", "sort", "tail", "itembuilder", "loop"]


class ConfArg(TypedDict):
    type: str
    value: int | str | bool


class Terminal(TypedDict):
    terminal: str
    type: str


class Subkey(TypedDict):
    subkey: str
    type: str


Value = ConfArg | Terminal | Subkey


class Param(TypedDict):
    key: ConfArg
    value: Value


class FetchConf(TypedDict):
    URL: Value


class SortKey(TypedDict):
    dir: Value
    field: Value
    type: Value


class InputConf(TypedDict):
    debug: ConfArg
    default: ConfArg
    name: ConfArg
    position: ConfArg
    param: Param | Sequence[Param]
    prompt: ConfArg


class SortConf(TypedDict):
    KEY: list[SortKey]


class TailConf(TypedDict):
    count: Value


class ItemBuilderConf(TypedDict):
    attrs: list[Param]


class RssItemBuilderConf(TypedDict, total=False):
    author: Value
    description: Value
    guid: Value
    link: Value
    mediaContentHeight: Value
    mediaContentType: Value
    mediaContentURL: Value
    mediaContentWidth: Value
    mediaThumbHeight: Value
    mediaThumbURL: Value
    mediaThumbWidth: Value
    pubdate: Value
    title: Value


class EmbeddedModule(TypedDict):
    id: str
    type: ModuleName
    conf: "AnyModuleConf"
    assign: NotRequired[ConfArg]
    emit: NotRequired[ConfArg]


class Embed(TypedDict):
    type: Literal["module"]
    value: EmbeddedModule


class LoopConf(TypedDict):
    count: Value
    assign: ConfArg
    embed: Embed
    field: ConfArg


AnyModuleConf = (
    FetchConf
    | InputConf
    | SortConf
    | TailConf
    | ItemBuilderConf
    | LoopConf
    | RssItemBuilderConf
)
