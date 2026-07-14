# vim: sw=4:ts=4:expandtab
"""
Provides a class for creating case insensitive dicts with dot notation access
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import date
from decimal import Decimal
from functools import reduce
from typing import TYPE_CHECKING, Any, Self, TypeGuard, TypeVar, cast, overload
from typing import cast as cast_type

import pygogo as gogo
from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeIs

from riko import Objectify, replacer
from riko.cast import CAST_SWITCH, CastType
from riko.cast import cast as cast_value
from riko.types.general import Item, Stream
from riko.types.modules import ConfArg
from riko.types.values import (
    BasicList,
    BasicValue,
    BasicValueType,
    Key,
    PrimitiveValue,
    RSSEntry,
    RikoList,
    RikoValue,
    Sentinal,
    SentinalValue,
)

if TYPE_CHECKING:
    from _typeshed import SupportsKeysAndGetItem

logger = gogo.Gogo(__name__, monolog=True).logger


TV_KEYS = ("type", "value")
WIRE_KEYS = ("id", "src", "tgt")
PASSTHROUGH_TYPES = (str, int, float, date, Decimal, Objectify)

D = TypeVar("D")
VT = TypeVar("VT")
type Data = Iterable[tuple[str, VT]] | RSSEntry


def is_mapping[D, VT](val: Mapping[D, VT] | object) -> TypeIs[Mapping[D, VT]]:
    failure = False

    # Delay calling isinstance(val, Mapping) as much as possible
    if not (success := isinstance(val, (dict, CaseInsensitiveDict, Objectify))):
        failure = isinstance(val, (str, int, float))

    return success or (False if failure else isinstance(val, Mapping))


def is_known_sequence[VT](val: object) -> TypeIs[list[VT] | tuple[VT]]:
    return isinstance(val, (list, tuple))


def is_mapping_seq[D, VT](
    val: list[VT] | tuple[VT],
) -> TypeGuard[list[Mapping[D, VT]] | tuple[Mapping[D, VT]]]:
    return is_mapping(val[0])


def is_value_seq[VT](
    val: list[VT] | tuple[VT],
) -> TypeGuard[BasicList | tuple[BasicValue]]:
    return isinstance(val[0], BasicValueType)


def is_sentinal[VT](val: Mapping[str, VT], **kwargs) -> TypeGuard[Sentinal]:
    if SentinalValue in val:
        sentinal = str(val[SentinalValue])
        key = replacer(sentinal, "")
    else:
        key = None

    return all([key, (len(val) == 2), key in kwargs])


def is_type_value(val: Mapping) -> TypeGuard[ConfArg]:
    n = len(val)
    double = n == 2 and "type" in val and "value" in val
    return double or (n == 1 and "value" in val)


def parse_key(key: Key | None = None) -> list[str]:
    if isinstance(key, str):
        if not key:
            keys = []
        elif "." not in key:
            keys = [key]
        else:
            keys = key.rstrip(".").split(".")
    elif key and (subkey := key.get("subkey")):
        keys = [subkey]
    else:
        keys = []

    return keys


@overload
def parse_sentinel(  # noqa: E704  # pyright: ignore[reportOverlappingOverload]
    value: ConfArg, default: object | None = ...
) -> PrimitiveValue: ...
@overload  # noqa: E302
def parse_sentinel[D](  # noqa: E704
    value: Sentinal, default: D | None = ..., **kwargs: object
) -> Item | D | None: ...
@overload  # noqa: E302
def parse_sentinel[D, VT](  # noqa: E704
    value: Mapping[str, VT],
    default: D | None = ...,  # pyright: ignore[reportInvalidTypeVarUse]
    **kwargs: VT,
) -> dict[str, VT]: ...
def parse_sentinel[D, VT](  # noqa: E302
    value: Sentinal | Mapping[str, VT], default: D | None = None, **kwargs: VT
) -> Item | D | dict[str, VT] | PrimitiveValue:
    if is_sentinal(value, **kwargs):
        key = replacer(value[SentinalValue], "")

        if stream := kwargs.get(key):
            stream = cast_type(Stream, stream)
            parsed = next(stream)
        else:
            parsed = default
    elif is_type_value(value):
        parsed = value["value"]

        if (
            not (_type := value.get("type"))
            or (_type == CastType.TEXT)
            and isinstance(parsed, str)
        ):
            pass
        elif _type == CastType.LOCATION:
            logger.warning(f"Location type not supported! Not casting {parsed=}.")
        elif _type in CAST_SWITCH:
            parsed = cast_value(parsed, _type=CastType(_type))
        elif _type != "module":
            logger.warning(f"Invalid cast type={_type}! Not casting {parsed=}.")
    else:
        _parsed = {}

        for k, v in value.items():
            _parsed[k] = parse_sentinel(v, v, **kwargs) if is_mapping(v) else v

        parsed = cast(dict[str, VT], _parsed)

    return parsed


def parse_map[VT](
    *keys: str, data: Mapping[str, VT], **kwargs: VT
) -> Iterator[tuple[str, VT | None]]:
    for key in keys:
        value = DotDict(data).get(key, **kwargs)
        v = next(gen_dict(value, default_key=None))
        yield (key.lower(), v)


def parse_dotdict[VT](*keys: str, data: DotDict[VT]) -> Iterator[tuple[str, VT | None]]:
    for key in keys:
        value = cast(VT, CaseInsensitiveDict.__getitem__(data, key))
        v = next(gen_dict(value, default_key=None))
        yield (key.lower(), cast(VT, v))


@overload
def gen_dict[VT](  # noqa: E704
    data: DotDict[VT] | Mapping[str, VT],
    key: Key | None = ...,
    default_key: str = ...,
    **kwargs: VT,
) -> Iterator[tuple[str, VT | None]]: ...
@overload  # noqa: E302
def gen_dict[VT](  # noqa: E704
    data: DotDict[VT] | Mapping[str, VT],
    key: Key,
    default_key: None,
    **kwargs: VT,
) -> Iterator[dict[str, VT | None]]: ...
@overload  # noqa: E302
def gen_dict[VT](  # noqa: E704
    data: list[VT] | tuple[VT],
    key: Key | None = ...,
    default_key: str = ...,
    **kwargs: VT,
) -> Iterator[dict[str, VT | None]]: ...
@overload  # noqa: E302
def gen_dict[VT](  # noqa: E704
    data: list[VT | None] | tuple[VT | None],
    key: Key | None = ...,
    *,
    default_key: None,
    **kwargs: VT,
) -> Iterator[list[VT | None]]: ...
@overload  # noqa: E302
def gen_dict[VT](  # noqa: E704
    data: VT,
    key: Key | None = ...,
    default_key: str = ...,
) -> Iterator[tuple[str, VT | None]]: ...
@overload  # noqa: E302
def gen_dict[VT](  # noqa: E704
    data: Sentinal | ConfArg,
    key: Key | None = ...,
    *,
    default_key: None,
    **kwargs: VT,
) -> Iterator[VT | None]: ...
@overload  # noqa: E302
def gen_dict[VT](  # noqa: E704
    data: VT,
    key: Key | None = ...,
    *,
    default_key: None,
    **kwargs: VT,
) -> Iterator[VT | None]: ...
def gen_dict[VT](  # noqa: E302
    data: Sentinal
    | ConfArg
    | DotDict[VT]
    | Mapping[str, VT]
    | list[VT]
    | tuple[VT]
    | VT
    | None,
    key: Key | None = None,
    default_key: str | None = "self",
    **kwargs: VT,
) -> Iterator[
    tuple[str, VT | None] | VT | None | list[VT | None] | dict[str, VT | None]
]:
    """
    >>> r = DotDict({'a': {'value': 'bar'}})
    >>> r
    {'a': 'bar'}
    >>> dict(gen_dict(r))
    {'a': 'bar'}
    >>> r = DotDict({'a': {'value': 'baz', 'type': 'text'}})
    >>> r
    {'a': 'baz'}
    >>> dict(gen_dict(r))
    {'a': 'baz'}
    """
    if key:
        keys = parse_key(key)
    else:
        if is_mapping(data):
            if DotDict.is_self(data) and not kwargs:
                data = parse_sentinel(cast(DotDict[VT], data), default=data)
            else:
                data = DotDict(cast(Mapping[str, VT], data)).get(**kwargs)

        keys = []

    if is_mapping(data):
        keys = keys or data.keys()

        if DotDict.is_self(data) and not kwargs:
            items = parse_dotdict(*keys, data=data)
        else:
            items = parse_map(*keys, data=data, **kwargs)

        items = cast(Iterator[tuple[str, VT]], items)

        if default_key:
            yield from items
        else:
            yield dict(items)
    elif is_known_sequence(data) and default_key:
        for d in data:
            yield dict(gen_dict(d, default_key=default_key))
    elif is_known_sequence(data):
        yield [next(gen_dict(d, default_key=None)) for d in data]
    elif default_key:
        yield (default_key, data)
    else:
        yield data


# def is_stateful_item(val: dict | CaseInsensitiveDict) -> TypeIs[StatefulItem]:
#     return len(val) == 1 and "state" in val
#
#
# def is_wire(val) -> TypeIs[Wire]:
#     if is_mapping(val) and len(val) == 3 and all(s in val for s in WIRE_KEYS):
#         x = val["src"]
#         x
#         success = is_mapping(val["src"]) and is_mapping(val["tgt"])
#     else:
#         success = False
#
#     return success
#
#
class DotDict(CaseInsensitiveDict[VT]):
    """
    A dictionary whose keys can be accessed using dot notation

    Examples:
        >>> r = DotDict({'a': {'content': 'value'}})
        >>> r.get('a')
        {'content': 'value'}
        >>> r.get('a.content')
        'value'
        >>> r.get('b.content')
        >>> r['a.content']
        'value'
        >>> param = {
        ...     "value": {"type": "text", "value": "foo"},
        ...     "key": {"type": "text", "value": "q"},
        ... }
        >>> r = DotDict({"param": param})
        >>> r.get('param')
        {'value': 'foo', 'key': 'q'}
        >>> r.asdict()
        {'param': {'value': 'foo', 'key': 'q'}}
        >>> DotDict({"title": "baz"}).get({"subkey": "title"})
        'baz'
        >>> r = DotDict({'KEY': 'bar'})
        >>> 'key' in r
        True
        >>> r.get('key')
        'bar'
        >>> list(r)
        ['KEY']
        >>> [k for k in r]
        ['KEY']
        >>> data = {
        ...     "value": {'value': 'the title', 'type': 'text'},
        ...     "key": 'title',
        ... }
        >>> r = DotDict(data)
        >>> list(r)
        ['value', 'key']
        >>> [k for k in r]
        ['value', 'key']
        >>> DotDict({'start': 0, 'count': {'type': 'int', 'value': '5'}})
        {'start': 0, 'count': 5}
        >>> DotDict(**{'a': 1, 'b': 2})
        {'a': 1, 'b': 2}

    """

    def __init__(self, data: Mapping[str, VT] | Data | None = None, **kwargs: VT):
        super().__init__()
        self.update(data, **kwargs)

    @classmethod
    def is_self[V](cls, value: Mapping[str, V]) -> TypeGuard[DotDict[V]]:
        return isinstance(value, DotDict)

    @overload
    @classmethod
    def dictize[V](cls, value: Mapping[str, V]) -> DotDict[V]: ...  # noqa: E704
    @overload  # noqa: E301
    @classmethod
    def dictize[V](cls, value: Mapping[str, V], key: Key) -> V: ...  # noqa: E704
    @overload  # noqa: E301
    @classmethod
    def dictize[T, V](  # noqa: E704
        cls,
        value: Mapping[str, V],
        key: Key | None = ...,
        default: T | None = ...,
        **kwargs: V,
    ) -> T | None: ...
    @overload  # noqa: E301
    @classmethod
    def dictize[V](cls, value: V) -> V: ...  # noqa: E704
    @overload  # noqa: E301
    @classmethod
    def dictize[V](  # noqa: E704 # pyright: ignore[reportOverlappingOverload]
        cls, value: Mapping[str, V] | V
    ) -> DotDict[V] | V: ...
    @classmethod  # noqa: E30
    def dictize[T, V](
        cls,
        value: Mapping[str, V] | V,
        key: Key | None = None,
        default: T | None = None,
        **kwargs: V,
    ) -> DotDict[V] | V | T | None:
        if is_mapping(value):
            if cls.is_self(value):
                result = value
            else:
                result = cast(DotDict[V], cls(cast(Mapping[str, Any], value)))

            if key or kwargs:
                result = result.get(key=key, default=default, **kwargs)
        else:
            result = value

        return result

    @overload
    def _parse_value(  # noqa: E704
        self,
        value: Mapping[str, VT],
        key: str | int,
        default: D | None = ...,
        **kwargs: VT,
    ) -> VT | dict[str, VT] | Item | RikoValue | D | None: ...
    @overload  # noqa: E301
    def _parse_value(  # noqa: E704
        self,
        value: list[VT] | tuple[VT],
        key: str | int,
        default: object | None = ...,
        **kwargs: VT,
    ) -> RikoList | BasicValue: ...
    @overload  # noqa: E301
    def _parse_value(  # noqa: E704
        self, value: object, key: str | int, default: D | None = ..., **kwargs: VT
    ) -> D | None: ...
    def _parse_value(  # noqa: E301
        self,
        value: list[VT] | tuple[VT] | Mapping[str, VT] | object,
        key: str | int,
        default: D | None = None,
        **kwargs: VT,
    ) -> VT | D | Any:
        parsed = default
        msg = f"Ignoring unsupported key {key} to access {{0}} value {{1}}."

        if is_mapping(value):
            if isinstance(key, str):
                dd_value = value if self.is_self(value) else DotDict(value)

                if key in dd_value:
                    parsed = dd_value[key]
                elif is_sentinal(value, **kwargs):
                    parsed = parse_sentinel(value, default=default, **kwargs)

                    if is_mapping(parsed) and key in parsed:
                        parsed = parsed[key]
                    elif key:
                        parsed = default
            else:
                logger.warning(msg.format("Mapping", value))
        elif is_known_sequence(value):
            if is_mapping_seq(value):
                if isinstance(key, str):
                    parsed = cast(RikoList, [v[key] for v in value])
                else:
                    logger.warning(msg.format("submapping", value[0]))
            elif is_value_seq(value):
                if isinstance(key, int):
                    parsed = value[key]
                else:
                    logger.warning(msg.format("submapping", value[0]))
            else:
                parsed = list(value)
        elif value is not None:
            parsed = value

        return parsed

    def __getitem__(self, key: Key) -> VT:
        """
        >>> r = DotDict({'key': 'bar'})
        >>> r['key']
        'bar'
        >>> r['KEY']
        'bar'
        """
        keys = parse_key(key)
        value = cast(VT, CaseInsensitiveDict.__getitem__(self, keys[0]))

        if len(keys) > 1:
            key = ".".join(keys[1:])
            msg = f"Ignoring unsupported key {key} to access non-mapping value {value}."

            if is_mapping(value):
                value = cast(VT, value[key])
            else:
                logger.warning(msg)

        result = value

        if is_mapping(value):
            parsed = parse_sentinel(value, default=value)
            result = cast(VT, self.dictize(parsed))

        return result

    def __setitem__(self, key: str, value: VT):
        """
        >>> r = DotDict({'author': 'bar'})
        >>> r
        {'author': 'bar'}
        >>> r['author.name'] = 'bar'
        >>> r
        {'author': {'name': 'bar'}}
        >>> r['author.url'] = 'example.com'
        >>> r
        {'author': {'name': 'bar', 'url': 'example.com'}}
        """

        def reducer(item: Self, key: str) -> Self:
            if item and key in item:
                existing = CaseInsensitiveDict.__getitem__(item, key)

                if existing and not is_mapping(existing):
                    del item[key]
                    existing = None
            else:
                existing = None

            if existing is None:
                existing = item[key] = cast(VT, {})
                # CaseInsensitiveDict.__setitem__(item, key, existing)

            return cast(Self, existing)

        keys = parse_key(key)

        if len(keys) == 1:
            CaseInsensitiveDict.__setitem__(self, key, value)
        else:
            item = self.copy()
            rest, last = keys[:-1], keys[-1]
            reduced = reduce(reducer, rest, item)
            reduced[last] = value
            CaseInsensitiveDict.update(self, item)

    def __or__[V](self, other: Mapping[str, V]) -> Self:
        """
        >>> r = DotDict({'key': 'bar'})
        >>> r | {'key': 'baz'}
        {'key': 'baz'}
        >>> r | DotDict({'key': 'baz'})
        {'key': 'baz'}
        """
        dd = self.copy()
        dd.update(other)
        return dd

    @overload
    def get(  # noqa: E704
        self, key: Key | None, default: None = None
    ) -> VT | None: ...
    @overload
    def get(self, key: Key | None, default: D) -> D: ...  # noqa: E704
    @overload  # noqa: E301
    def get(  # noqa: E704  # pyright: ignore[reportOverlappingOverload]
        self, key: Key | None, default: D | VT
    ) -> D | VT: ...
    @overload
    def get(self) -> VT: ...  # noqa: E704
    @overload
    def get(self, **kwargs: VT) -> VT | None: ...  # noqa: E704
    def get(  # noqa: E301  # pyright: ignore[reportInconsistentOverload]
        self,
        key: Key | None = None,
        default: D | None = None,
        **kwargs: VT,
    ) -> Self | VT | D | Item | dict[str, VT] | PrimitiveValue:
        """
        >>> r = DotDict({'key': 'bar'})
        >>> r.get('key')
        'bar'
        >>> r.get('KEY')
        'bar'
        >>> r.get('KEY')
        'bar'
        >>> r.get('baz')
        >>> r = DotDict({"terminal": "attrs_1", "type": "text"})
        >>> r.get()
        {'terminal': 'attrs_1', 'type': 'text'}
        >>> r.get(attrs_1=iter(['baz']))
        'baz'
        >>> r.get(attrs_1=iter([{'content': 'baz'}]))
        {'content': 'baz'}
        >>> r.get('subkey')
        >>> attrs = {
        ...     "value": {"terminal": "attrs_1", "type": "text"},
        ...     "key": {"type": "text", "value": "title"},
        ... }
        >>> r = DotDict({'attrs': attrs})
        >>> r.get('attrs')
        {'value': {'terminal': 'attrs_1', 'type': 'text'}, 'key': 'title'}
        >>> r.get('attrs.key')
        'title'
        >>> r.get('attrs.value')
        {'terminal': 'attrs_1', 'type': 'text'}
        >>> r.get('subkey')
        >>> r.get('attrs.value', attrs_1=iter([{'content': 'baz'}]))
        {'content': 'baz'}
        >>> r.get('attrs.value.content', attrs_1=iter([{'content': 'baz'}]))
        'baz'
        >>> r.get('attrs.value.foo', attrs_1=iter([{'content': 'baz'}]))
        >>> r = DotDict({'stanzas': {'verses': ['verse1', 'verse2']}})
        >>> r.get('stanzas.verses')
        ['verse1', 'verse2']
        >>> r.get('stanzas.verses.1')
        'verse2'
        """
        keys = parse_key(key)
        item = self

        if keys:
            for k in keys:
                try:
                    k = int(k)
                except ValueError:
                    pass

                item = self._parse_value(item, k, default=default, **kwargs)
        else:
            item = parse_sentinel(item, default=item, **kwargs)

        if is_mapping(item) and is_sentinal(item, **kwargs):
            item = parse_sentinel(item, default=default, **kwargs)

        return self.dictize(item)

    def copy(self) -> Self:
        return type(self)(self)

    def delete(self, key: str):
        reducer = lambda i, k: DotDict(i.get(k))
        keys = parse_key(key)
        rest, last = keys[:-1], keys[-1]
        reduced = reduce(reducer, rest, self)

        try:
            _key = reduced[last]
        except KeyError:
            pass
        else:
            del _key

    @overload
    def update(  # noqa: E704
        self, data: SupportsKeysAndGetItem[str, VT]
    ) -> None: ...
    @overload  # noqa: E301
    def update(  # noqa: E704
        self, data: SupportsKeysAndGetItem[str, VT], **kwargs: VT
    ) -> None: ...
    @overload
    def update(self, data: Data) -> None: ...  # noqa: E704
    @overload  # noqa: E301
    def update(  # noqa: E704
        self, data: Data, **kwargs: VT
    ) -> None: ...
    @overload
    def update[V](self, data: Mapping[str, V]) -> None: ...  # noqa: E704
    @overload
    def update(self, **kwargs: VT) -> None: ...  # noqa: E704
    @overload
    def update(self, data: None) -> None: ...  # noqa: E704
    def update(  # noqa: E301  # pyright: ignore[reportInconsistentOverload]
        self, data: SupportsKeysAndGetItem[str, VT] | Data | None = None, **kwargs: VT
    ):
        """
        >>> r = DotDict({'author': 'bar'})
        >>> r
        {'author': 'bar'}
        >>> r.update({'author.name': 'bar', 'author.url': 'example.com'})
        >>> r
        {'author': {'name': 'bar', 'url': 'example.com'}}
        >>> r = DotDict({'author.name': 'bar', 'author.url': 'example.com'})
        >>> r
        {'author': {'name': 'bar', 'url': 'example.com'}}
        """
        if is_mapping(data):
            data = cast(Mapping[str, VT], data)
            if self.is_self(data):
                if kwargs:
                    _dict = data | kwargs
                else:
                    return self._store.update(data._store)
            elif kwargs or any("." in k for k in data):
                _dict = cast_type(dict[str, VT], {**data, **kwargs})
            else:
                for key, value in data.items():
                    CaseInsensitiveDict.__setitem__(self, key, value)

                return
        elif data:
            _dict = dict(data, **kwargs)
        else:
            _dict = kwargs

        if dot_keys := [k for k in _dict if "." in k]:
            # skip key if a subkey redefines it
            # i.e., 'author.name' has precedence over 'author'
            skip_keys = {".".join(parse_key(key)[:-1]) for key in dot_keys}
            items = [(k, _dict[k]) for k in _dict if k not in skip_keys]
        else:
            items = _dict.items()

        for key, value in items:
            self[key] = value

    def asdict(self, key: Key | None = None, **kwargs: VT) -> dict[str, VT | None]:
        """
        >>> r = DotDict({'a': {'value': 'bar'}})
        >>> r
        {'a': 'bar'}
        >>> r.asdict()
        {'a': 'bar'}
        >>> r = DotDict({'a': {'value': 'baz', 'type': 'text'}})
        >>> r
        {'a': 'baz'}
        >>> r.asdict()
        {'a': 'baz'}
        """
        items = gen_dict(self, key=key, default_key="self", **kwargs)
        return dict(items)
