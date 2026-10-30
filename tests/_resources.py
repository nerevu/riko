# vim: sw=4:ts=4:expandtab
"""
Provides shared resource values, factories, fixtures, and checks for resource tests.

The root ``conftest.py`` loads this module as a plugin, so its fixtures are
available to every test without an import.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from functools import wraps
from typing import TYPE_CHECKING

import pytest

from riko.definitions._resource_definition import Resource

if TYPE_CHECKING:
    from collections.abc import Callable


CREDENTIAL = "microsoft/cif"
SCALAR = 42


class Connection:
    def __init__(self):
        self.opened = True

    @property
    def closed(self):
        return not self.opened

    def close(self):
        self.opened = False


class AsyncConnection(Connection):
    async def aclose(self):
        self.opened = False


def close_connection(conn: Connection):
    conn.close()


async def close_async_connection(conn: AsyncConnection):
    await conn.aclose()


def sync_callable_factory():
    return Connection()


async def async_callable_factory():
    return AsyncConnection()


def sync_gen_factory(credential: str | None = None):
    connection = Connection()
    print(f"\nCreating a fresh sync db using {connection}")
    yield connection
    print("\nClosing sync db...")


async def async_gen_factory(credential: str | None = None):
    connection = AsyncConnection()
    print(f"\nCreating a fresh async db using {connection}")
    yield connection
    print("\nClosing async db...")


@contextmanager
def sync_cm_factory(credential: str | None = None):
    connection = Connection()
    print(f"Setting up sync db using {connection}")

    try:
        yield connection
    finally:
        print("Cleaning sync db...")


@asynccontextmanager
async def async_cm_factory(credential: str | None = None):
    connection = AsyncConnection()
    print(f"Setting up async db using {connection}")

    try:
        yield connection
    finally:
        print("Cleaning async db...")


def _passthrough[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        return func(*args, **kwargs)

    return wrapper


wrapped_sync_gen_factory = _passthrough(sync_gen_factory)
wrapped_async_gen_factory = _passthrough(async_gen_factory)
wrapped_sync_cm_factory = _passthrough(sync_cm_factory)
wrapped_async_cm_factory = _passthrough(async_cm_factory)


def check_credential_and_lazy(resource):
    assert resource.credential == CREDENTIAL
    assert resource.lazy


def check_metadata(
    resource,
    typ: type,
    *,
    external: bool,
    reusable: bool,
    classification: type | None = None,
):
    assert isinstance(resource, typ)
    assert resource.external == external
    assert resource.reusable == reusable

    if classification is not None:
        assert isinstance(resource._plan, classification)


VALUE_FACTORIES = [
    pytest.param(sync_callable_factory, close_connection, id="sync"),
    pytest.param(async_callable_factory, close_async_connection, id="async"),
]


connection = pytest.fixture(sync_callable_factory)
sync_contextmanager = pytest.fixture(sync_cm_factory)
scalar = pytest.fixture(lambda: SCALAR)


@pytest.fixture
def one_shot_resource(connection: Connection) -> Resource[Connection]:
    return Resource(connection)


@pytest.fixture
def external_resource(connection: Connection) -> Resource[Connection]:
    return Resource.from_external(connection)
