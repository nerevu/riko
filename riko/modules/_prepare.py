# vim: sw=4:ts=4:expandtab
"""
riko.modules._prepare
~~~~~~~~~~~~~~~~~~~~~~
Module preparation and per-item dispatch: the frozen ``PreparedModule`` record,
conf merging/extraction, and the parser/caster construction that turns opts and
conf into the callables a wrapper applies to each item.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import partial
from typing import cast, overload

import pygogo as gogo

from riko._iterutils import broadcast, dispatch, listize
from riko._objectify import objectify
from riko.cast import (
    CAST_SWITCH,
    BasicCastType,
    CastType,
    cast_none,
    cast_pass,
    cast_value,
)
from riko.dotdict import DotDict, is_mapping
from riko.parsers import conf_is_dynamic, get_field, parse_conf
from riko.types._collections import BasicReturn, RikoDict, RikoList, RikoValue
from riko.types._dynamic_conf import DynamicConf
from riko.types._options import (
    Casted,
    Defaults,
    ItemDispatch,
    ItemOrValueDispatch,
    Opts,
    ValueDispatch,
)
from riko.types._scalars import PrimitiveValue
from riko.types._streams import Item, ItemOrValue
from riko.types._wrappers import (
    ArgCaster,
    CastFuncs,
    ParseFuncs,
    ParserOutput,
    SyncConfCastFunc,
)
from riko.types.modules import AnyModuleConf, Conf

logger = gogo.Gogo(__name__, monolog=True).logger

SyncArgFunc = ArgCaster


def require_kwarg[T](  # noqa: E704
    kwargs: Mapping[str, object], name: str, pipe: str, strict: bool = False
) -> T:  # pyright: ignore[reportInvalidTypeVarUse]
    """
    Returns a required pipe argument, or reports which one is unusable.

    A missing operand is a call-site programming error, so this raises rather
    than degrading. ``None`` counts as missing: the collection API always
    populates keys such as ``others``/``func`` in ``kwargs``, so checking only
    for an absent key would never fire through ``SyncPipe``.

    Args:
        kwargs: The keyword arguments the pipe was called with.

        name: The argument that must be present.

        pipe: The pipe name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. an empty
            ``others`` list that would publish to nobody. Use it only where a
            falsy value can never be legitimate — never on an argument for
            which ``0``, ``False`` or ``""`` is a real value (default: False).

    Returns:
        The value bound to ``name``.

    Raises:
        TypeError: If ``name`` is absent or ``None``, or is falsy under
            ``strict``.

    Examples:
        >>> require_kwarg({"func": len}, "func", "udf")
        <built-in function len>
        >>> require_kwarg({}, "func", "udf")
        Traceback (most recent call last):
            ...
        TypeError: the 'udf' pipe requires the 'func' keyword argument

        A falsy value passes unless ``strict`` is set:

        >>> require_kwarg({"others": []}, "others", "send")
        []
        >>> require_kwarg({"others": []}, "others", "send", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'send' pipe requires the 'others' keyword argument

    """
    value = kwargs.get(name)

    if (value is None) or (strict and not value):
        raise TypeError(f"the {pipe!r} pipe requires the {name!r} keyword argument")

    return cast(T, value)


def require_conf[T](  # noqa: E704
    objconf: DynamicConf, key: str, pipe: str, strict: bool = False
) -> T:  # pyright: ignore[reportInvalidTypeVarUse]
    """
    Returns a required conf value, or reports which one is unusable.

    A missing conf key is a call-site programming error, so this raises rather
    than degrading — unlike an absent *field* on an item, which is a runtime
    data condition and is skipped.

    Args:
        objconf: The parsed pipe configuration.

        key: The conf key that must be set.

        pipe: The pipe name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. a ``url``
            set to ``""``. Use it only where a falsy value can never be
            legitimate — never on a key for which ``0``, ``False`` or ``""`` is
            a real value (default: False).

    Returns:
        The value bound to ``key``.

    Raises:
        TypeError: If ``key`` is absent or ``None``, or is falsy under
            ``strict``.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> require_conf(Objectify({"url": "x"}), "url", "csv")
        'x'
        >>> require_conf(Objectify({}), "url", "csv")
        Traceback (most recent call last):
            ...
        TypeError: the 'csv' pipe requires the 'url' conf key

        A falsy value passes unless ``strict`` is set:

        >>> require_conf(Objectify({"url": ""}), "url", "csv")
        ''
        >>> require_conf(Objectify({"url": ""}), "url", "csv", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'csv' pipe requires the 'url' conf key

    """
    value = getattr(objconf, key, None)

    if (value is None) or (strict and not value):
        raise TypeError(f"the {pipe!r} pipe requires the {key!r} conf key")

    return cast(T, value)


def get_pieces_or_conf(
    parsed_conf: AnyModuleConf | None, defaults: Defaults, opts: Opts, pipe: str = ""
) -> tuple[BasicReturn | AnyModuleConf | list[BasicReturn] | None, AnyModuleConf]:
    if is_mapping(parsed_conf):
        merged_conf = cast(AnyModuleConf, {**defaults, **parsed_conf})
    else:
        merged_conf = cast(AnyModuleConf, defaults)

    if extract := opts.get("extract"):
        try:
            pieces = next(v for k, v in merged_conf.items() if k.lower() == extract)
        except StopIteration:
            label = f"the {pipe!r} pipe" if pipe else "this pipe"
            raise TypeError(f"{label} requires the {extract!r} conf key") from None
        else:
            pieces = cast(BasicReturn, pieces)

        if pieces and opts.get("listize"):
            pieces_or_conf = cast(list[BasicReturn], listize(pieces))
        else:
            pieces_or_conf = pieces
    else:
        pieces_or_conf = merged_conf

    return pieces_or_conf, merged_conf


@dataclass(frozen=True)
class PreparedModule[T, E]:
    name: str
    conf: Conf
    opts: Opts
    parsers: ParseFuncs
    casters: CastFuncs[ItemOrValue, E]
    assign: str
    emit: bool | Callable[[ParserOutput], bool] | None
    is_source: bool
    static_casted: tuple[ArgCaster[T], E, DynamicConf] | None


@overload
def parse_and_cast[T, E](  # noqa: E704
    item: Item | RikoDict | DotDict[RikoValue],
    opts: Opts,
    conf: Conf,
    *,
    parsers: ParseFuncs,
    casters: CastFuncs[T, E],
    defaults: Defaults | None = ...,
    field: str | None = ...,
    pipe: str = ...,
    **kwargs: object,
) -> ItemDispatch[T, E]: ...
@overload  # noqa: E302
def parse_and_cast[T, E](  # noqa: E704
    item: PrimitiveValue | RikoList,
    opts: Opts,
    conf: Conf,
    *,
    parsers: ParseFuncs,
    casters: CastFuncs[T, E],
    defaults: Defaults | None = ...,
    field: str | None = ...,
    pipe: str = ...,
    **kwargs: object,
) -> ValueDispatch[T, E]: ...
def parse_and_cast[T, E](  # noqa: E302
    item: ItemOrValue,
    opts: Opts,
    conf: Conf,
    *,
    parsers: ParseFuncs,
    casters: CastFuncs[T, E],
    defaults: Defaults | None = None,
    field: str | None = None,
    pipe: str = "",
    **kwargs: object,
) -> ItemOrValueDispatch[T, E]:
    defaults = defaults or Defaults({})
    field = field or opts.get("field")

    if parsers:
        parsed_field, _parsed_conf = broadcast(item, *parsers, field=field, **kwargs)
    else:
        parsed_field, _parsed_conf = item, conf

    parsed_conf = cast(AnyModuleConf, _parsed_conf)
    pieces_or_conf, merged_conf = get_pieces_or_conf(parsed_conf, defaults, opts, pipe)
    parsed = (parsed_field, pieces_or_conf, merged_conf)
    casted = dispatch(parsed, *casters) if casters else parsed
    _conf = cast(DynamicConf, casted[2])

    if is_mapping(item):
        dispatched = ItemDispatch(item, Casted(casted[0], casted[1], _conf))
    else:
        dispatched = ValueDispatch(item, Casted(casted[0], casted[1], _conf))

    return dispatched


def get_parsers(opts: Opts, conf: Conf, **kwargs: object) -> tuple[ParseFuncs, bool]:
    is_dynamic = False

    if opts.get("ftype") == BasicCastType.NONE:
        field_parser = cast_none
    else:
        field_parser = partial(get_field)

    if opts.get("ptype") == BasicCastType.NONE:
        conf_parser = cast_none
    elif conf_is_dynamic(conf, memoize=False, **kwargs):
        conf_parser = partial(parse_conf, conf=conf, memoize=False)
        is_dynamic = True
    else:
        pre_parsed = parse_conf(None, conf=conf, memoize=True)
        conf_parser = lambda _, **__: pre_parsed

    return ParseFuncs(field_parser, conf_parser), is_dynamic


def get_casters(opts: Opts) -> CastFuncs:
    ftype = opts.get("ftype")
    ptype = opts.get("ptype")
    extract = opts.get("extract")

    if ftype in CAST_SWITCH:
        _field_func = partial(cast_value, type_=CastType(ftype))
    else:
        if ftype:
            logger.warning(f"Invalid cast {ftype=}. Ignoring.")

        _field_func = cast_pass

    field_func = cast(SyncArgFunc, _field_func)

    if ptype in CAST_SWITCH:
        _caster = partial(cast_value, type_=CastType(ptype))
    else:
        if ptype:
            logger.warning(f"Invalid cast {ptype=}. Ignoring.")

        _caster = cast_pass

    caster = cast(SyncArgFunc, _caster)

    if ptype == BasicCastType.NONE:
        extract_caster = cast_none
        _conf_caster = cast_pass
    elif opts.get("listize") and opts.get("objectify"):
        extract_caster = lambda pieces: [objectify(piece, caster) for piece in pieces]
        _conf_caster = objectify
    elif opts.get("objectify"):
        extract_caster = partial(objectify, func=caster)
        _conf_caster = objectify if extract else partial(objectify, func=caster)
    else:
        extract_caster = caster
        _conf_caster = cast_pass

    conf_caster = cast(SyncConfCastFunc, _conf_caster)
    return CastFuncs(field_func, extract_caster, conf_caster)
