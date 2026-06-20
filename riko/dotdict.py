# vim: sw=4:ts=4:expandtab
"""
Provides a class for creating case insensitive dicts with dot notation access
"""

from collections.abc import Iterator, Mapping, Sequence
from functools import reduce
from time import struct_time
from typing import TypeGuard, Union
from typing import cast as cast_type

import pygogo as gogo
from requests.structures import CaseInsensitiveDict
from typing_extensions import TypeIs

from riko import Objectify, replacer
from riko.cast import CAST_SWITCH, CastType
from riko.cast import cast as cast_value
from riko.types.compile import Wire, WireEndpoint
from riko.types.general import Stream
from riko.types.modules import ConfArg, Sentinal
from riko.types.values import (
    BasicValue,
    ComplexArg,
    ComplexMapping,
    ComplexSequence,
    IntermediateValue,
    StatefulItem,
    StreamState,
)

logger = gogo.Gogo(__name__, monolog=True).logger


SENTINALS = ("terminal",)
TV_KEYS = ("type", "value")
WIRE_KEYS = ("id", "src", "tgt")


def is_mapping(val: ComplexArg | WireEndpoint) -> TypeIs[Mapping]:
    return isinstance(val, (dict, CaseInsensitiveDict))


def is_mapping_seq(val: ComplexArg) -> TypeIs[Sequence[Mapping]]:
    return isinstance(val, Sequence) and isinstance(val[0], Mapping)


def is_value_seq(val: ComplexArg) -> TypeIs[Sequence[BasicValue]]:
    return isinstance(val, Sequence) and isinstance(val[0], BasicValue)


def is_sentinal(val: ComplexArg) -> TypeIs[Mapping[str | Sentinal, str]]:
    return (
        isinstance(val, (dict, CaseInsensitiveDict))
        and len(val) == 2
        and "terminal" in val
    )


def is_type_value(val: ComplexArg) -> TypeGuard[ConfArg]:
    if not isinstance(val, (dict, CaseInsensitiveDict)):
        result = False
    else:
        n = len(val)
        double = n == 2 and "type" in val and "value" in val
        result = double or (n == 1 and "value" in val)

    return result


def is_wire(val: ComplexArg) -> TypeGuard[Wire]:
    if is_mapping(val) and len(val) == 3 and all(s in val for s in WIRE_KEYS):
        success = is_mapping(val["src"]) and is_mapping(val["tgt"])
    else:
        success = False

    return success


def is_stateful_item(val: ComplexArg) -> TypeGuard[StatefulItem]:
    if (
        isinstance(val, (dict, CaseInsensitiveDict))
        and len(val) == 1
        and "state" in val
    ):
        success = isinstance(val["state"], StreamState)
    else:
        success = False

    return success


