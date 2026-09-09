# vim: sw=4:ts=4:expandtab
"""Tests the execution-resource foundation (``riko.resources`` + Context wiring)."""

from contextlib import (
    AbstractAsyncContextManager,
    AbstractContextManager,
    asynccontextmanager,
    contextmanager,
)
from functools import partial
from typing import cast

import pytest

from riko.context import Context
from riko.modules import operator
from riko.resources import (
    OneShotResource,
    Resource,
    ReusableResource,
    _FactoryKind,
    bind_resources,
    classify_factory,
)
from riko.types._guards import is_context_manager
from riko.types._io import CloseableType
from riko.types._resource import LifecycleFactory, ResourceValue, ValueFactory
from riko.types._streams import Stream
from tests import async_test

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
    classification: _FactoryKind | None = None,
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
            (sync_gen_factory, _FactoryKind.SYNC_GEN_FACTORY),
            (async_gen_factory, _FactoryKind.ASYNC_GEN_FACTORY),
            (sync_cm_factory, _FactoryKind.SYNC_CM_FACTORY),
            (async_cm_factory, _FactoryKind.ASYNC_CM_FACTORY),
        ],
    )
    def test_resource_metadata[T](
        self, factory: LifecycleFactory[T], classification: _FactoryKind
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
                _FactoryKind.SYNC_CALLABLE_FACTORY,
            ),
            (
                async_callable_factory,
                close_async_connection,
                _FactoryKind.ASYNC_CALLABLE_FACTORY,
            ),
        ],
    )
    def test_resource_metadata[T](
        self, factory: ValueFactory[T], cleanup, classification: _FactoryKind
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


class TestValues:
    @pytest.mark.parametrize(
        "value_fixture",
        [
            "scalar",
            "connection",
            "sync_contextmanager",
            "one_shot_resource",
            "external_resource",
        ],
    )
    def test_raises[T](self, value_fixture, request):
        value: ResourceValue[T] | Resource[T] = request.getfixturevalue(value_fixture)

        if not isinstance(value, ReusableResource):
            with pytest.raises(TypeError, match="Invalid resource factory"):
                Context().with_resource(  # pyright: ignore[reportCallIssue]
                    "value",
                    value,  # pyright: ignore[reportArgumentType]
                )

        if isinstance(value, Resource):
            with pytest.raises(TypeError, match="Expected a resolved resource value"):
                Resource(value)
        elif isinstance(value, int):
            with pytest.raises(TypeError, match="Must provide a Closeable value"):
                Resource(value)
        elif not isinstance(value, CloseableType):
            with pytest.raises(TypeError, match="Expected a resolved resource value"):
                Resource(value)

            with pytest.raises(TypeError, match="Expected a resolved resource"):
                Resource.from_external(value)

        if not is_context_manager(value):
            with pytest.raises(TypeError, match="Invalid lifecycle factory"):
                Resource.from_lifecycle(value)  # pyright: ignore[reportArgumentType]

        if is_context_manager(value):
            with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
                Resource.from_factory(value)  # pyright: ignore[reportArgumentType]
        else:
            with pytest.raises(TypeError, match="Invalid resource factory"):
                Resource.from_factory(value)  # pyright: ignore[reportArgumentType]

    @async_test
    async def test_async_raises[T](
        self,
        async_connection: _AsyncConnection,
        async_contextmanager: AbstractAsyncContextManager[_AsyncConnection],
    ):
        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "value",
                async_connection,  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Invalid resource factory"):
            Context().with_resource(  # pyright: ignore[reportCallIssue]
                "value",
                async_contextmanager,  # pyright: ignore[reportArgumentType]
            )

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource(async_contextmanager)

        with pytest.raises(TypeError, match="Expected a resolved resource"):
            Resource.from_external(async_contextmanager)

        with pytest.raises(TypeError, match=r"ValueFactory.*cleanup function"):
            Resource.from_factory(
                async_contextmanager  # pyright: ignore[reportArgumentType]
            )

    @pytest.mark.parametrize(
        "value_fixture",
        [
            "scalar",
            "connection",
            "sync_contextmanager",
            "one_shot_resource",
            "external_resource",
        ],
    )
    def test_credential_and_lazy_carried[T](self, value_fixture, request):
        value: ResourceValue[T] | Resource[T] = request.getfixturevalue(value_fixture)

        if isinstance(value, ReusableResource):
            with pytest.raises(TypeError, match=r"credential.*lazy.*LifecycleFactory"):
                Context().with_resource(
                    "value",  # pyright: ignore[reportCallIssue]
                    value,  # pyright: ignore[reportArgumentType]
                    credential=_CREDENTIAL,
                    lazy=True,
                )

        if is_context_manager(value):
            resource = Resource.from_lifecycle(value, credential=_CREDENTIAL, lazy=True)
            _test_credential_and_lazy(resource)

    @pytest.mark.parametrize(
        "value_fixture",
        [
            "scalar",
            "connection",
            "sync_contextmanager",
            "one_shot_resource",
            "external_resource",
        ],
    )
    def test_resource_metadata[T](self, value_fixture, request):
        value: ResourceValue[T] | Resource[T] = request.getfixturevalue(value_fixture)

        if isinstance(value, ReusableResource):
            context = Context().with_resource("value", value)
            resource = context.resources["value"]
            _test_metadata(resource, ReusableResource, external=True, reusable=True)

        if isinstance(value, Resource):
            pass
        elif isinstance(value, int):
            resource = Resource(value, cleanup=lambda x: None)
            _test_metadata(resource, OneShotResource, external=False, reusable=False)
        elif isinstance(value, CloseableType):
            resource = Resource(value)
            _test_metadata(resource, OneShotResource, external=False, reusable=False)

        if isinstance(value, Resource):
            pass
        elif isinstance(value, (int, CloseableType)):
            resource = Resource.from_external(value)
            _test_metadata(resource, ReusableResource, external=True, reusable=True)

        if is_context_manager(value):
            resource = Resource.from_lifecycle(value)
            _test_metadata(resource, OneShotResource, external=False, reusable=False)

            casted = cast(ValueFactory[AbstractContextManager[_Connection]], value)
            resource = Resource.from_factory(casted, cleanup=cleanup_contextmanager)
            _test_metadata(resource, ReusableResource, external=False, reusable=True)

    @pytest.mark.parametrize(
        "value_fixture",
        [
            "scalar",
            "connection",
            "sync_contextmanager",
            "one_shot_resource",
            "external_resource",
        ],
    )
    def test_resource_opens_and_closes[T](self, value_fixture, request):
        value: ResourceValue[T] | Resource[T] = request.getfixturevalue(value_fixture)

        if isinstance(value, ReusableResource):
            context = Context().with_resource("value", value)
            resource = context.resources["value"]
            _test_open_close(resource)

        if isinstance(value, Resource):
            pass
        elif isinstance(value, int):
            resource = Resource(value, cleanup=lambda x: None)
            _test_open_close(resource, value)
        elif isinstance(value, CloseableType):
            _test_open_close(Resource(value), value)

        if isinstance(value, Resource):
            pass
        elif isinstance(value, (int, CloseableType)):
            resource = Resource.from_external(value)
            _test_open_close(resource, value)

        if is_context_manager(value):
            resource = Resource.from_lifecycle(value)

            with pytest.raises(NotImplementedError, match="execution layer"):
                _test_open_close(resource, value)

    @async_test
    async def test_resource_async_opens_and_closes[T](
        self,
        async_connection: _AsyncConnection,
        async_contextmanager: AbstractAsyncContextManager[_AsyncConnection],
    ):
        await _async_test_open_close(Resource(async_connection), async_connection)

        resource = Resource.from_external(async_connection)
        await _async_test_open_close(resource, async_connection)

        resource = Resource.from_lifecycle(async_contextmanager)

        with pytest.raises(NotImplementedError, match="execution layer"):
            await _async_test_open_close(resource, async_contextmanager)


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
        def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
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
        """Name validation must complete before resource acquisition"""
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
        def pipe(stream: Stream, objconf, tuples, **kwargs) -> Stream:
            captured["view"] = kwargs.get("resources")
            return stream

        resource = Resource.from_external(connection)
        context = Context().with_resource("resource", resource)
        list(pipe([{"a": 1}], context=context))
        assert captured["view"].resource is connection
