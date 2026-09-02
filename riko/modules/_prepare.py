# vim: sw=4:ts=4:expandtab
"""
riko.modules._prepare
~~~~~~~~~~~~~~~~~~~~~~

Module preparation and per-item dispatch: the frozen ``PreparedModule`` record,
conf merging/extraction, and the parser/caster construction that turns opts and
conf into the callables a wrapper applies to each item.
"""

from collections.abc import Callable
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
from riko.types._locations import AnyLocation
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


def require_arg[T](value: T | None, name: str, pipe: str, strict: bool = False) -> T:
    """
    Narrows a required pipe argument, or reports which one is unusable.

    A known pipe argument lives in the parser signature typed ``T | None`` and
    defaulting to ``None``: optional to Python so Riko can raise its own
    meaningful missing-argument error, required to Riko. This validates that
    runtime invariant — ``None`` means the argument was not supplied — and
    narrows ``T | None`` to ``T``. A missing operand is a call-site programming
    error, so this raises rather than degrading.

    Args:
        value: The supplied argument value, or ``None`` when omitted.

        name: The argument being validated, used in the error message.

        pipe: The pipe name, used in the error message.

        strict: Whether to also reject a present but falsy value, e.g. an empty
            ``others`` list that would publish to nobody. Use it only where a
            falsy value can never be legitimate — never on an argument for
            which ``0``, ``False`` or ``""`` is a real value (default: False).

    Returns:
        The value, narrowed to ``T``.

    Raises:
        TypeError: If ``value`` is ``None``, or is falsy under ``strict``.

    Examples:
        >>> require_arg(len, "func", "udf")
        <built-in function len>
        >>> require_arg(None, "func", "udf")
        Traceback (most recent call last):
            ...
        TypeError: the 'udf' pipe requires the 'func' keyword argument

        A falsy value passes unless ``strict`` is set:

        >>> require_arg([], "others", "send")
        []
        >>> require_arg([], "others", "send", strict=True)
        Traceback (most recent call last):
            ...
        TypeError: the 'send' pipe requires the 'others' keyword argument

    """
    if (value is None) or (strict and not value):
        raise TypeError(f"the {pipe!r} pipe requires the {name!r} keyword argument")

    return value


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
    parsed_conf: AnyModuleConf | Conf | None,
    defaults: Defaults,
    opts: Opts,
    pipe: str = "",
) -> tuple[BasicReturn | AnyModuleConf | list[BasicReturn] | None, AnyModuleConf]:
    """
    Merges conf over defaults and optionally extracts a single conf value.

    When ``opts`` names an ``extract`` key, that key's value is pulled out (and
    list-wrapped if ``listize`` is set); otherwise the whole merged conf is
    returned. Both the extracted-or-merged value and the merged conf are handed
    back so the caller keeps access to the full conf.

    Args:
        parsed_conf: The per-item parsed conf, or ``None``.
        defaults: The module's default conf.
        opts: The decoration options (``extract``/``listize``).
        pipe: The pipe name, used in the error message.

    Returns:
        The extracted value or merged conf, paired with the merged conf.

    Raises:
        TypeError: When ``extract`` names a key absent from the merged conf.

    """
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

        pieces_or_conf = listize(pieces) if opts.get("listize") else pieces
    else:
        pieces_or_conf = merged_conf

    return pieces_or_conf, merged_conf


