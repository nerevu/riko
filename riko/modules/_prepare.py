# vim: sw=4:ts=4:expandtab
"""Prepares modules for per-item dispatch."""

from __future__ import annotations

from collections.abc import Iterator
from functools import cached_property, partial
from typing import TYPE_CHECKING, cast, overload

from attrs import Factory, define, field

from riko.base._iterutils import broadcast, dispatch
from riko.coercion._objectify import objectify
from riko.coercion._sequences import listize
from riko.coercion.cast import cast_none, cast_pass, cast_value, resolve_cast_type
from riko.parsing._dotdict import match_key
from riko.parsing.config import conf_is_dynamic, get_field, resolve_conf
from riko.types._collections import narrow_from_require, require_from_form
from riko.types._enums import BasicCastType, CastType
from riko.types._guards import is_mapping
from riko.types._options import (
    Casted,
    DecorationOptions,
    Defaults,
    ItemDispatch,
    ItemOrValueDispatch,
    ValueDispatch,
)
from riko.types._wrappers import (
    ArgCaster,
    CastFuncs,
    ParseFuncs,
    ParserOutput,
    SyncConfCastFunc,
)
from riko.types.modules import AnyModuleConf, Conf, require_module_conf

if TYPE_CHECKING:
    from collections.abc import Callable

    from riko.coercion._dynamic_conf import DynamicConf
    from riko.parsing._dotdict import DotDict
    from riko.types._geo import AnyLocation
    from riko.types._scalars import PrimitiveValue
    from riko.types._streams import Item, ItemOrValue
    from riko.types._values import BasicReturn, RikoDict, RikoList, RikoValue
    from riko.types._wrappers import ExtraNames


