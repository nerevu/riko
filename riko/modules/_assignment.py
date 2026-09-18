# vim: sw=4:ts=4:expandtab
"""Handles sub-pipe binding and item assignment."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterator
from functools import partial
from itertools import chain, islice
from typing import TYPE_CHECKING, overload

import pygogo as gogo

from riko.parsing._dotdict import DotDict

if TYPE_CHECKING:
    from logging import Logger

    from riko.runtime.context import Context
    from riko.types._collections import RikoValue
    from riko.types._compiler import CountValues, EmbedKwargs
    from riko.types._scalars import PrimitiveValue
    from riko.types._streams import (
        Item,
        ItemOrValue,
        Stream,
        StreamOrValueStream,
        ValueStream,
    )
    from riko.types._wrappers import (
        AsyncProcessorWrapper,
        AsyncSubPipe,
        OperatorParserOutput,
        ProcessorWrapper,
        ProcessorWrapperInput,
        SubPipe,
        SyncProcessorWrapper,
        SyncProcessorWrapperOutput,
        SyncSubPipe,
    )

logger: Logger = gogo.Gogo(__name__, monolog=True).logger


@overload
def get_subpipe(  # noqa: E704
    embed: SyncProcessorWrapper | SyncSubPipe,
    context: Context,
    embedded_kwargs: EmbedKwargs | None = ...,
    field: str | None = ...,
) -> partial[SyncProcessorWrapperOutput]: ...
@overload  # noqa: E302
def get_subpipe(  # noqa: E704
    embed: AsyncProcessorWrapper | AsyncSubPipe,
    context: Context,
    embedded_kwargs: EmbedKwargs | None = ...,
    field: str | None = ...,
) -> partial[Awaitable[SyncProcessorWrapperOutput]]: ...
def get_subpipe(  # noqa: E302
    embed: ProcessorWrapper | SubPipe,
    context: Context,
    embedded_kwargs: EmbedKwargs | None = None,
    field: str | None = None,
) -> Callable[
    [ProcessorWrapperInput],
    SyncProcessorWrapperOutput | Awaitable[SyncProcessorWrapperOutput],
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

    embed_context = context.augment(submodule=True)
    return partial(embed, **kwargs, context=embed_context)


@overload
def get_assignment(  # noqa: E704
    items: Stream | Item, skip: bool = ..., count: CountValues | None = ...
) -> tuple[bool, Stream]: ...
@overload  # noqa: E302
def get_assignment(  # noqa: E704
    items: PrimitiveValue, skip: bool = ..., count: CountValues | None = ...
) -> tuple[bool, ValueStream]: ...
@overload  # noqa: E302
def get_assignment(  # noqa: E704
    items: OperatorParserOutput[ItemOrValue],
    skip: bool = ...,
    count: CountValues | None = ...,
) -> tuple[bool, StreamOrValueStream]: ...
def get_assignment(  # noqa: E302
    items: OperatorParserOutput[ItemOrValue],
    skip=False,
    count: CountValues | None = None,
) -> tuple[bool, StreamOrValueStream]:
    if isinstance(items, Iterator):
        dictized = map(DotDict.dictize, items)
    else:
        dictized = iter([DotDict.dictize(items)])

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
def gen_assignments(  # noqa: E704
    item: DotDict[RikoValue],
    assignment: Stream,
    assign: str | None = ...,
    one: bool = ...,
) -> Stream: ...
@overload  # noqa: E302
def gen_assignments(  # noqa: E704
    item: DotDict[RikoValue],
    assignment: ValueStream,
    assign: None = ...,
    one: bool = ...,
) -> ValueStream: ...
@overload  # noqa: E302
def gen_assignments(  # noqa: E704
    item: DotDict[RikoValue],
    assignment: StreamOrValueStream,
    assign: str | None = ...,
    one: bool = ...,
) -> StreamOrValueStream: ...
def gen_assignments(  # noqa: E302
    item: DotDict[RikoValue],
    assignment: StreamOrValueStream,
    assign: str | None = None,
    one: bool = False,
    **_,
) -> Iterator[
    DotDict[RikoValue | list[ItemOrValue]] | ItemOrValue | DotDict[ItemOrValue]
]:
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
            for v in value:
                yield DotDict({assign: v})
        else:
            yield item | {assign: value}
    elif value_is_iterator:
        yield from map(DotDict.dictize, value)
    else:
        yield DotDict.dictize(value)
