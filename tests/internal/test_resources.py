# vim: sw=4:ts=4:expandtab
"""Tests the execution-resource foundation (``riko.resources`` + Context wiring)."""

import pytest

from riko.context import Context
from riko.modules import operator
from riko.resources import Resource, bind_resources
from riko.types._streams import Stream
from tests import skipif_issync


class _Handle:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class _AsyncHandle:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


def test_owned_resource_opens_and_closes_handle():
    handle = _Handle()
    resource = Resource(handle)

    assert resource.open() is handle
    resource.close(handle)
    assert handle.closed


@pytest.mark.anyio
@skipif_issync
async def test_owned_resource_acloses_handle():
    handle = _AsyncHandle()
    resource = Resource(handle)

    assert await resource.aopen() is handle
    await resource.aclose(handle)
    assert handle.closed


def test_cleanup_override_wins():
    seen = []
    handle = _Handle()
    resource = Resource(handle, cleanup=seen.append)
    resource.close(handle)

    assert seen == [handle]
    assert not handle.closed


def test_credential_reference_is_carried():
    resource = Resource(object(), credential="microsoft/cif")
    assert resource.credential == "microsoft/cif"


def test_context_with_resource_is_immutable_copy():
    base = Context()
    resource = Resource.from_external(object())
    derived = base.with_resource("db", resource)

    assert "db" not in base.resources
    assert derived.resources["db"] is resource
    assert derived is not base


def test_bind_resources_missing_binding_raises():
    with pytest.raises(TypeError, match="unbound resource"):
        bind_resources("handle", {})


def test_bind_resources_owned_is_deferred():
    with pytest.raises(NotImplementedError, match="external"):
        bind_resources("db", {"db": Resource(object())})


def test_operator_parser_receives_resource_view():
    captured = {}

    @operator(resources="handle")
    def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
        captured["view"] = kwargs.get("resources")
        return stream

    handle = _Handle()
    context = Context().with_resource("handle", Resource.from_external(handle))
    list(pipe([{"a": 1}], context=context))
    assert captured["view"].handle is handle


def test_operator_missing_resource_binding_raises():
    @operator(resources="handle")
    def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
        return stream

    with pytest.raises(TypeError, match="unbound resource"):
        list(pipe([{"a": 1}], context=Context()))
