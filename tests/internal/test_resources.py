# vim: sw=4:ts=4:expandtab
"""Tests execution-resource foundations and Context wiring."""

from __future__ import annotations

from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Literal, cast

import pytest

from riko.definitions._resources import bind_resources
from riko.modules import operator
from riko.runtime._resources import (
    FactoryKind,
    OneShotResource,
    Resource,
    ReusableResource,
    classify_factory,
)
from riko.runtime.context import Context
from tests import async_test

if TYPE_CHECKING:
    from riko.types._resource import LifecycleFactory, ValueFactory
    from riko.types._streams import RecordStream

_CREDENTIAL = "microsoft/cif"
_SCALAR = 42


class _Connection:
    def __init__(self):
        self.opened = True

    @property
    def closed(self):
        return not self.opened

    def close(self):
        self.opened = False


class _AsyncConnection(_Connection):
    async def aclose(self):
        self.opened = False


def close_connection(conn: _Connection):
    conn.close()


async def close_async_connection(conn: _AsyncConnection):
    await conn.aclose()


def sync_callable_factory():
    return _Connection()


async def async_callable_factory():
    return _AsyncConnection()


def sync_gen_factory(credential: str | None = None):
    connection = _Connection()
    print(f"\nCreating a fresh sync db using {connection}")
    yield connection
    print("\nClosing sync db...")


async def async_gen_factory(credential: str | None = None):
    connection = _AsyncConnection()
    print(f"\nCreating a fresh async db using {connection}")
    yield connection
    print("\nClosing async db...")


@contextmanager
def sync_cm_factory(credential: str | None = None):
    connection = _Connection()
    print(f"Setting up sync db using {connection}")

    try:
        yield connection
    finally:
        print("Cleaning sync db...")


@asynccontextmanager
async def async_cm_factory(credential: str | None = None):
    connection = _AsyncConnection()
    print(f"Setting up async db using {connection}")

    try:
        yield connection
    finally:
        print("Cleaning async db...")


def cleanup_contextmanager(_: AbstractContextManager[_Connection]):
    pass


connection = pytest.fixture(sync_callable_factory)
async_connection = pytest.fixture(async_callable_factory)
sync_contextmanager = pytest.fixture(sync_cm_factory)
async_contextmanager = pytest.fixture(async_cm_factory)
scalar = pytest.fixture(lambda: _SCALAR)


@pytest.fixture
def one_shot_resource(connection: _Connection) -> OneShotResource[_Connection]:
    return Resource(connection)


@pytest.fixture
def external_resource(connection: _Connection):
    return Resource.from_external(connection)


def _test_open_close(resource, value: object | None = None):
    if value is None:
        value = resource.open()
        assert value
    else:
        assert resource.open() is value

    if isinstance(value, _Connection):
        assert value.opened

    resource.close(value)

    if isinstance(value, _Connection):
        assert value.closed is not resource.external
        value.opened = True  # reset for next test


async def _async_test_open_close(resource, value: object | None = None):
    if value is None:
        value = await resource.aopen()
        assert value
    else:
        assert await resource.aopen() is value

    if isinstance(value, _AsyncConnection):
        assert value.opened

    await resource.aclose(value)

    if isinstance(value, _AsyncConnection):
        assert value.closed is not resource.external
        value.opened = True  # reset for next test


def _test_credential_and_lazy(resource):
    assert resource.credential == _CREDENTIAL
    assert resource.lazy


def _test_metadata(
    resource,
    typ: type,
    *,
    external: bool,
    reusable: bool,
    classification: FactoryKind | None = None,
):
    assert isinstance(resource, typ)
    assert resource.external == external
    assert resource.reusable == reusable

    if classification is not None:
        assert resource.kind is classification


