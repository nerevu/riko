# vim: sw=4:ts=4:expandtab
"""
riko.modules._assignment
~~~~~~~~~~~~~~~~~~~~~~~~~
Assignment machinery: sub-pipe binding for embedded modules and the logic that
decides whether a parser result is a single value or a stream and how it is
assigned onto the item.
"""

from collections.abc import Awaitable, Iterator
from copy import copy
from functools import partial
from itertools import chain, islice
from typing import Literal, cast, overload

from riko.context import Context
from riko.dotdict import DotDict
from riko.types.general import (
    AsyncProcessorWrapper,
    Item,
    OperatorParserOutput,
    ProcessorParserOutput,
    ProcessorWrapper,
    ProcessorWrapperOutput,
    Stream,
    StreamOrValueStream,
    SyncProcessorWrapper,
    ValueStream,
)
from riko.types.modules import ConfValues
from riko.types.values import PrimitiveValue, RikoValue, StatefulItem


@overload
def _get_subpipe(  # noqa: E704
    embed: SyncProcessorWrapper, context: Context, **embedded_kwargs
) -> partial[ProcessorWrapperOutput]: ...
@overload  # noqa: E302
def _get_subpipe(  # noqa: E704
    embed: AsyncProcessorWrapper, context: Context, **embedded_kwargs
) -> partial[Awaitable[ProcessorWrapperOutput]]: ...
def _get_subpipe(  # noqa: E302 # pyright: ignore[reportInconsistentOverload]
    embed: ProcessorWrapper, context: Context, **embedded_kwargs
) -> partial[ProcessorWrapperOutput | Awaitable[ProcessorWrapperOutput]]:
    embed_context = copy(context)
    embed_context.submodule = True
    embedded_kwargs["context"] = embed_context
    return partial(embed, **embedded_kwargs)


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
    items: ProcessorParserOutput | OperatorParserOutput | DotDict[RikoValue],
    skip: bool = ...,
) -> tuple[bool, StreamOrValueStream]: ...
def get_assignment(  # noqa: E302
    items: ProcessorParserOutput | OperatorParserOutput | DotDict[RikoValue],
    skip=False,
    **conf: ConfValues,
) -> tuple[bool, StreamOrValueStream]:
    count = conf.get("count")

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
def gen_assignments[T: StreamOrValueStream](  # noqa: E704
    item: DotDict[RikoValue],
    assignment: T,
    assign: str = ...,
    one: Literal[False] = ...,
) -> T: ...
@overload  # noqa: E302
def gen_assignments(  # noqa: E704
    item: DotDict[RikoValue],
    assignment: StreamOrValueStream,
    assign: str = ...,
    *,
    one: Literal[True],
) -> Stream: ...
def gen_assignments(  # noqa: E302
    item: DotDict[RikoValue],
    assignment: Item | StreamOrValueStream,
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
            yield from cast(StreamOrValueStream, ({assign: v} for v in value))
        else:
            yield item | {assign: value}
    elif value_is_iterator:
        yield from map(DotDict.dictize, value)
    else:
        yield DotDict.dictize(value)