@dataclass(frozen=True)
class PreparedModule[T, E]:
    """
    Immutable per-call invocation state for a module.

    Built once per pipe call by ``Module.prepare`` and shared across the
    ``setup``/``process`` steps. Frozen so concurrent invocations and differing
    call-site options never overwrite one another.

    Attributes:
        name: The module name.
        conf: The merged pipe configuration.
        opts: The resolved decoration/call options.
        parsers: The field and conf parsers.
        casters: The field, extract, and conf casters.
        assign: The field results are assigned to.
        emit: Whether — or a predicate deciding whether — to emit rather than
            assign.
        is_source: Whether the pipe is a source (``ftype`` is ``"none"``).
        static_casted: Precomputed cast for conf that does not vary per item, or
            ``None`` when the conf is dynamic.

    """

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
    """
    Parses and casts one item's field and conf into a dispatch record.

    Runs the field/conf parsers over the item, resolves the extract-or-conf via
    ``get_pieces_or_conf``, applies the casters, and wraps the result as an item
    or value dispatch depending on whether the input is a mapping.

    Args:
        item: The input item or value.
        opts: The resolved options.
        conf: The merged pipe configuration.
        parsers: The field and conf parsers.
        casters: The field, extract, and conf casters.
        defaults: The module's default conf.
        field: Optional field whose value replaces the item.
        pipe: The pipe name, used in error messages.
        **kwargs: Extra options forwarded to the parsers.

    Returns:
        An item or value dispatch pairing the original item with its cast pieces.

    """
    defaults = defaults or Defaults({})
    field = field or opts.get("field")

    if parsers:
        parsed_field, parsed_conf = broadcast(item, *parsers, field=field, **kwargs)
    else:
        parsed_field, parsed_conf = item, conf

    pieces_or_conf, merged_conf = get_pieces_or_conf(parsed_conf, defaults, opts, pipe)
    parsed = (parsed_field, pieces_or_conf, merged_conf)
    casted = dispatch(parsed, *casters) if casters else parsed

    if is_mapping(item):
        dispatched = ItemDispatch(item, Casted(*casted))
    else:
        dispatched = ValueDispatch(item, Casted(*casted))

    return dispatched


def get_parsers(opts: Opts, conf: Conf, **kwargs: object) -> tuple[ParseFuncs, bool]:
    """
    Builds the field and conf parsers for a module, detecting dynamic conf.

    A ``none`` ftype/ptype yields a null parser. A conf that varies per item is
    parsed lazily per call (dynamic); otherwise it is parsed once and memoized.

    Args:
        opts: The decoration options (``ftype``/``ptype``).
        conf: The merged pipe configuration.
        **kwargs: Extra options forwarded to dynamic-conf detection.

    Returns:
        The field/conf parsers, and whether the conf is dynamic (per-item).

    """
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


@overload
def _get_caster[T](type_: None) -> ArgCaster[T]: ...  # noqa: E704
@overload
def _get_caster(type_: BasicCastType) -> ArgCaster[ItemOrValue]: ...  # noqa: E704
@overload  # noqa: E302
def _get_caster(  # noqa: E704
    type_: CastType,
) -> ArgCaster[ItemOrValue | AnyLocation]: ...
def _get_caster[T](  # noqa: E302
    type_: BasicCastType | CastType | None,
) -> ArgCaster[T | PrimitiveValue | AnyLocation]:
    """
    Builds a caster for a destination type, degrading on an unknown one.

    An unrecognized ``type_`` logs a warning and falls back to ``cast_pass``
    (pass-through) rather than raising.

    Args:
        type_: The destination cast type, or ``None`` for pass-through.

    Returns:
        A caster callable taking content and optional kwargs.

    """
    if type_ in CAST_SWITCH:
        cast_type = CastType(type_)

        def caster(content: T, **kwargs: object) -> T | PrimitiveValue | AnyLocation:
            return cast_value(content, cast_type, **kwargs)
    else:
        if type_:
            logger.warning(f"Invalid cast {type_=}. Ignoring.")

        caster = cast_pass

    return caster


def get_casters(opts: Opts) -> CastFuncs[ItemOrValue, object]:
    """
    Builds the field, extract, and conf casters from a module's options.

    Honors ``ftype``/``ptype`` for the field and extract casters and combines
    ``objectify``/``listize`` to decide how extract and conf are cast; a ``none``
    ptype disables casting for both.

    Args:
        opts: The decoration options (``ftype``/``ptype``/``extract``/
            ``listize``/``objectify``).

    Returns:
        The field, extract, and conf casters.

    """
    ftype = opts.get("ftype")
    ptype = opts.get("ptype")
    extract = opts.get("extract")

    field_caster = _get_caster(ftype)
    value_caster = _get_caster(ptype)

    if ptype == BasicCastType.NONE:
        extract_caster: ArgCaster[object] = cast_none
        _conf_caster = cast_pass
    elif opts.get("listize") and opts.get("objectify"):
        extract_caster = lambda pieces: [
            objectify(piece, value_caster) for piece in pieces
        ]
        _conf_caster = objectify
    elif opts.get("objectify"):
        extract_caster = partial(objectify, func=value_caster)
        _conf_caster = objectify if extract else partial(objectify, func=value_caster)
    else:
        extract_caster = value_caster
        _conf_caster = cast_pass

    conf_caster = cast(SyncConfCastFunc, _conf_caster)
    return CastFuncs(field_caster, extract_caster, conf_caster)