class TestLifecyleFactory:
    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_raises[T](self, factory: LifecycleFactory[T]):
        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource(factory)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(factory)

    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_credential_and_lazy_carried[T](self, factory: LifecycleFactory[T]):
        context = Context().with_resource(
            "factory", factory, credential=_CREDENTIAL, lazy=True
        )
        resource = context.resources["factory"]
        _test_credential_and_lazy(resource)

        resource = Resource.from_lifecycle(factory, credential=_CREDENTIAL, lazy=True)
        _test_credential_and_lazy(resource)

        resource = Resource.from_factory(factory, credential=_CREDENTIAL, lazy=True)
        _test_credential_and_lazy(resource)

    @pytest.mark.parametrize(
        ("factory", "classification"),
        [
            (sync_gen_factory, FactoryKind.SYNC_GEN_FACTORY),
            (async_gen_factory, FactoryKind.ASYNC_GEN_FACTORY),
            (sync_cm_factory, FactoryKind.SYNC_CM_FACTORY),
            (async_cm_factory, FactoryKind.ASYNC_CM_FACTORY),
        ],
    )
    def test_resource_metadata[T](
        self, factory: LifecycleFactory[T], classification: FactoryKind
    ):
        assert classify_factory(factory) is classification
        test_metadata = partial(_test_metadata, classification=classification)

        context = Context().with_resource("factory", factory)
        resource = context.resources["factory"]
        test_metadata(resource, ReusableResource, external=False, reusable=True)

        resource = Resource.from_lifecycle(factory)
        test_metadata(resource, OneShotResource, external=False, reusable=False)

        resource = Resource.from_factory(factory)
        test_metadata(resource, ReusableResource, external=False, reusable=True)

    @pytest.mark.parametrize(
        "factory",
        [sync_gen_factory, async_gen_factory, sync_cm_factory, async_cm_factory],
    )
    def test_resource_opens_and_closes[T](self, factory: LifecycleFactory[T]):
        context = Context().with_resource("factory", factory)
        resource = context.resources["factory"]

        with pytest.raises(NotImplementedError, match=r"Factory resource.*execution"):
            _test_open_close(resource)

        resource = Resource.from_lifecycle(factory)

        with pytest.raises(NotImplementedError, match=r"Lifecycle resource.*execution"):
            _test_open_close(resource)

        resource = Resource.from_factory(factory)

        with pytest.raises(NotImplementedError, match=r"Factory resource.*execution"):
            _test_open_close(resource)


