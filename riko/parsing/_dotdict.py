# vim: sw=4:ts=4:expandtab
"""Provides a class for creating case insensitive dicts with dot notation access."""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from datetime import date
from decimal import Decimal
from functools import reduce
from typing import TYPE_CHECKING, Self, TypeGuard, TypeVar, cast, overload

from requests.structures import CaseInsensitiveDict

from riko.base._guards import (
    is_known_sequence,
    is_mapping,
    is_mapping_seq,
    is_value_seq,
)
from riko.base._logging import get_logger
from riko.base._sentinels import Sentinel, SentinelValue, StreamState, is_sentinel
from riko.base._strutils import replacer
from riko.coercion._objectify import Objectify
from riko.coercion.cast import cast_value, resolve_cast_type
from riko.types._enums import CastType
from riko.types.modules import is_type_value

if TYPE_CHECKING:
    from logging import Logger

    from _typeshed import SupportsKeysAndGetItem

    from riko.types._scalars import BasicValue, PrimitiveValue
    from riko.types._streams import Item, ItemOrValue, StatefulItem, Stream
    from riko.types._values import RikoList
    from riko.types.modules import ConfArg

logger: Logger = get_logger(__name__)

TV_KEYS = ("type", "value")
PASSTHROUGH_TYPES = (str, int, float, date, Decimal, Objectify)
D = TypeVar("D")

type Data[VT] = Iterable[tuple[str, VT]]
type DotDictInput[VT] = Data[VT] | Item
type SubkeyRef = Mapping[str, str]
type Key = str | SubkeyRef


def parse_key(key: Key | None = None) -> list[str]:
    if isinstance(key, str):
        if "." in key:
            keys = key.rstrip(".").split(".")
        else:
            keys = [key] if key else []
    elif key and (subkey := key.get("subkey")):
        keys = [subkey]
    else:
        keys = []

    return keys


def match_key(data: object, key: str) -> str | None:
    """
    Case insensitively finds the ``data`` key named by ``key``.

    Args:

        data: The mapping to look in (non-mappings will match nothing).
        key: The key to look up.

    Returns:

        The key as ``data`` stores it, or ``None`` when no key matches.

    Examples:

        >>> match_key({"Title": 1}, "TITLE")
        'Title'

    """
    if isinstance(data, CaseInsensitiveDict):
        stored = data._store.get(key.lower())
        matched = None if stored is None else stored[0]
    elif is_mapping(data):
        if key in data:
            matched = key
        else:
            lowered = key.lower()
            keys = (k for k in data if k.lower() == lowered)
            matched = next(keys, None)
    else:
        matched = None

    return matched


def raw_get[VT](data: Mapping[str, VT], key: str) -> VT:
    if isinstance(data, CaseInsensitiveDict):
        value = CaseInsensitiveDict.__getitem__(data, key)  # noqa: PLC2801
    else:
        value = data[key]

    return value


def raw_set[VT](data: MutableMapping[str, VT], key: str, value: VT) -> None:
    if isinstance(data, CaseInsensitiveDict):
        CaseInsensitiveDict.__setitem__(data, key, value)  # noqa: PLC2801
    else:
        data[key] = value


def detach_nested[VT](data: MutableMapping[str, VT], key: str) -> VT | None:
    """Replaces the mapping at ``key`` with a copy, so writes stay off the source."""
    value = raw_get(data, key)

    if isinstance(value, CaseInsensitiveDict):
        copied = value.copy()
    elif is_mapping(value):
        copied = dict(value)
    else:
        copied = None

    if copied is not None:
        raw_set(data, key, cast("VT", copied))

    return cast("VT | None", copied)


@overload
def resolve_sentinel(  # pyright: ignore[reportOverlappingOverload]
    value: ConfArg, default: object | None = ...
) -> PrimitiveValue: ...
@overload
def resolve_sentinel[D](
    value: Sentinel, default: D | None = ..., **kwargs: object
) -> Item | D | None: ...
@overload
def resolve_sentinel[D, VT](
    value: Mapping[str, VT],
    default: D | None = ...,  # pyright: ignore[reportInvalidTypeVarUse]
    **kwargs: VT,
) -> dict[str, VT]: ...
def resolve_sentinel[D, VT](
    value: Sentinel | Mapping[str, VT], default: D | None = None, **kwargs: VT
) -> Item | D | dict[str, VT] | PrimitiveValue:
    if is_sentinel(value, **kwargs):
        key = replacer(value[SentinelValue], "")

        if stream := kwargs.get(key):
            stream = cast("Stream", stream)
            parsed = next(stream, default)
        else:
            parsed = default
    elif is_type_value(value):
        parsed = value["value"]

        if (
            not (type_ := value.get("type"))
            or (type_ == CastType.TEXT)
            and isinstance(parsed, str)
        ):
            pass
        elif type_ == CastType.LOCATION:
            logger.warning(f"Location type not supported! Not casting {parsed=}.")
        elif type_ != "module":
            parsed = cast_value(parsed, resolve_cast_type(type_))
    else:
        _parsed = {}

        for k, v in value.items():
            _parsed[k] = resolve_sentinel(v, v, **kwargs) if is_mapping(v) else v

        parsed = cast("dict[str, VT]", _parsed)

    return parsed


