"""
Configuration parsing and per-item resolution helpers.

Examples:

    >>> from riko.parsing import resolve_conf
    >>>
    >>> resolve_conf(conf={"type": "text", "value": "hello"})
    'hello'

Attributes:

    SKIP_SWITCH: Text predicates used by ``get_skip`` configuration rules.

"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, is_dataclass
from time import struct_time
from typing import TYPE_CHECKING, cast

from riko.coercion._freeze import repr_cache
from riko.coercion._sequences import listize
from riko.types._guards import is_mapping, is_sentinel, is_type_value

from ._dotdict import DotDict

if TYPE_CHECKING:
    from _typeshed import DataclassInstance

    from riko.types._collections import RikoValue
    from riko.types._options import SkipIf
    from riko.types._streams import Item, ItemOrValue


SKIP_SWITCH: dict[str, Callable[[str, str], bool]] = {
    "contains": lambda text, value: text.lower() in value.lower(),
    "intersection": lambda text, value: bool(set(text).intersection(value)),
    "search": lambda text, value: re.search(text, value, re.IGNORECASE) is not None,
}


def _conf_is_dynamic_uncached(conf: object, **kwargs: object) -> bool:
    is_dynamic = False

    if isinstance(conf, Mapping):
        if "subkey" in conf or is_sentinel(conf, **kwargs):
            is_dynamic = True
        else:
            values = conf.values()
            is_dynamic = any(_conf_is_dynamic_uncached(v, **kwargs) for v in values)
    elif isinstance(conf, Sequence) and not isinstance(conf, str):
        is_dynamic = any(_conf_is_dynamic_uncached(c, **kwargs) for c in conf)

    return is_dynamic


@repr_cache
def _conf_is_dynamic_cached(conf: object, **kwargs: object) -> bool:
    return _conf_is_dynamic_uncached(conf, **kwargs)


def conf_is_dynamic(conf: object, memoize: bool = False, **kwargs: object) -> bool:
    """
    Reports whether configuration requires per-item parsing.

    Args:

        conf: Configuration value to inspect recursively.
        memoize: Whether to use the representation-based cache.
        **kwargs: Sentinel values used when identifying dynamic configuration.

    Returns:

        ``True`` when ``conf`` contains a subkey or sentinel that depends on an
        input item, otherwise ``False``.

    Examples:

        >>> _conf_is_dynamic_cached.cache_clear()
        >>> conf_is_dynamic({'type': 'text', 'value': 'hello'}, True)
        False
        >>> conf_is_dynamic({'type': 'text', 'subkey': 'title'}, True)
        True
        >>> _ = conf_is_dynamic({'type': 'text', 'value': 'hello'}, True)
        >>> _conf_is_dynamic_cached.cache_info().hits
        1

    """
    func = _conf_is_dynamic_cached if memoize else _conf_is_dynamic_uncached
    return func(conf, **kwargs)


def _parse_conf_uncached[VT](
    item: Item | None = None,
    conf: VT | None = None,
    default: VT | None = None,
    **kwargs: VT,
) -> VT | None:
    parsed = default

    if is_dataclass(conf):
        d_conf: dict[str, VT] | VT | None = asdict(cast("DataclassInstance", conf))
    else:
        d_conf = conf

    dd_conf = DotDict.dictize(d_conf)

    if isinstance(dd_conf, DotDict):
        if subkey := dd_conf.get("subkey"):
            dd_item = DotDict.dictize(item) if item else DotDict()
            parsed = dd_item.get(cast("str", subkey), **kwargs)
        elif is_sentinel(dd_conf, **kwargs) or is_type_value(dd_conf):
            # parsed = next(gen_dict(dd_conf, key=None, default_key=None, **kwargs))
            parsed = cast("DotDict[VT]", dd_conf).get()
        else:
            _parsed = {
                k: _parse_conf_uncached(item, v, **kwargs)
                for k, v in dd_conf.asdict(key=None, **kwargs).items()
            }
            parsed = cast("VT", _parsed)
    elif isinstance(dd_conf, (str, struct_time)):
        parsed = dd_conf
    elif isinstance(dd_conf, (list, tuple)):
        _parsed = [_parse_conf_uncached(item, c, **kwargs) for c in dd_conf]
        parsed = cast("VT", _parsed)
    elif dd_conf is not None:
        parsed = cast("VT", dd_conf)

    return parsed


@repr_cache
def _parse_conf_cached[VT](
    item: Item | None = None,
    conf: VT | None = None,
    default: VT | None = None,
    **kwargs: VT,
) -> VT | None:
    return _parse_conf_uncached(item, conf, default=default, **kwargs)


def resolve_conf[VT](
    item: Item | None = None,
    conf: VT | None = None,
    default: VT | None = None,
    memoize: bool | None = None,
    **kwargs: VT,
) -> VT | None:
    """
    Resolves configuration against an item by expanding subkeys and sentinels.

    Static configurations are memoized by default; ``memoize`` can force or disable
    caching for a specific call.

    Args:

        item: Input item used to resolve subkey references.
        conf: Configuration value to parse recursively.
        default: Value returned when ``conf`` does not produce another value.
        memoize: Explicit cache choice, or ``None`` to cache only static config.
        **kwargs: Sentinel values and options forwarded while resolving config.

    Returns:

        The resolved configuration value, or ``default`` when unresolved.

    Examples:

        >>> param = {
        ...     "key": {"type": "text", "value": "q"},
        ...     "value": {"type": "text", "subkey": "title"}
        ... }
        >>> params = [
        ...     param,
        ...     {
        ...         "key": {"type": "text", "value": "v"},
        ...         "value": {"type": "text", "value": "1.0"}
        ...     }
        ... ]
        >>> conf = {
        ...     "count": {"type": "text", "value": "all"},
        ...     "type": "urlbuilder",
        ...     "BASE": {"type": "text", "value": "http://example.com"},
        ...     "PARAM": params
        ... }
        >>> item = {"title": "the title"}
        >>> parsed = resolve_conf(item, conf=conf, objectify=True)
        >>> parsed["count"], parsed["base"]
        ('all', 'http://example.com')
        >>> parsed["param"]
        [{'key': 'q', 'value': 'the title'}, {'key': 'v', 'value': '1.0'}]
        >>> conf = DotDict({"terminal": "attrs_1", "type": "text"})
        >>> conf.get(attrs_1=iter([{'content': 'baz'}]))
        {'content': 'baz'}
        >>> _parse_conf_cached.cache_clear()
        >>> resolve_conf(conf={'type': 'text', 'value': 'hello'})
        'hello'
        >>> _parse_conf_cached.cache_info().hits
        0
        >>> _ = resolve_conf(conf={'type': 'text', 'value': 'hello'})
        >>> _parse_conf_cached.cache_info().hits
        1
        >>> resolve_conf(conf={'type': 'text', 'value': 'hello'}, memoize=False)
        'hello'
        >>> _parse_conf_cached.cache_info().hits
        1
        >>> _ = resolve_conf(conf={'type': 'text', 'value': 'hello'}, memoize=True)
        >>> _parse_conf_cached.cache_info().hits
        2

    """
    if memoize is None:
        memoize = not conf_is_dynamic(conf, memoize=False, **kwargs)

    func = _parse_conf_cached if memoize else _parse_conf_uncached
    return func(item, conf, default=default, **kwargs)


def get_skip(item: ItemOrValue, skip_if: SkipIf | None = None, **_: object) -> bool:
    """
    Determines whether or not to skip an item.

    Args:

        item: The entry to process.
        skip_if: The skipping criteria.

    Returns:

        Whether or not to skip.

    Examples:

        >>> item = {"content": "Some content"}
        >>> get_skip(item, lambda x: x["content"] == "Some content")
        True
        >>> get_skip(item)
        False
        >>> get_skip(item, {"field": "content"})
        False
        >>> get_skip(item, {"field": "content", "text": None})
        False
        >>> get_skip(item, {"field": "content", "text": 0})
        False
        >>> get_skip(item, {"field": "content", "text": ""})
        True
        >>> get_skip({}, {"field": "content"})
        True
        >>> bool(get_skip(item, {"field": "content", "include": True}))
        True
        >>> get_skip(item, {"field": "content", "text": "some"})
        True
        >>> get_skip(item, {"field": "content", "text": "some", "include": True})
        False
        >>> get_skip(item, {"field": "content", "text": "other"})
        False
        >>> get_skip(item, {"field": "content", "text": "other", "include": True})
        True

    """
    item = item or {}
    skip = False

    if is_mapping(item):
        for _skip in listize(skip_if):
            if callable(_skip):
                skip = _skip(item)
            elif is_mapping(_skip) and (field := _skip["field"]):
                value = item.get(field)

                if (text := _skip.get("text")) is None:
                    skip = bool(value) if _skip.get("include") else not value
                elif value is None:
                    skip = not _skip.get("include")
                else:
                    op = str(_skip.get("op", "contains"))
                    match = SKIP_SWITCH[op](str(text), str(value))
                    skip = not match if _skip.get("include") else match

            if skip:
                break

    return skip


def get_field(
    item: ItemOrValue | None = None, field: str = "", **kwargs: object
) -> ItemOrValue:
    """
    Extracts a configured field from an item.

    Args:

        item: Mapping, ``DotDict``, or scalar value to inspect.
        field: Field name to extract; an empty name returns ``item`` unchanged.
        **kwargs: Dynamic values forwarded to ``DotDict.get``.

    Returns:

        The requested field value, ``None`` when an ordinary mapping lacks the
        field, or ``item`` itself when no field is requested.

    Examples:

        >>> get_field({"title": "hello"}, "title")
        'hello'
        >>> get_field({"title": "hello"})
        {'title': 'hello'}
        >>> get_field({"title": "hello"}, "missing") is None
        True

    """
    if field and isinstance(item, DotDict):
        value = item.get(field, **cast("dict[str, RikoValue]", kwargs))
    elif field and is_mapping(item):
        value = item.get(field)
    else:
        value = item

    return value