class TestValueFactory:
    @pytest.mark.parametrize("factory", [sync_callable_factory, async_callable_factory])
    def test_raises[T](self, factory: ValueFactory[T]):
        with pytest.raises(TypeError, match=r"Invalid resource factory.*one-shot"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "factory",
                factory,  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Must provide a Closeable value"):
            Resource(  # pyright: ignore[reportCallIssue]
                factory  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            Resource.from_lifecycle(factory)  # pyright: ignore[reportArgumentType]

        with pytest.raises(TypeError, match=r"ValueFactory requires.*cleanup function"):
            Resource.from_factory(factory)  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize(
        ("factory", "cleanup"),
        [
            (sync_callable_factory, close_connection),
            (async_callable_factory, close_async_connection),
        ],
    )
    def test_credential_and_lazy_carried[T](self, factory: ValueFactory[T], cleanup):
        Resource.from_factory(
            factory, cleanup=cleanup, credential=_CREDENTIAL, lazy=True
        )

    @pytest.mark.parametrize(
        ("factory", "cleanup", "classification"),
        [
            (
                sync_callable_factory,
                close_connection,
                FactoryKind.SYNC_CALLABLE_FACTORY,
            ),
            (
                async_callable_factory,
                close_async_connection,
                FactoryKind.ASYNC_CALLABLE_FACTORY,
            ),
        ],
    )
    def test_resource_metadata[T](
        self, factory: ValueFactory[T], cleanup, classification: FactoryKind
    ):
        assert classify_factory(factory, lifecycle=False) is classification
        test_metadata = partial(_test_metadata, typ=ReusableResource, reusable=True)

        resource = Resource.from_external(factory)
        test_metadata(resource, external=True)

        resource = Resource.from_factory(factory, cleanup=cleanup)
        test_metadata(resource, external=False, classification=classification)

    @pytest.mark.parametrize(
        ("factory", "cleanup"),
        [
            (sync_callable_factory, close_connection),
            (async_callable_factory, close_async_connection),
        ],
    )
    def test_resource_opens_and_closes[T](self, factory: ValueFactory[T], cleanup):
        resource = Resource.from_factory(factory, cleanup=cleanup)

        with pytest.raises(NotImplementedError, match="execution layer"):
            _test_open_close(resource, factory)


type ValueKind = Literal[
    "scalar", "closeable", "context-manager", "one-shot", "external"
]


@dataclass(frozen=True)
class ValueCase:
    fixture: str
    kind: ValueKind


VALUE_CASES = [
    pytest.param(ValueCase("scalar", "scalar"), id="scalar"),
    pytest.param(ValueCase("connection", "closeable"), id="connection"),
    pytest.param(
        ValueCase("sync_contextmanager", "context-manager"), id="sync-context-manager"
    ),
    pytest.param(ValueCase("one_shot_resource", "one-shot"), id="one-shot"),
    pytest.param(ValueCase("external_resource", "external"), id="external"),
]


class TestValues:
    @pytest.mark.parametrize("case", VALUE_CASES)
    def test_constructor_contract(self, case: ValueCase, request):
        value = request.getfixturevalue(case.fixture)

        if case.kind == "external":
            context = Context().with_resource("value", value)
            resource = context.resources["value"]
            _test_metadata(resource, ReusableResource, external=True, reusable=True)
            _test_open_close(resource)

            with pytest.raises(TypeError, match=r"credential.*lazy.*LifecycleFactory"):
                Context().with_resource(
                    "value", value, credential=_CREDENTIAL, lazy=True
                )
        else:
            with pytest.raises(TypeError, match="Invalid resource factory"):
                Context().with_resource("value", value)

        if case.kind in {"one-shot", "external"}:
            with pytest.raises(TypeError, match="Expected a resolved resource value"):
                Resource(value)
        elif case.kind == "scalar":
            with pytest.raises(TypeError, match="Must provide a Closeable value"):
                Resource(value)

            owned = Resource(value, cleanup=lambda _: None)
            _test_metadata(owned, OneShotResource, external=False, reusable=False)
            _test_open_close(owned, value)

            external = Resource.from_external(value)
            _test_metadata(external, ReusableResource, external=True, reusable=True)
            _test_open_close(external, value)
        elif case.kind == "closeable":
            owned = Resource(value)
            _test_metadata(owned, OneShotResource, external=False, reusable=False)
            _test_open_close(owned, value)

            external = Resource.from_external(value)
            _test_metadata(external, ReusableResource, external=True, reusable=True)
            _test_open_close(external, value)
        else:
            with pytest.raises(TypeError, match="Expected a resolved resource value"):
                Resource(value)

            with pytest.raises(TypeError, match="Expected a resolved resource"):
                Resource.from_external(value)

        if case.kind == "context-manager":
            lifecycle = Resource.from_lifecycle(value)
            _test_metadata(lifecycle, OneShotResource, external=False, reusable=False)

            configured = Resource.from_lifecycle(
                value, credential=_CREDENTIAL, lazy=True
            )
            _test_credential_and_lazy(configured)

            with pytest.raises(NotImplementedError, match="execution layer"):
                _test_open_close(lifecycle, value)

            with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
                Resource.from_factory(value)

            casted = cast("ValueFactory[AbstractContextManager[_Connection]]", value)
            factory = Resource.from_factory(casted, cleanup=cleanup_contextmanager)
            _test_metadata(factory, ReusableResource, external=False, reusable=True)
        else:
            with pytest.raises(TypeError, match="Invalid lifecycle factory"):
                Resource.from_lifecycle(value)

            with pytest.raises(TypeError, match="Invalid resource factory"):
                Resource.from_factory(value)

    @async_test
    async def test_async_constructor_contract(
        self,
        async_connection: _AsyncConnection,
        async_contextmanager: AbstractAsyncContextManager[_AsyncConnection],
    ):
        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "value",
                async_contextmanager,  # pyright: ignore[reportArgumentType]
            )

        await _async_test_open_close(Resource(async_connection), async_connection)

        external = Resource.from_external(async_connection)
        await _async_test_open_close(external, async_connection)

        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "value",
                async_contextmanager,  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource(async_contextmanager)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(async_contextmanager)

        lifecycle = Resource.from_lifecycle(async_contextmanager)

        with pytest.raises(NotImplementedError, match="execution layer"):
            await _async_test_open_close(lifecycle, async_contextmanager)

        with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
            Resource.from_factory(
                async_contextmanager  # pyright: ignore[reportArgumentType]
            )


class TestResourceEcosystem:
    def test_context_with_resource_is_immutable_copy(self):
        base = Context(verbose=True)
        resource = Resource.from_factory(sync_gen_factory)
        derived = base.with_resource("resource", resource)

        assert "resource" not in base.resources
        assert derived.resources["resource"] is resource
        assert derived.verbose
        assert derived is not base

    def test_operator_missing_resource_binding_raises(self):
        @operator(resources="connection")
        def pipe(stream: RecordStream, objconf, tuples, **kwargs) -> RecordStream:
            return stream

        with pytest.raises(TypeError, match="is not bound"):
            list(pipe([{"a": 1}], context=Context()))

    def test_classify_rejects_non_resource(self):
        with pytest.raises(TypeError, match="Invalid lifecycle factory"):
            classify_factory(_SCALAR)  # pyright: ignore[reportArgumentType]

    def test_bind_resources_missing_binding_raises(self):
        with pytest.raises(TypeError, match="is not bound"):
            bind_resources("connection", {})

    def test_bind_resources_validates_all_names_before_opening(self):
        """Name validation must complete before resource acquisition."""
        opened: list[str] = []

        class _Spy:
            def open(self) -> object:
                opened.append("present")
                return object()

        resources = {"present": _Spy()}

        with pytest.raises(TypeError, match="is not bound"):
            bind_resources(
                {"a": "present", "b": "absent"},
                resources,  # pyright: ignore[reportArgumentType]
            )

        assert opened == []

    def test_bind_owned_resources_not_implemented(self, connection: _Connection):
        external = Resource.from_external(connection)
        owned = Resource.from_lifecycle(sync_gen_factory)

        assert bind_resources("db", {"db": external}).db is connection

        with pytest.raises(NotImplementedError, match="execution layer"):
            bind_resources("db", {"db": owned})  # pyright: ignore[reportArgumentType]

        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "factory",
                owned,  # pyright: ignore[reportArgumentType]
            )

    def test_operator_parser_receives_resource_view(self, connection: _Connection):
        captured = {}

        @operator(resources="resource")
        def pipe(stream: RecordStream, objconf, tuples, **kwargs) -> RecordStream:
            captured["view"] = kwargs.get("resources")
            return stream

        resource = Resource.from_external(connection)
        context = Context().with_resource("resource", resource)
        list(pipe([{"a": 1}], context=context))
        assert captured["view"].resource is connection


class TestResourceImmutability:
    """
    Keep resource definitions structurally immutable.

    Fields cannot be reassigned and definition-owned containers are read-only, but
    Riko does not recursively freeze arbitrary referenced values. Do not restore
    public setters; mutable resolved state belongs to the execution layer.
    """

    def test_external_value_fields_are_read_only(self, connection: _Connection):
        resource = Resource.from_external(connection)

        with pytest.raises(AttributeError):
            resource.value = object()  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.credential = "other"  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.lazy = True  # pyright: ignore[reportAttributeAccessIssue]

    def test_referenced_value_is_not_frozen(self, connection: _Connection):
        resource = Resource.from_external(connection)
        connection.opened = False
        assert resource.value is connection

        if isinstance(resource.value, _Connection):
            assert resource.value.closed

    def test_factory_fields_and_containers_are_read_only(self):
        resource = Resource.from_factory(sync_gen_factory)

        with pytest.raises(AttributeError):
            resource.factory = sync_gen_factory  # pyright: ignore[reportAttributeAccessIssue]

        with pytest.raises(AttributeError):
            resource.kind = FactoryKind.SYNC_GEN_FACTORY  # pyright: ignore[reportAttributeAccessIssue]