def gen_map_items[VT](
    *keys: str, data: Mapping[str, VT], **kwargs: VT
) -> Iterator[tuple[str, VT | None]]:
    dd = data if DotDict.is_self(data) else DotDict(data)

    for key in keys:
        value = dd.get(key, **kwargs)
        v = next(gen_dict(value, default_key=None))
        yield (key.lower(), v)


def gen_dotdict_items[VT](
    *keys: str, data: DotDict[VT]
) -> Iterator[tuple[str, VT | None]]:
    for key in keys:
        if key in data:
            value = raw_get(data, key)
            v = next(gen_dict(value, default_key=None))
        else:
            v = None

        yield (key.lower(), v)


@overload
def gen_dict[VT](
    data: DotDict[VT] | Mapping[str, VT],
    key: Key | None = ...,
    default_key: str = ...,
    **kwargs: VT,
) -> Iterator[tuple[str, VT | None]]: ...
@overload
def gen_dict[VT](
    data: DotDict[VT] | Mapping[str, VT], key: Key, default_key: None, **kwargs: VT
) -> Iterator[dict[str, VT | None]]: ...
@overload
def gen_dict[VT](
    data: list[VT] | tuple[VT, ...],
    key: Key | None = ...,
    default_key: str = ...,
    **kwargs: VT,
) -> Iterator[dict[str, VT | None]]: ...
@overload
def gen_dict[VT](
    data: list[VT | None] | tuple[VT, ...],
    key: Key | None = ...,
    *,
    default_key: None,
    **kwargs: VT,
) -> Iterator[list[VT | None]]: ...
@overload
def gen_dict[VT](
    data: VT, key: Key | None = ..., default_key: str = ...
) -> Iterator[tuple[str, VT | None]]: ...
@overload
def gen_dict[VT](
    data: Sentinel | ConfArg, key: Key | None = ..., *, default_key: None, **kwargs: VT
) -> Iterator[VT | None]: ...
@overload
def gen_dict[VT](
    data: VT, key: Key | None = ..., *, default_key: None, **kwargs: VT
) -> Iterator[VT | None]: ...
def gen_dict(
    data: object,
    key: Key | None = None,
    default_key: str | None = "self",
    **kwargs: object,
) -> Iterator[object]:
    """
    Generates a data tuple.

    Examples:

        >>> r = DotDict({'a': {'value': 'bar'}})
        >>> r
        {'a': {'value': 'bar'}}
        >>> dict(gen_dict(r))
        {'a': {'value': 'bar'}}
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
                data = resolve_sentinel(data, default=data)
            else:
                data = DotDict(data).get(**kwargs)

        keys = []

    if is_mapping(data):
        keys = keys or data.keys()

        if DotDict.is_self(data) and not kwargs:
            items = gen_dotdict_items(*keys, data=data)
        else:
            items = gen_map_items(*keys, data=data, **kwargs)

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


class DotDict[VT](CaseInsensitiveDict[VT]):
    """
    A dictionary whose keys can be accessed using dot notation.

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

    def __init__(
        self, data: Mapping[str, VT] | DotDictInput[VT] | None = None, **kwargs: VT
    ):
        super().__init__()
        self.update(data, **kwargs)

    @classmethod
    def is_self[V](cls, value: Mapping[str, V]) -> TypeGuard[DotDict[V]]:
        return isinstance(value, DotDict)

    @overload
    @classmethod
    def dictize(cls, value: StatefulItem) -> DotDict[StreamState]: ...
    @overload
    @classmethod
    def dictize[V](cls, value: Mapping[str, V]) -> DotDict[V]: ...
    @overload
    @classmethod
    def dictize[V](cls, value: Mapping[str, V], key: Key) -> V | None: ...
    @overload
    @classmethod
    def dictize[V, D](
        cls,
        value: Mapping[str, V],
        key: Key | None = ...,
        default: D | None = ...,
        **kwargs: V,
    ) -> V | D | None: ...
    @overload
    @classmethod
    def dictize[V](cls, value: V) -> V: ...
    @classmethod
    def dictize(
        cls,
        value: object,
        key: Key | None = None,
        default: object | None = None,
        **kwargs: object,
    ) -> object:
        if is_mapping(value):
            mapping = cast("Mapping[str, object]", value)

            if cls.is_self(mapping):
                result: object = mapping
            else:
                result = DotDict[object](mapping)

            if key is not None or kwargs:
                result = result.get(key=key, default=default, **kwargs)
        else:
            result = value

        return result

    @overload
    def _parse_value(
        self,
        value: Mapping[str, VT],
        key: str | int,
        default: D | None = ...,
        **kwargs: VT,
    ) -> VT | dict[str, VT] | ItemOrValue | D | None: ...
    @overload
    def _parse_value(
        self,
        value: list[VT] | tuple[VT, ...],
        key: str | int,
        default: object | None = ...,
        **kwargs: VT,
    ) -> RikoList | BasicValue: ...
    @overload
    def _parse_value[V, D](
        self, value: V, key: str | int, default: D | None = ..., **kwargs: VT
    ) -> V | D | None: ...
    def _parse_value(
        self, value: object, key: str | int, default: object | None = None, **kwargs: VT
    ) -> object:
        """
        Parse value helper.

        Examples:

            >>> dd = DotDict()
            >>> dd._parse_value([10, 20], 1, 'missing')
            20
            >>> dd._parse_value([10, 20], 5, 'missing')
            'missing'
            >>> dd._parse_value([{'b': 1}, {'b': 2}], 'b', 'missing')
            [1, 2]
            >>> dd._parse_value([{'b': 1}, {'b': 2}], 'z', 'missing')
            'missing'

        """
        parsed = default
        msg = f"Ignoring unsupported key {key} to access {{0}} value {{1}}."

        if is_mapping(value):
            if isinstance(key, str):
                dd_value = value if self.is_self(value) else DotDict(value)

                if key in dd_value:
                    parsed = dd_value[key]
                elif is_sentinel(value, **kwargs):
                    parsed = resolve_sentinel(value, default=default, **kwargs)

                    if is_mapping(parsed) and key in parsed:
                        parsed = parsed[key]
                    elif key:
                        parsed = default
            else:
                logger.warning(msg.format("Mapping", value))
        elif is_known_sequence(value):
            if is_mapping_seq(value):
                if isinstance(key, str):
                    try:
                        parsed = cast("RikoList", [v[key] for v in value])
                    except (KeyError, IndexError):
                        parsed = default
                else:
                    logger.warning(msg.format("submapping", value[0]))
            elif is_value_seq(value):
                if isinstance(key, int):
                    try:
                        parsed = value[key]
                    except IndexError:
                        parsed = default
                else:
                    logger.warning(msg.format("submapping", value[0]))
            else:
                parsed = list(value)
        elif value is not None:
            parsed = value

        return parsed

    def __getitem__(self, key: Key) -> VT:
        """
        __getitem__.

        Examples:

            >>> r = DotDict({'key': 'bar'})
            >>> r['key']
            'bar'
            >>> r['KEY']
            'bar'

        """
        keys = parse_key(key)
        value = raw_get(self, keys[0])

        if len(keys) > 1:
            key = ".".join(keys[1:])
            msg = f"Ignoring unsupported key {key} to access non-mapping value {value}."

            if is_mapping(value):
                nested = value if self.is_self(value) else DotDict(value)
                value = cast("VT", nested[key])
            else:
                logger.warning(msg)

        result = value

        if is_mapping(value):
            parsed = resolve_sentinel(value, default=value)
            result = cast("VT", self.dictize(parsed))

        return result

    def __contains__(self, key: object) -> bool:
        """
        Checks whether a key, dotted path, or subkey mapping resolves to a value.

        Examples:

            >>> r = DotDict({'A': {'content': 'value'}})
            >>> 'a' in r
            True
            >>> 'a.content' in r
            True
            >>> 'b' in r
            False

        """
        if isinstance(key, str) and "." not in key:
            contained = key.lower() in self._store
        else:
            try:
                self[cast("Key", key)]
            except KeyError:
                contained = False
            else:
                contained = True

        return contained

    def __setitem__(self, key: str, value: VT) -> None:
        """
        __setitem__.

        Examples:

            >>> r = DotDict({'author': 'bar'})
            >>> r
            {'author': 'bar'}
            >>> r['author.name'] = 'bar'
            >>> r
            {'author': {'name': 'bar'}}
            >>> r['author.url'] = 'example.com'
            >>> r
            {'author': {'name': 'bar', 'url': 'example.com'}}
            >>> c = DotDict({'count': 0})
            >>> c['count.total'] = 1
            >>> c
            {'count': {'total': 1}}

        """

        def reducer(item: Self, key: str) -> Self:
            if (existing := detach_nested(item, key) if key in item else None) is None:
                existing = cast("VT", {})
                raw_set(item, key, existing)

            return cast("Self", existing)

        keys = parse_key(key)

        if len(keys) == 1:
            CaseInsensitiveDict.__setitem__(self, key, value)
        else:
            rest, last = keys[:-1], keys[-1]
            raw_set(reduce(reducer, rest, self), last, value)

    @overload
    def __or__(self, other: SupportsKeysAndGetItem[str, VT]) -> Self: ...
    @overload
    def __or__[T](self, other: SupportsKeysAndGetItem[str, T]) -> DotDict[VT | T]: ...
    def __or__[T](
        self, other: SupportsKeysAndGetItem[str, T]
    ) -> Self | DotDict[VT | T]:
        """
        Merge another mapping, widening the value type to cover both mappings.

        Examples:

            >>> r = DotDict({'key': 'bar'})
            >>> r | {'key': 'baz'}
            {'key': 'baz'}
            >>> r | DotDict({'key': 'baz'})
            {'key': 'baz'}

        """
        dd = cast("DotDict[VT | T]", self.copy())
        dd.update(other)
        return dd

    @overload
    def get(self, key: Key | None, default: None = None) -> VT | None: ...
    @overload
    def get(self, key: Key | None, default: D) -> D: ...
    @overload
    def get(  # pyright: ignore[reportOverlappingOverload]
        self, key: Key | None, default: D | VT
    ) -> D | VT: ...
    @overload
    def get(self) -> VT: ...
    @overload
    def get(self, **kwargs: VT) -> VT | None: ...
    def get(  # pyright: ignore[reportInconsistentOverload]
        self, key: Key | None = None, default: D | None = None, **kwargs: VT
    ) -> Self | VT | D | Item | dict[str, VT] | PrimitiveValue:
        """
        Retrieves a value from a DotDict.

        Examples:

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
            item = resolve_sentinel(item, default=item, **kwargs)

        if is_mapping(item) and is_sentinel(item, **kwargs):
            item = resolve_sentinel(item, default=default, **kwargs)

        return self.dictize(item)

    def copy(self) -> Self:
        return type(self)(self)

    def delete(self, key: str) -> None:
        """
        Deletes a root or nested key.

        Matching is case-insensitive at every level, including nested plain-dict values.

        Examples:

            >>> r = DotDict({'author': {'name': 'bar', 'url': 'x.com'}})
            >>> r.delete('AUTHOR.NAME')
            >>> r.asdict()
            {'author': {'url': 'x.com'}}

        """

        def reducer(item: Self | None, key: str) -> Self | None:
            if item and key and (matched := match_key(item, key)):
                value = detach_nested(item, matched)
            else:
                value = None

            return cast("Self | None", value)

        keys = parse_key(key)
        rest, last = keys[:-1], keys[-1]

        if len(keys) == 1 and match_key(self, key):
            CaseInsensitiveDict.__delitem__(self, key)  # noqa: PLC2801
        elif (reduced := reduce(reducer, rest, self)) is not None and (
            matched := match_key(reduced, last)
        ) is not None:
            del reduced[matched]

    @overload
    def update(self, data: SupportsKeysAndGetItem[str, VT]) -> None: ...
    @overload
    def update(self, data: SupportsKeysAndGetItem[str, VT], **kwargs: VT) -> None: ...
    @overload
    def update(self, data: DotDictInput[VT]) -> None: ...
    @overload
    def update(self, data: DotDictInput[VT], **kwargs: VT) -> None: ...
    @overload
    def update(self, **kwargs: VT) -> None: ...
    @overload
    def update(self, data: None) -> None: ...
    def update(  # pyright: ignore[reportInconsistentOverload]
        self,
        data: SupportsKeysAndGetItem[str, VT] | DotDictInput[VT] | None = None,
        **kwargs: VT,
    ):
        """
        Updates the DotDict with new data.

        Supports dot notation for nested keys.

        Examples:

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
            data = cast("Mapping[str, VT]", data)
            if self.is_self(data):
                if kwargs:
                    _dict = data | kwargs
                else:
                    return self._store.update(data._store)
            elif kwargs or any("." in k for k in data):
                _dict = {**data, **kwargs}
            else:
                for key, value in data.items():
                    CaseInsensitiveDict.__setitem__(self, key, value)  # noqa: PLC2801

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
        Formats a DotDict as a standard dictionary.

        Examples:

            >>> r = DotDict({'a': {'value': 'bar'}})
            >>> r
            {'a': {'value': 'bar'}}
            >>> r.asdict()
            {'a': {'value': 'bar'}}
            >>> r = DotDict({'a': {'value': 'baz', 'type': 'text'}})
            >>> r
            {'a': 'baz'}
            >>> r.asdict()
            {'a': 'baz'}

        """
        items = gen_dict(self, key=key, default_key="self", **kwargs)
        return dict(items)