class DotDict(CaseInsensitiveDict[ComplexArg]):
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

    Warning:
        Do NOT pass data as keyword arguments.

            >>> DotDict(**{'a': 1, 'b': 2})
            Traceback (most recent call last):
                ...
            TypeError: DotDict.__init__() got an unexpected keyword argument 'a'
            >>> DotDict({'a': 1, 'b': 2})
            {'a': 1, 'b': 2}

    """

    def __init__(self, data: ComplexMapping | None = None):
        super().__init__()

        if isinstance(data, Objectify):
            _data = data.iteritems()
        elif isinstance(data, Mapping):
            # pyright doesn't like typeddicts
            _data = cast_type(dict[str, ComplexArg], data)
        else:
            _data = data

        if _data:
            self.update(_data)

    def _parse_key(self, key: str | Mapping[str, str] | None = None) -> list[str]:
        if isinstance(key, str):
            if not key:
                keys = []
            elif "." not in key:
                keys = [key]
            else:
                keys = key.rstrip(".").split(".")
        elif key and "subkey" in key:
            keys = [key["subkey"]]
        else:
            keys = []

        return keys

    def _parse_sentinel(
        self, value: ComplexArg, default: ComplexArg | None = None, **kwargs: ComplexArg
    ) -> ComplexArg:
        if not isinstance(value, (dict, CaseInsensitiveDict)):
            parsed = default
        elif kwargs and is_sentinal(value):
            key = next(s for s in SENTINALS if s in value)
            sentinal = value[key]
            replaced = replacer(sentinal, "")

            if stream := kwargs.get(replaced):
                stream = cast_type(Stream, stream)
                item = next(stream)
                parsed = item
            else:
                parsed = default
        elif is_type_value(value):
            parsed = value["value"]

            if not (_type := value.get("type")):
                pass
            elif _type == CastType.LOCATION:
                logger.warning(f"Location type not supported! Not casting {parsed=}.")
            elif _type in CAST_SWITCH:
                _parsed = cast_value(parsed, _type=CastType(_type))
                parsed = cast_type(IntermediateValue, _parsed)
            elif _type != "module":
                logger.warning(f"Invalid cast type={_type}! Not casting {parsed=}.")
        elif is_stateful_item(value):
            parsed = value
        elif isinstance(value, (dict, CaseInsensitiveDict)):
            parsed = {
                k: self._parse_sentinel(
                    cast_type(ComplexArg, v), cast_type(ComplexArg, v), **kwargs
                )
                for k, v in value.items()
            }
        else:
            parsed = default

        return parsed

    def _parse_value(
        self,
        value: ComplexArg,
        key: str | int,
        default: ComplexArg | None = None,
        **kwargs,
    ) -> ComplexArg:
        parsed = default
        msg = f"Ignoring unsupported key {key} to access {{0}} value {{1}}."

        if isinstance(value, Mapping) and isinstance(key, str):
            dd_value = value if isinstance(value, DotDict) else DotDict(value)

            if key in dd_value:
                parsed = dd_value[key]
            elif kwargs and is_sentinal(value):
                parsed = self._parse_sentinel(value, default=default, **kwargs)

                if key and is_mapping(parsed) and key in parsed:
                    parsed = parsed[key]
                elif key:
                    parsed = default
        elif isinstance(value, (str, int, struct_time)):
            parsed = value
        elif isinstance(value, Mapping):
            logger.warning(msg.format("Mapping", value))
        elif isinstance(value, Objectify):
            logger.warning(msg.format("Objectify", value))
        elif is_mapping_seq(value) and isinstance(key, str):
            parsed = [v[key] for v in value]
        elif is_mapping_seq(value):
            logger.warning(msg.format("submapping", value[0]))
        elif is_value_seq(value) and isinstance(key, int):
            parsed = value[key]
        elif is_value_seq(value):
            logger.warning(msg.format("submapping", value[0]))
        elif isinstance(value, Sequence):
            parsed = list(value)
        elif value is not None:
            parsed = value

        return parsed

    def __getitem__(self, key: str) -> ComplexArg:
        """
        >>> r = DotDict({'key': 'bar'})
        >>> r['key']
        'bar'
        >>> r['KEY']
        'bar'
        """
        keys = self._parse_key(key)
        value = CaseInsensitiveDict.__getitem__(self, keys[0])

        if len(keys) > 1:
            key = ".".join(keys[1:])
            msg = f"Ignoring unsupported key {key} to access non-mapping value {value}."

            if isinstance(value, Mapping):
                value = value[key]
            else:
                logger.warning(msg)

        if isinstance(value, (dict, CaseInsensitiveDict)):
            value = self._parse_sentinel(value, default=value)
            result = (
                DotDict(value)
                if isinstance(value, (dict, CaseInsensitiveDict))
                else value
            )
        else:
            result = value

        return result

    def get(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        key: str | Mapping[str, str] | None = None,
        default: ComplexArg | None = None,
        **kwargs,
    ) -> Union["DotDict", IntermediateValue, ComplexSequence]:
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
        """
        keys = self._parse_key(key)
        item = self
        if keys:
            for k in keys:
                try:
                    k = int(k)
                except ValueError:
                    pass

                item = self._parse_value(item, k, default=default, **kwargs)
        else:
            item = self._parse_sentinel(item, default=item, **kwargs)

        if kwargs and is_sentinal(item):
            item = self._parse_sentinel(item, default=default, **kwargs)

        if isinstance(item, (Mapping, Objectify)):
            value = DotDict(item)
        else:
            value = item

        return value

    def delete(self, key: str):
        reducer = lambda i, k: DotDict(i.get(k))
        keys = self._parse_key(key)
        rest, last = keys[:-1], keys[-1]
        reduced = reduce(reducer, rest, self)

        try:
            _key = reduced[last]
        except KeyError:
            pass
        else:
            del _key

    # TODO: does this need to be __setitem__?
    def __setitem__(self, key: str, value: ComplexArg):
        reducer = lambda i, k: i.setdefault(k, {})
        keys = self._parse_key(key)

        if len(keys) == 1:
            CaseInsensitiveDict.__setitem__(self, key, value)
        else:
            item = self.copy()
            rest, last = keys[:-1], keys[-1]
            reduced = reduce(reducer, rest, item)
            reduced[last] = value
            CaseInsensitiveDict.update(self, item)

    def update(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        data: ComplexMapping | Iterator[tuple[str, ComplexArg]] | None = None,
        **kwargs,
    ):
        if not kwargs and isinstance(data, dict) and not any("." in k for k in data):
            for key, value in data.items():
                CaseInsensitiveDict.__setitem__(self, key, value)

            return
        elif isinstance(data, Objectify):
            _dict = dict(data.iteritems())
        elif isinstance(data, Mapping):
            # pyright doesn't like typeddicts
            _dict = cast_type(dict[str, ComplexArg], data)
        elif data:
            _dict = dict(data)
        else:
            _dict: dict[str, ComplexArg] = {}

        _dict.update(kwargs)

        if dot_keys := [d for d in _dict if "." in d]:
            skip_keys = {".".join(self._parse_key(key)[:-1]) for key in dot_keys}
            items = [(k, _dict[k]) for k in _dict if k not in skip_keys]
        else:
            items = _dict.items()

        for key, value in items:
            self[key] = value

    def asdict(self, default_key="self", **kwargs) -> dict[str, ComplexArg]:
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
        if kwargs:
            value = self.get(**kwargs)

            if isinstance(value, Mapping):
                result = {
                    k: DotDict(v).get(**kwargs) if isinstance(v, Mapping) else v
                    for k, v in value.items()
                }
            elif value:
                result = {default_key: value}
            else:
                result: dict[str, ComplexArg] = {}
        else:
            result = {}

            for k in self:
                raw = CaseInsensitiveDict.__getitem__(self, k)

                if isinstance(raw, (dict, CaseInsensitiveDict)):
                    processed = self._parse_sentinel(raw, default=raw)
                    result[k] = (
                        DotDict(processed).asdict()
                        if isinstance(processed, (dict, CaseInsensitiveDict))
                        else processed
                    )
                else:
                    result[k] = raw

        return dict(result)
