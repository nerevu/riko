# vim: sw=4:ts=4:expandtab
"""
Return-kind inference diagnostics tests (Phase 4).

gen_return_inferences yields a ReturnInference (kind + source + reason) per
resolved return member. A successful classification names its source
(annotation/generator/ast); an unclassifiable one has source None and a reason
that explains how to fix the function contract.
"""

import asyncio
import itertools
from collections.abc import Iterator
from functools import wraps
from typing import Annotated, Any

import pytest

from riko.modules._inference import (
    gen_operator_return_kinds,
    gen_return_inferences,
    infer_from_source,
)
from riko.types._sentinels import MISSING
from riko.types.modules import InferenceSource, OperatorReturnKind

STREAM = OperatorReturnKind.STREAM
NONSTREAM = OperatorReturnKind.NONSTREAM
UNKNOWN = OperatorReturnKind.UNKNOWN
GENERATOR = InferenceSource.GENERATOR
ANNOTATION = InferenceSource.ANNOTATION
AST = InferenceSource.AST

type _AliasStream = Iterator[int]


def _broad(items) -> Any:
    return items


def _ambiguous(items):
    return build_result(items)  # noqa: F821 # pyright: ignore[reportUndefinedVariable]


def _gen_sync(items):
    yield from items


async def _gen_async(items):
    for item in items:
        yield item


def _ann_iterator(items) -> Iterator[int]:
    return iter(items)


def _ann_value(items) -> int:
    return len(items)


def _ann_wrapper(items) -> Annotated[Iterator[int], "meta"]:
    return iter(items)


def _alias(items) -> _AliasStream:
    return iter(items)


def _builtin_stream(items):
    return map(str, items)


def _builtin_nonstream(items):
    return list(items)


def _itertools_stream(items):
    return itertools.chain(items)


async def _passthrough(items):
    result = await asyncio.to_thread(map, str, items)
    return result


def _unresolvable(items) -> "Nonexistent":  # noqa: F821 # pyright: ignore[reportUndefinedVariable]
    return sum(items)


def only(pipe):
    return next(iter(gen_return_inferences(pipe)))


def kinds(pipe):
    return [inference.kind for inference in gen_return_inferences(pipe)]


@pytest.mark.parametrize(
    ("pipe", "kind", "source"),
    [
        pytest.param(_gen_sync, STREAM, GENERATOR, id="sync-generator"),
        pytest.param(_gen_async, STREAM, GENERATOR, id="async-generator"),
        pytest.param(_ann_iterator, STREAM, ANNOTATION, id="annotated-iterator"),
        pytest.param(_builtin_nonstream, NONSTREAM, AST, id="builtin-nonstream"),
        pytest.param(_unresolvable, NONSTREAM, AST, id="unresolvable-annotation"),
        pytest.param(_ann_value, NONSTREAM, MISSING, id="annotated-value"),
        pytest.param(_ann_wrapper, STREAM, MISSING, id="annotated-wrapper"),
        pytest.param(_alias, STREAM, MISSING, id="type-alias"),
        pytest.param(_builtin_stream, STREAM, MISSING, id="builtin-stream"),
        pytest.param(_itertools_stream, STREAM, MISSING, id="itertools-stream"),
        pytest.param(_passthrough, STREAM, MISSING, id="passthrough-wrapper"),
    ],
)
def test_classification(pipe, kind, source):
    inference = only(pipe)
    assert inference.kind is kind

    if source is not MISSING:
        assert inference.source is source


@pytest.mark.parametrize(
    ("pipe", "reasons"),
    [
        pytest.param(_broad, ("too broad",), id="broad-annotation"),
        pytest.param(len, ("return annotation",), id="unavailable-source"),
        pytest.param(
            _ambiguous, ("build_result", "return annotation"), id="ambiguous-call"
        ),
    ],
)
def test_unknown_with_reason(pipe, reasons):
    inference = only(pipe)
    assert inference.kind is UNKNOWN
    assert inference.source is None
    assert inference.reason is not None

    for reason in reasons:
        assert reason in inference.reason


def test_annotated_union():
    def pipe(items) -> Iterator[int] | int:
        return iter(items)

    assert set(kinds(pipe)) == {STREAM, NONSTREAM}


def test_nested_decorator_with_wraps():
    def deco(fn):
        @wraps(fn)
        def inner(*args, **kwargs):
            return fn(*args, **kwargs)

        return inner

    @deco
    def pipe(items):
        return sum(items)

    assert only(pipe).kind is NONSTREAM


def test_gen_operator_return_kinds_yields_bare_kinds():
    def pipe(items) -> Iterator[int] | int:
        return iter(items)

    assert set(gen_operator_return_kinds(pipe)) == {STREAM, NONSTREAM}


def test_infer_from_source_direct():
    def pipe(items):
        return sorted(items)

    inference = infer_from_source(pipe)
    assert inference.kind is NONSTREAM
    assert inference.source is AST


@pytest.mark.parametrize(
    "pipe",
    [len, lambda items: undefined(items)],  # noqa: F821, PLW0108 # pyright: ignore[reportUndefinedVariable]
)
def test_every_unknown_is_actionable(pipe):
    for inference in gen_return_inferences(pipe):
        if inference.kind is UNKNOWN:
            assert inference.source is None
            assert inference.reason is not None
            assert "return annotation" in inference.reason
