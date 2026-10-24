# vim: sw=4:ts=4:expandtab
"""
The stable, runnable ``Pipeline``.

A ``Pipeline`` is a ``PipelineDefinition`` that runs. Iterating it, synchronously or
asynchronously, executes its workflow and yields the items at its default output.
Composing a ``Pipeline`` yields another ``Pipeline``, so a chain stays runnable.

Examples:

    Basic usage::

        >>> from riko import Pipeline
        >>>
        >>> source = [{"x": 2}, {"x": 1}]
        >>> pipeline = Pipeline(source=source).sort(conf={"rule": {"field": "x"}})
        >>> list(pipeline)
        [{'x': 1}, {'x': 2}]

"""

from __future__ import annotations

from contextlib import aclosing, closing
from functools import partial
from typing import TYPE_CHECKING, Concatenate, cast, overload

from attrs import define
from typing_extensions import TypeVar

from riko.base._exceptions import EmptyPipelineError
from riko.base._sentinels import MISSING, MissingType
from riko.definitions._composition import PipelineDefinition
from riko.types._streams import Item

from ._resolver import dispatcher
from ._run import arun_pipeline, run_pipeline

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable, Generator

    from riko.definitions._nodes import CallableVersion
    from riko.definitions._resource_definition import ResourcesLike
    from riko.types._enums import IdentityModeLike


T = TypeVar("T", default=Item)


@define(frozen=True, slots=True, repr=False)
class Pipeline(PipelineDefinition[T]):
    """
    A runnable ``PipelineDefinition``: iterating it yields its default output.

    Examples:

        >>> items = [{"x": 1}, {"x": 2}, {"x": 3}]
        >>> pipeline = Pipeline(source=items).tail(conf={"count": 2})
        >>> for item in pipeline:
        ...     print(item)
        {'x': 2}
        {'x': 3}

    """

    def __iter__(self) -> Generator[T, None]:
        """
        Synchronously runs the pipeline with its context and execution settings.

        Each iteration is a fresh run that owns its resources for the lifetime of
        the returned iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        return run_pipeline(self, dispatcher)

    def __aiter__(self) -> AsyncGenerator[T, None]:  # noqa: PYI058
        """
        Asynchronously runs the pipeline with its context and execution settings.

        Each iteration is a fresh run that owns its resources for the lifetime of
        the returned async iterator.

        Yields:

            The items produced at the pipeline's default output.

        """
        return arun_pipeline(self, dispatcher)

    def map[R](
        self,
        fn: Callable[[T], R] | Callable[Concatenate[T, ...], R],
        *,
        resources: ResourcesLike = (),
        version: CallableVersion = MISSING,
        identity: IdentityModeLike | None = None,
        **kwargs: object,
    ) -> Pipeline[R]:
        """
        Chains ``fn`` as its own node and calls it with each item.

        ``fn`` receives each item as is and its return value becomes the next item. It
        is called with the item, then the keyword arguments, then each bound resource as
        a keyword named after its alias. Keyword arguments must be JSON-native, so use
        ``functools.partial`` to pass a non-JSON-native value.

        Args:

            fn: The callable to apply to each item.

        Kwargs:

            resources: The Context resources ``fn`` receives as keywords.
            version: The durable identity of ``fn``'s behavior, if declared.

            identity: How each result's identity relates to its input item
                (``"preserve"``, ``"derive"``, or ``"combine"``), if declared. Not yet
                implemented.

            kwargs (JSONValue): The JSON-native keywords ``fn`` receives with each item.

        Returns:

            A new pipeline whose default output is the callable node.

        Raises:

            InvalidPipelineError: If a resource alias is not a Python identifier, a
                keyword argument shares its name with a resource alias, a keyword
                argument is not JSON-native, or ``identity`` is not an identity mode.

            TypeError: If ``fn`` is not callable, or ``version`` is ``None`` or
                unhashable.

        Examples:

            >>> from operator import itemgetter
            >>>
            >>> pipeline = Pipeline(source=[{"x": 1}, {"x": 2}])
            >>> list(pipeline.map(lambda item: item["x"] * 10))
            [10, 20]
            >>> list(pipeline.map(itemgetter("x")))
            [1, 2]

        """
        mapper = partial(super().map, fn, resources=resources, **kwargs)
        return cast("Pipeline[R]", mapper(version=version, identity=identity))

    @overload
    def first(self) -> T: ...
    @overload
    def first[D](self, default: D) -> T | D: ...
    def first[D](self, default: D | MissingType = MISSING) -> T | D:
        """
        Runs the pipeline just long enough to read its first item.

        The run is closed as soon as the item is read.

        Args:

            default: The value returned when the pipeline produces no items.

        Returns:

            The first item at the pipeline's default output, or ``default``.

        Raises:

            EmptyPipelineError: If the pipeline produces no items and no
                ``default`` is given.

        Examples:

            >>> Pipeline(source=[{"x": 1}, {"x": 2}]).first()
            {'x': 1}
            >>> print(Pipeline(source=[]).first(default=None))
            None

        """
        with closing(iter(self)) as stream:
            item = next(stream, default)

        if isinstance(item, MissingType):
            raise EmptyPipelineError

        return item

    @overload
    async def afirst(self) -> T: ...
    @overload
    async def afirst[D](self, default: D) -> T | D: ...
    async def afirst[D](self, default: D | MissingType = MISSING) -> T | D:
        """
        Asynchronously runs the pipeline just long enough to read its first item.

        The run is closed as soon as the item is read.

        Args:

            default: The value returned when the pipeline produces no items.

        Returns:

            The first item at the pipeline's default output, or ``default``.

        Raises:

            EmptyPipelineError: If the pipeline produces no items and no
                ``default`` is given.

        Examples:

            >>> from riko import run
            >>>
            >>> async def main():
            ...     print(await Pipeline(source=[{"x": 1}]).afirst())
            >>>
            >>> run(main)
            {'x': 1}

        """
        async with aclosing(aiter(self)) as stream:
            item = await anext(stream, default)

        if isinstance(item, MissingType):
            raise EmptyPipelineError

        return item


__all__ = ["Pipeline"]