def build_conf(
    parsed_conf: AnyModuleConf | Conf | None,
    defaults: Defaults,
    opts: DecorationOptions,
    module: str = "",
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
        module: The module name, used in the error message.

    Returns:

        The extracted value or merged conf, paired with the merged conf.

    Raises:

        TypeError: When ``extract`` names a key absent from the merged conf.

    """
    if is_mapping(parsed_conf):
        merged_conf = require_module_conf({**defaults, **parsed_conf})
    else:
        merged_conf = require_module_conf(defaults)

    if extract := opts.get("extract"):
        matched = match_key(merged_conf, extract)

        if matched is None:
            label = f"the {module!r} module" if module else "this module"
            raise TypeError(f"{label} requires the {extract!r} conf key")

        pieces = cast("BasicReturn", merged_conf[matched])

        pieces_or_conf = listize(pieces) if opts.get("listize") else pieces
    else:
        pieces_or_conf = merged_conf

    return pieces_or_conf, merged_conf


@overload
def _build_caster[T](type_: None) -> ArgCaster[T]: ...  # noqa: E704
@overload
def _build_caster(type_: BasicCastType) -> ArgCaster[ItemOrValue]: ...  # noqa: E704
@overload  # noqa: E302
def _build_caster(type_: CastType) -> ArgCaster[ItemOrValue]: ...  # noqa: E704
def _build_caster[T](  # noqa: E302
    type_: BasicCastType | CastType | None,
) -> ArgCaster[T | PrimitiveValue | ItemOrValue]:
    """
    Builds a caster for a known cast type and degrades on an unknown one.

    An unrecognized ``type_`` logs a warning and falls back to ``cast_pass``
    (pass-through) rather than raising.

    Args:

        type_: The cast type, or ``None`` for pass-through.

    Returns:

        A caster callable taking content and optional kwargs.

    """
    if (cast_type := resolve_cast_type(type_)) == CastType.PASS:
        caster = cast_pass
    else:

        def caster(content: T, **kwargs: object) -> T | PrimitiveValue | AnyLocation:
            return cast_value(content, cast_type, **kwargs)

    return caster


def build_casters(opts: DecorationOptions) -> CastFuncs[ItemOrValue, object]:
    """
    Builds the field, extract, and conf casters from a module's options.

    Honors ``ftype``/``ptype`` for the field and extract casters and combines
    ``objectify``/``listize`` to decide how extract and conf are cast; a ``"none"``
    ``ptype`` disables casting for both.

    Args:

        opts: The decoration options (``ftype``/``ptype``/``extract``/
            ``listize``/``objectify``).

    Returns:

        The field, extract, and conf casters.

    """
    ftype = opts.get("ftype")
    ptype = opts.get("ptype")
    extract = opts.get("extract")

    field_caster = _build_caster(ftype)
    value_caster = _build_caster(ptype)

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

    conf_caster = cast("SyncConfCastFunc", _conf_caster)
    return CastFuncs(field_caster, extract_caster, conf_caster)


_require_conf = require_from_form(Conf, "PreparedModule 'conf'", error=TypeError)
_conf_converter = narrow_from_require(_require_conf, accepted=Conf)


@define(frozen=True, slots=True)
class PreparedModule[T, E]:
    """
    Immutable call-time module state that is prepared once and reused across items.

    Attributes:

        name: The module name.

        conf: The merged module configuration.

        opts: The decoration options plus the resolved call options.

        extras: The names of the extra inputs delivered with each item. A
            configuration value naming one is resolved per item.

        defaults: The module's default configuration.

        assign: The field results are assigned to (default: the module name).

        emit: Whether (or a predicate deciding whether) to emit rather than assign.

        is_conf_parsed: Whether the module parses its configuration.

        is_dynamic: Whether the configuration varies per item.

        static_conf: The parsed configuration when it does not vary per item, else
            ``None``.

        parsers: The field and conf parsers.

        casters: The field, extract, and conf casters.

        static_casted: The cast field caster, extraction, and conf when the
            configuration does not vary per item, else ``None``.

    Examples:

        >>> prepared = PreparedModule(name="pipe", conf={"times": 2})
        >>> prepared.assign, prepared.is_dynamic, prepared.static_conf
        ('pipe', False, {'times': 2})
        >>> prepared.static_casted[1]
        {'times': 2}

    """

    name: str
    conf: Conf = field(factory=lambda: _require_conf({}), converter=_conf_converter)
    opts: DecorationOptions = Factory(DecorationOptions)
    extras: ExtraNames = ()
    defaults: Defaults = Factory(Defaults)

    @cached_property
    def assign(self) -> str:
        """The field results are assigned to."""
        return self.opts.get("assign", self.name)

    @cached_property
    def emit(self) -> bool | Callable[[ParserOutput[ItemOrValue]], bool] | None:
        """Whether (or a predicate deciding whether) to emit rather than assign."""
        return self.opts.get("emit")

    @cached_property
    def is_conf_parsed(self) -> bool:
        """Whether the module parses its configuration."""
        return self.opts.get("ptype") != BasicCastType.NONE

    @cached_property
    def is_dynamic(self) -> bool:
        """Whether the configuration varies per item."""
        if self.is_conf_parsed:
            sentinels = dict.fromkeys(self.extras)
            is_dynamic = conf_is_dynamic(self.conf, **sentinels)
        else:
            is_dynamic = False

        return is_dynamic

    @cached_property
    def static_conf(self) -> AnyModuleConf | None:
        """The parsed configuration when it does not vary per item, else ``None``."""
        if self.is_dynamic or not self.is_conf_parsed:
            static_conf = None
        else:
            static_conf = resolve_conf(None, conf=self.conf)

        return static_conf

    @cached_property
    def parsers(self) -> ParseFuncs:
        """
        The field and conf parsers.

        A ``"none"`` ``ftype``/``ptype`` yields a null parser. A conf that varies per
        item is parsed per call; otherwise every call gets the parsed static conf.
        """
        if self.opts.get("ftype") == BasicCastType.NONE:
            field_parser = cast_none
        else:
            field_parser = partial(get_field)

        if not self.is_conf_parsed:
            conf_parser = cast_none
        elif self.is_dynamic:
            conf_parser = partial(resolve_conf, conf=self.conf)
        else:
            static = self.static_conf
            conf_parser = lambda _, **__: static

        return ParseFuncs(field_parser, conf_parser)

    @cached_property
    def casters(self) -> CastFuncs[ItemOrValue, E]:
        """The field, extract, and conf casters."""
        return cast("CastFuncs[ItemOrValue, E]", build_casters(self.opts))

    @cached_property
    def static_casted(self) -> tuple[ArgCaster[T], E, DynamicConf] | None:
        """The cast field caster, extraction, and conf of a static configuration."""
        if self.is_dynamic:
            static_casted = None
        else:
            casters = self.casters
            parsed_conf = self.parsers.conf_parser({})
            args = (parsed_conf, self.defaults, self.opts, self.name)
            casted = dispatch(build_conf(*args), casters[1], casters[2])
            field_caster = cast("ArgCaster[T]", casters[0])
            static_casted = (field_caster, casted[0], casted[1])

        return static_casted

    def resolve_emit(self, output: ParserOutput[ItemOrValue]) -> bool:
        """
        Decides whether a parser's result is emitted rather than assigned.

        An ``emit`` predicate decides from the result itself, except for a lazy
        iterator, which it cannot inspect without consuming; an iterator and a
        plain flag use the flag's truthiness.

        Args:

            output: The parser's result.

        Returns:

            True when the result is emitted as is.

        Examples:

            >>> from riko.types._guards import is_mapping
            >>>
            >>> opts = {"assign": "content", "emit": is_mapping}
            >>> prepared = PreparedModule(name="pipe", opts=opts)
            >>> prepared.resolve_emit({"x": 1})
            True
            >>> prepared.resolve_emit("x")
            False
            >>> prepared.resolve_emit(iter([{"x": 1}]))
            True

        """
        if callable(self.emit) and not isinstance(output, Iterator):
            emit = bool(self.emit(output))
        else:
            emit = bool(self.emit)

        return emit


@overload
def resolve_and_cast[T, E](  # noqa: E704
    item: Item | RikoDict | DotDict[RikoValue],
    opts: DecorationOptions,
    *,
    parsers: ParseFuncs,
    casters: CastFuncs[T, E],
    defaults: Defaults | None = ...,
    field: str | None = ...,
    module: str = ...,
    **kwargs: object,
) -> ItemDispatch[T, E]: ...
@overload  # noqa: E302
def resolve_and_cast[T, E](  # noqa: E704
    item: PrimitiveValue | RikoList,
    opts: DecorationOptions,
    *,
    parsers: ParseFuncs,
    casters: CastFuncs[T, E],
    defaults: Defaults | None = ...,
    field: str | None = ...,
    module: str = ...,
    **kwargs: object,
) -> ValueDispatch[T, E]: ...
def resolve_and_cast[T, E](  # noqa: E302
    item: ItemOrValue,
    opts: DecorationOptions,
    *,
    parsers: ParseFuncs,
    casters: CastFuncs[T, E],
    defaults: Defaults | None = None,
    field: str | None = None,
    module: str = "",
    **kwargs: object,
) -> ItemOrValueDispatch[T, E]:
    """
    Parses and casts one item's field and conf into a dispatch record.

    Runs the field/conf parsers over the item, resolves the extract-or-conf via
    ``build_conf``, applies the casters, and wraps the result as an item
    or value dispatch depending on whether the input is a mapping.

    Args:

        item: The input item or value.
        opts: The resolved decoration and call options.
        parsers: The field and conf parsers.
        casters: The field, extract, and conf casters.
        defaults: The module's default conf.
        field: Optional field whose value replaces the item.
        module: The module name, used in error messages.
        **kwargs: Extra keyword arguments forwarded to the parsers.

    Returns:

        An item or value dispatch pairing the original item with its cast pieces.

    """
    defaults = defaults or Defaults({})
    field = opts.get("field") if field is None else field
    parsed_field, parsed_conf = broadcast(item, *parsers, field=field, **kwargs)
    pieces_or_conf, merged_conf = build_conf(parsed_conf, defaults, opts, module)
    parsed = (parsed_field, pieces_or_conf, merged_conf)
    casted = dispatch(parsed, *casters) if casters else parsed

    if is_mapping(item):
        dispatched = ItemDispatch(item, Casted(*casted))
    else:
        dispatched = ValueDispatch(item, Casted(*casted))

    return dispatched
