# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.dotdict
~~~~~~~~~~~~
Provides a class for creating case insensitive dicts with dot notation access
"""
from typing import Iterator, Mapping, Optional, Sequence, TypeAlias, TypeGuard, cast as cast_type, Self
import pygogo as gogo

from functools import reduce

from requests.structures import CaseInsensitiveDict
from riko import replacer
from riko.cast import CAST_SWITCH, cast as cast_value
from riko.types import Stream

logger = gogo.Gogo(__name__, monolog=True).logger

BasicValue: TypeAlias = str | int | None
BasicMapping: TypeAlias = Mapping[str, "BasicAnyArg"]
BasicSequence: TypeAlias = Sequence["BasicAnyArg"]
BasicAnyArg: TypeAlias = BasicMapping | BasicSequence | BasicValue

BasicDict: TypeAlias = dict[str, "BasicAnyReturn"]
BasicList: TypeAlias = list["BasicAnyReturn"]
BasicAnyReturn: TypeAlias = BasicDict | BasicList | BasicValue

SENTINALS = ("terminal",)


def is_mapping_seq(val: BasicSequence) -> TypeGuard[Sequence[BasicDict]]:
    return isinstance(val[0], Mapping)


def is_value_seq(val: BasicSequence) -> TypeGuard[Sequence[BasicValue]]:
    return isinstance(val[0], BasicValue)


def is_sentinal(val: BasicAnyArg) -> TypeGuard[dict[str, str]]:
    return isinstance(val, Mapping) and len(val) == 2 and any(s in val for s in SENTINALS)


class DotDict(CaseInsensitiveDict[BasicAnyArg]):
    """A dictionary whose keys can be accessed using dot notation

    Examples:
        >>> r = DotDict({'a': {'content': 'value'}})
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
        >>> r = DotDict({'value': {'terminal': 'attrs_1_value', 'type': 'text'}, 'key': 'title'})
        >>> list(r)
        ['value', 'key']
        >>> [k for k in r]
        ['value', 'key']

    """
    def __init__(self, data=None, **kwargs):
        super().__init__(data, **kwargs)
        self.update(data)

    def _parse_key(self, key: Optional[str | Mapping[str, str]] = None) -> list[str]:
        if isinstance(key, str):
            keys = key.rstrip(".").split(".") if key else []
        elif key and "subkey" in key:
            keys = [key["subkey"]]
        else:
            keys = []

        return keys

    def _parse_sentinel(self, *args: BasicAnyArg, **kwargs: BasicAnyArg) -> BasicAnyArg:
        value = args[0]
        default: BasicAnyArg = kwargs.pop("default", None)

        if kwargs and is_sentinal(value):
            key = next(s for s in SENTINALS if s in value)
            sentinal = value[key]
            replaced = replacer(sentinal, "")
            stream = cast_type(Stream, kwargs[replaced])

            if callable(stream):
                item = next(stream(**kwargs))
            else:
                item = next(stream)

            if "path" in value:
                content_path = value["path"]
            elif isinstance(item, Mapping):
                content_path = "content"
            else:
                content_path = None

            parsed = item[content_path] if content_path else item
        elif isinstance(value, Mapping) and set(value) == {"value", "type"}:
            parsed = value["value"]
            _type = value["type"]

            if parsed and isinstance(_type, str) and _type in CAST_SWITCH:
                parsed = cast_value(parsed, _type=_type)
        else:
            parsed = default
        return parsed

    def _parse_value(
        self,
        value: BasicAnyArg,
        key: str | int,
        default: Optional[BasicValue] = None,
        **kwargs
    ) -> BasicAnyArg:
        parsed = default
        msg = f"Ignoring unsupported key {key} to access {{0}} value {{1}}."

        if isinstance(value, Mapping) and isinstance(key, str):
            value = DotDict(value)

            if key in value:
                parsed = value[key]
            elif is_sentinal(value):
                parsed = self._parse_sentinel(value, default=default, **kwargs)
        elif isinstance(value, Mapping):
            logger.warning(msg.format("mapping", value))
        elif isinstance(value, (str, int)):
            parsed = value
        elif isinstance(value, Sequence) and is_mapping_seq(value):
            if isinstance(key, int):
                logger.warning(msg.format("submapping", value[0]))
            else:
                parsed = [v[key] for v in value]
        elif isinstance(value, Sequence) and is_value_seq(value):
            if isinstance(key, str):
                logger.warning(msg.format("submapping", value[0]))
            else:
                parsed = value[key]
        elif value is not None:
            logger.warning(f"Setting to unsupported value type {type(value)}.")
            parsed = value

        return parsed

    def __getitem__(self, key: str) -> BasicAnyArg:
        """
        >>> r = DotDict({'key': 'bar'})
        >>> r['key']
        'bar'
        >>> r['KEY']
        'bar'
        """
        keys = self._parse_key(key)
        value = super().__getitem__(keys[0])

        if len(keys) > 1:
            key = ".".join(keys[1:])
            msg = f"Ignoring unsupported key {key} to access non-mapping value {value}."

            if isinstance(value, Mapping):
                value = value[key]
            else:
                logger.warning(msg)

        value = self._parse_sentinel(value, default=value)
        result = DotDict(value) if hasattr(value, "keys") else value
        return result

    def get(self, key=None, default=None, **kwargs) -> BasicAnyArg | Self:
        """
        >>> r = DotDict({'key': 'bar'})
        >>> r.get('key')
        'bar'
        >>> r.get('KEY')
        'bar'
        >>> r.get('baz')
        >>> attrs = {
        ...     "value": {"terminal": "attrs_1", "type": "text"},
        ...     "key": {"type": "text", "value": "title"},
        ... }
        >>> r = DotDict({'attrs': attrs})
        >>> r.get('attrs')
        {'value': {'terminal': 'attrs_1', 'type': 'text'}, 'key': 'title'}
        >>> r.get('attrs.key')
        'title'
        >>> r.get('attrs.value.content', attrs_1=iter([{'content': 'baz'}]))
        'baz'
        """
        keys = self._parse_key(key)
        # TODO: figure out if the copy is necessary
        item = DotDict(self.copy())

        if keys:
            for k in keys:
                try:
                    k = int(k)
                except ValueError:
                    pass

                item = self._parse_value(item, k, default=default, **kwargs)
        else:
            item = self._parse_sentinel(item, default=item, **kwargs)

        value = DotDict(item) if hasattr(item, "keys") else item

        return value

    def delete(self, key: str):
        reducer = lambda i, k: DotDict(i.get(k))
        keys = self._parse_key(key)
        rest, last = keys[:-1], keys[-1]
        reduced = reduce(reducer, rest, DotDict(self))

        try:
            _key = reduced[last]
        except KeyError:
            pass
        else:
            del _key

    # TODO: does this need to be __setitem__?
    def set(self, key, value):
        reducer = lambda i, k: i.setdefault(k, {})
        keys = self._parse_key(key)
        item = self.copy()
        rest, last = keys[:-1], keys[-1]
        reduced = reduce(reducer, rest, item)
        reduced[last] = value
        super().update(item)

    def update(self, data=None, **kwargs):
        _dict = dict(data or {})
        _dict.update(kwargs)
        dot_keys = [d for d in _dict if "." in d]

        if dot_keys:
            # skip key if a subkey redefines it
            # i.e., 'author.name' has precedence over 'author'
            keys = [".".join(self._parse_key(key)[:-1]) for key in dot_keys]
            items = ((k, v) for k, v in _dict.items() if k not in keys)
        else:
            items = _dict.items()

        [self.set(key, value) for key, value in items]

    def asdict(self, **kwargs) -> dict[str, BasicAnyArg] | BasicAnyArg:
        """
        >>> DotDict({'a': {'value': 'bar'}}).asdict()
        {'a': {'value': 'bar'}}
        >>> DotDict({'a': {'value': 'baz', 'type': 'string'}}).asdict()
        {'a': 'baz'}
        """
        value = self.get(**kwargs)

        if isinstance(value, DotDict):
            result = {k: DotDict(v).asdict(**kwargs) if hasattr(v, "keys") else v for k, v in value.items()}
        else:
            result = value

        return result
