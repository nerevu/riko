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
    _gen_operator_return_kinds,
    _infer_from_source,
    gen_return_inferences,
)
from riko.types.modules import InferenceSource, OperatorReturnKind

STREAM = OperatorReturnKind.STREAM
NONSTREAM = OperatorReturnKind.NONSTREAM
UNKNOWN = OperatorReturnKind.UNKNOWN

type _AliasStream = Iterator[int]


def only(pipe):
    return next(iter(gen_return_inferences(pipe)))


def kinds(pipe):
    return [inference.kind for inference in gen_return_inferences(pipe)]


def test_sync_generator():
    def pipe(items):
        yield from items

    inference = only(pipe)
    assert inference.kind is STREAM
    assert inference.source is InferenceSource.GENERATOR


def test_async_generator():
    async def pipe(items):
        for item in items:
            yield item

    inference = only(pipe)
    assert inference.kind is STREAM
    assert inference.source is InferenceSource.GENERATOR


def test_annotated_iterator():
    def pipe(items) -> Iterator[int]:
        return iter(items)

    inference = only(pipe)
    assert inference.kind is STREAM
    assert inference.source is InferenceSource.ANNOTATION


def test_annotated_value():
    def pipe(items) -> int:
        return len(items)

    assert only(pipe).kind is NONSTREAM


def test_annotated_union():
    def pipe(items) -> Iterator[int] | int:
        return iter(items)

    assert set(kinds(pipe)) == {STREAM, NONSTREAM}


def test_annotated_wrapper():
    def pipe(items) -> Annotated[Iterator[int], "meta"]:
        return iter(items)

    assert only(pipe).kind is STREAM


def test_type_alias():
    def pipe(items) -> _AliasStream:
        return iter(items)

    assert only(pipe).kind is STREAM


def test_broad_annotation_is_unknown_with_reason():
    def pipe(items) -> Any:
        return items

    inference = only(pipe)
    assert inference.kind is UNKNOWN
    assert inference.source is None
    assert inference.reason is not None
    assert "too broad" in inference.reason


def test_builtin_nonstream():
    def pipe(items):
        return list(items)

    inference = only(pipe)
    assert inference.kind is NONSTREAM
    assert inference.source is InferenceSource.AST


def test_builtin_stream():
    def pipe(items):
        return map(str, items)

    assert only(pipe).kind is STREAM


def test_itertools_stream():
    def pipe(items):
        return itertools.chain(items)

    assert only(pipe).kind is STREAM


def test_passthrough_wrapper():
    async def pipe(items):
        result = await asyncio.to_thread(map, str, items)
        return result

    assert only(pipe).kind is STREAM


def test_unavailable_source_is_unknown_with_hint():
    inference = only(len)
    assert inference.kind is UNKNOWN
    assert inference.source is None
    assert inference.reason is not None
    assert "return annotation" in inference.reason


def test_ambiguous_call_is_unknown_with_hint():
    def pipe(items):
        return build_result(items)  # noqa: F821

    inference = only(pipe)
    assert inference.kind is UNKNOWN
    assert inference.source is None
    assert "build_result" in inference.reason
    assert "return annotation" in inference.reason


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


def test_unresolvable_annotation_falls_back_to_ast():
    def pipe(items) -> "Nonexistent":  # noqa: F821
        return sum(items)

    inference = only(pipe)
    assert inference.kind is NONSTREAM
    assert inference.source is InferenceSource.AST


def test_gen_operator_return_kinds_yields_bare_kinds():
    def pipe(items) -> Iterator[int] | int:
        return iter(items)

    assert set(_gen_operator_return_kinds(pipe)) == {STREAM, NONSTREAM}


def test_infer_from_source_direct():
    def pipe(items):
        return sorted(items)

    inference = _infer_from_source(pipe)
    assert inference.kind is NONSTREAM
    assert inference.source is InferenceSource.AST


@pytest.mark.parametrize("pipe", [len, lambda items: undefined(items)])  # noqa: F821
def test_every_unknown_is_actionable(pipe):
    for inference in gen_return_inferences(pipe):
        if inference.kind is UNKNOWN:
            assert inference.source is None
            assert inference.reason is not None
            assert "return annotation" in inference.reason
