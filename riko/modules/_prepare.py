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
from typing import cast as cast_type

import pygogo as gogo

from riko import listize, objectify
from riko.cast import CAST_SWITCH, BasicCastType, CastType, cast_none, cast_pass
from riko.cast import cast as cast_value
from riko.dotdict import DotDict, is_mapping
from riko.parsers import conf_is_dynamic, get_field, parse_conf
from riko.types.general import (
    Casted,
    CastFuncs,
    Conf,
    Defaults,
    Dispatched,
    Item,
    Opts,
    ParseFuncs,
    ParserOutput,
    SyncArgFunc,
    SyncConfCastFunc,
)
from riko.types.values import BasicReturn
from riko.utils import broadcast, dispatch

logger = gogo.Gogo(__name__, monolog=True).logger


def get_pieces_or_conf(
    parsed_conf: object, defaults: Defaults, opts: Opts
) -> tuple[
    BasicReturn | Conf | list[BasicReturn] | Defaults | None,
    Conf | Defaults,
]:
    if is_mapping(parsed_conf):
        merged_conf = cast_type(Conf, {**defaults, **parsed_conf})
    else:
        merged_conf = defaults

    if extract := opts.get("extract"):
        try:
            pieces = next(v for k, v in merged_conf.items() if k.lower() == extract)
        except StopIteration:
            logger.error(f"{extract=} not found in conf {merged_conf}")
            pieces = None
        else:
            pieces = cast_type(BasicReturn, pieces)

        if pieces and opts.get("listize"):
            pieces_or_conf = cast_type(list[BasicReturn], listize(pieces))
        else:
            pieces_or_conf = pieces
    else:
        pieces_or_conf = merged_conf

    return pieces_or_conf, merged_conf


@dataclass(frozen=True)
class PreparedModule:
    name: str
    conf: DotDict
    opts: Opts
    parsers: ParseFuncs
    casters: CastFuncs | None
    assign: str
    emit: bool | Callable[[ParserOutput], bool] | None
    is_source: bool
    static_casted: tuple | None


def _dispatch(
    item: Item,
    opts: Opts,
    conf: Conf,
    parsers: ParseFuncs | None = None,
    casters: CastFuncs | None = None,
    defaults: Defaults | None = None,
    field: str | None = None,
    **kwargs,
) -> Dispatched:
    defaults = defaults or Defaults({})
    field = field or opts.get("field")

    if parsers:
        parsed_field, parsed_conf = broadcast(item, *parsers, field=field, **kwargs)
    else:
        parsed_field, parsed_conf = item, conf

    pieces_or_conf, merged_conf = get_pieces_or_conf(parsed_conf, defaults, opts)
    parsed = (parsed_field, pieces_or_conf, merged_conf)
    casted = dispatch(parsed, *casters) if casters else parsed
    conf = cast_type(Conf, casted[2])
    return Dispatched(item, Casted(casted[0], casted[1], conf))


def get_parsers(opts: Opts, conf: Conf, **kwargs) -> ParseFuncs:
    conf = conf or {}

    if opts.get("ftype") == BasicCastType.NONE:
        field_parser = cast_none
    else:
        field_parser = partial(get_field)

    if opts.get("ptype") == BasicCastType.NONE:
        conf_parser = cast_none
    elif conf_is_dynamic(conf, **kwargs):
        conf_parser = partial(parse_conf, conf=conf, memoize=False)
    else:
        pre_parsed = parse_conf(None, conf=conf, memoize=True)
        conf_parser = lambda _, **__: pre_parsed

    return ParseFuncs(field_parser, conf_parser)


def get_casters(opts: Opts) -> CastFuncs:
    ftype = opts.get("ftype")
    ptype = opts.get("ptype")
    extract = opts.get("extract")

    if ftype in CAST_SWITCH:
        _field_func = partial(cast_value, _type=CastType(ftype))
    else:
        if ftype:
            logger.warning(f"Invalid cast {ftype=}. Ignoring.")

        _field_func = cast_pass

    field_func = cast_type(SyncArgFunc, _field_func)

    if ptype in CAST_SWITCH:
        _caster = partial(cast_value, _type=CastType(ptype))
    else:
        if ptype:
            logger.warning(f"Invalid cast {ptype=}. Ignoring.")

        _caster = cast_pass

    caster = cast_type(SyncArgFunc, _caster)

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

    conf_caster = cast_type(SyncConfCastFunc, _conf_caster)
    return CastFuncs(field_func, extract_caster, conf_caster)
