# vim: sw=4:ts=4:expandtab
"""
riko.modules._assignment
~~~~~~~~~~~~~~~~~~~~~~~~~
Assignment machinery: sub-pipe binding for embedded modules and the logic that
decides whether a parser result is a single value or a stream and how it is
assigned onto the item.
"""

from collections.abc import Awaitable, Callable, Iterable, Iterator
from copy import copy
from functools import partial
from itertools import chain, islice
from logging import Logger
from typing import Literal, cast, overload

import pygogo as gogo

from riko.context import Context
from riko.dotdict import DotDict
from riko.types.compile import EmbedKwargs
from riko.types.general import (
    AsyncProcessorWrapper,
    AsyncSubPipe,
    Item,
    ItemOrValue,
    ItemsOrValues,
    OperatorParserOutput,
    OperatorWrapperInput,
    ProcessorParserOutput,
    ProcessorWrapper,
    ProcessorWrapperInput,
    ProcessorWrapperOutput,
    Stream,
    StreamOrValueStream,
    SubPipe,
    SyncProcessorWrapper,
    SyncSubPipe,
    ValueStream,
)
from riko.types.modules import CountValues
from riko.types.values import PrimitiveValue, RikoValue, StatefulItem

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


@overload
def get_subpipe(  # noqa: E704
    embed: SyncProcessorWrapper | SyncSubPipe,
    context: Context,
    embedded_kwargs: EmbedKwargs | None = ...,
    field: str | None = ...,
) -> partial[ProcessorWrapperOutput]: ...
@overload  # noqa: E302
def get_subpipe(  # noqa: E704
    embed: AsyncProcessorWrapper | AsyncSubPipe,
    context: Context,
    embedded_kwargs: EmbedKwargs | None = ...,
    field: str | None = ...,
) -> partial[Awaitable[ProcessorWrapperOutput]]: ...
def get_subpipe(  # noqa: E302 # pyright: ignore[reportInconsistentOverload]
    embed: ProcessorWrapper | SubPipe,
    context: Context,
    embedded_kwargs: EmbedKwargs | None = None,
    field: str | None = None,
) -> Callable[
    [ProcessorWrapperInput], ProcessorWrapperOutput | Awaitable[ProcessorWrapperOutput]
]:
    if embedded_kwargs and "field" in embedded_kwargs:
        embed_field = embedded_kwargs["field"]

        if embed_field and field is not None and embed_field != field:
            logger.warning(f"Loop {field=} overrides {embed_field=}.")
            embedded_kwargs["field"] = field

        kwargs = {**embedded_kwargs}
    elif embedded_kwargs and field is not None:
        kwargs = {**embedded_kwargs, "field": field}
    elif embedded_kwargs:
        kwargs = {**embedded_kwargs}
    elif field:
        kwargs = {"field": field}
    else:
        kwargs = {}

    embed_context = copy(context)
    embed_context.submodule = True
    return partial(embed, **kwargs, context=embed_context)


@overload
def get_assignment(  # noqa: E704
    items: Stream | Iterator[StatefulItem] | DotDict[RikoValue], skip: bool = ...
) -> tuple[bool, Stream]: ...
@overload  # noqa: E302
def get_assignment(  # noqa: E704
    items: PrimitiveValue, skip: bool = ...
) -> tuple[bool, ValueStream]: ...
@overload  # noqa: E302
def get_assignment(  # noqa: E704
    items: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
    skip: bool = ...,
    count: CountValues | None = ...,
) -> tuple[bool, StreamOrValueStream]: ...
def get_assignment(  # noqa: E302
    items: ProcessorParserOutput | OperatorParserOutput | OperatorWrapperInput,
    skip=False,
    count: CountValues | None = None,
) -> tuple[bool, StreamOrValueStream]:
    if isinstance(items, Iterator):
        dictized = cast(Stream, map(DotDict.dictize, items))
    else:
        dictized = cast(StreamOrValueStream, iter([DotDict.dictize(items)]))

    if skip:
        one = False
        result = dictized
    else:
        results = list(islice(dictized, 2))
        multiple = len(results) > 1
        # multiple result pipe, e.g., fetchpage/tokenizer
        # one result pipe, e.g., strconcat

        result = chain(results, dictized) if results else iter(())
        first = bool(count == "first")
        _all = count == "all"
        one = first or not (multiple or _all)

        if one and results:
            result = islice(results, 1)
        elif one:
            result = iter(())

    return one, result


@overload
def gen_assignments[T: ItemOrValue](  # noqa: E704
    item: DotDict[RikoValue],
    assignment: Iterable[T],
    assign: str = ...,
    one: Literal[False] = ...,
) -> Iterator[T]: ...
@overload  # noqa: E302
def gen_assignments(  # noqa: E704
    item: DotDict[RikoValue],
    assignment: ItemsOrValues,
    assign: str = ...,
    *,
    one: Literal[True],
) -> Stream: ...
def gen_assignments(  # noqa: E302
    item: DotDict[RikoValue],
    assignment: Item | ItemsOrValues,
    assign: str | None = None,
    one=False,
    **_,
) -> StreamOrValueStream:
    if one and isinstance(assignment, Iterator):
        value = next(assignment, None)
    else:
        value = assignment

    value_is_iterator = isinstance(value, Iterator)

    if assign:
        if value is None:
            yield item
        elif item and value_is_iterator:
            yield item | {assign: list(value)}
        elif value_is_iterator:
            yield from cast(ItemsOrValues, ({assign: v} for v in value))
        else:
            yield item | {assign: value}
    elif value_is_iterator:
        yield from map(DotDict.dictize, value)
    else:
        yield cast(Item, DotDict.dictize(value))
