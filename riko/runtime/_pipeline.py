# vim: sw=4:ts=4:expandtab
"""
Chains modules and functions into a reusable ``Pipeline`` and runs it on items.

Start a pipeline with ``Pipeline.from_module(name, conf=...)``; extend by attribute
(``.sort(conf=...)``), with ``.pipe(name, conf=...)``, or ``.map(fn)``; or pipe by a
module name or another pipeline with ``|``. Each step returns a new pipeline and leaves
the original unchanged. ``with_context``, ``with_resource``, and ``with_execution`` set
what every run uses.

Each run is fresh. ``pipeline(items)`` and ``items | pipeline`` return a single-use
stream to iterate with ``for`` or ``async for``. ``pipeline.open(items)`` returns a
context manager for a run you may leave early, and ``first``/``afirst`` read one item.

Examples:

    Basic usage::

        >>> from riko import Pipeline
        >>>
        >>> items = [{"x": 2}, {"x": 1}]
        >>> pipeline = Pipeline.from_module("sort", conf={"rule": {"field": "x"}})
        >>> list(pipeline(items))
        [{'x': 1}, {'x': 2}]
        >>> list(items | pipeline)
        [{'x': 1}, {'x': 2}]
        >>> with pipeline.open(items) as stream:
        ...     print(next(stream))
        {'x': 1}
        >>> pipeline.first(items)
        {'x': 1}

    Asynchronous usage::

        >>> from riko import Pipeline, run
        >>>
        >>> pipeline = Pipeline.from_module("count")
        >>>
        >>> async def main():
        ...     async for item in pipeline([{"x": 1}, {"x": 2}]):
        ...         print(item)
        >>>
        >>> run(main)
        {'count': 2}

"""

from __future__ import annotations

from functools import partial
from inspect import isawaitable
from typing import TYPE_CHECKING, Concatenate, TypeGuard, overload

from attrs import define
from typing_extensions import TypeVar

from riko.base._exceptions import EmptyPipelineError
from riko.base._guards import is_mapping, is_streamlike
from riko.base._sentinels import MISSING, MissingType
from riko.definitions._pipeline_definition import PipelineDefinition
from riko.types._streams import Item

from ._resolver import dispatcher
from ._run import _PipelineRun, _PipelineStream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable, Iterator

    from riko.definitions._nodes import CallableVersion
    from riko.definitions._resource_definition import ResourcesLike
    from riko.types._enums import IdentityModeLike, ModuleNameLike
    from riko.types._frozendict import FrozenConf
    from riko.types._options import CallOptionsLike
    from riko.types._pipedef import Embed
    from riko.types._streams import InputLike, PipelineRun, PipelineStream
    from riko.types.modules import Conf


T_co = TypeVar("T_co", covariant=True, default=Item)


def _is_seed(value: object) -> TypeGuard[InputLike]:
    """A seed before ``|``: one item, a stream, an async stream, or an awaitable."""
    seedlike = is_mapping(value) or is_streamlike(value) or isawaitable(value)
    return seedlike and not isinstance(value, PipelineDefinition)


@define(frozen=True, slots=True, repr=False)
class Pipeline(PipelineDefinition[T_co]):
    """
    An immutable, runnable chain of modules: each call with items is a fresh run.

    Chaining (``from_module``, attribute chaining, ``pipe``, ``map``, ``|``, ``write``)
    and the ``with_*`` methods return a new ``Pipeline``. Running never changes one.

    Attributes:

        workflow: The ``Workflow`` graph each run executes.

        context: The environment each run uses, including the resources it provides, or
            ``None`` for a default one.

        settings: How each run executes its per-item work.

    Examples:

        >>> items = [{"x": 1}, {"x": 2}, {"x": 3}]
        >>> pipeline = Pipeline.from_module("tail", conf={"count": 2})
        >>> for item in pipeline(items):
        ...     print(item)
        {'x': 2}
        {'x': 3}

    """

    def __call__(self, seed: InputLike | None = None, /) -> PipelineStream[T_co]:
        """
        Starts a fresh run of the pipeline fed by ``seed``.

        The returned stream is a sync or async iterator. If you need to ``break`` out of
        iteration, use ``.open`` instead, which returns a context manager.

        Args:

            seed: Items for the pipeline's open input: one item, an item stream, an
                async item stream, or an awaitable resolving to one of those. ``None``
                means no seed (default: None).

        Returns:

            A single-use stream of the items at the pipeline's default output.

        Raises:

            InvalidPipelineError: On first read, if the workflow cannot be planned, or
                no ``seed`` is given and the pipeline does not start with a source
                module.

        Examples:

            >>> pipeline = Pipeline.from_module("count")
            >>> list(pipeline([{"x": 1}, {"x": 2}]))
            [{'count': 2}]

        """
        return _PipelineStream(self, dispatcher, seed)

    def __iter__(self) -> Iterator[T_co]:
        """
        Synchronously runs a pipeline.

        Each iteration is a fresh, unseeded run.

        Returns:

            An iterator over the items at the pipeline's default output.

        Raises:

            InvalidPipelineError: On first read, if the pipeline requires a seed.

        """
        return iter(self())

    def __aiter__(self) -> AsyncIterator[T_co]:
        """
        Asynchronously runs a pipeline.

        Each iteration is a fresh, unseeded run.

        Returns:

            An async iterator over the items at the pipeline's default output.

        Raises:

            InvalidPipelineError: On first read, if the pipeline requires a seed.

        """
        return aiter(self())

    def __ror__(self, other: object) -> PipelineStream[T_co]:
        """
        Starts a fresh run fed by the items on the left of ``|``.

        Args:

            other: The item, stream, async stream, or awaitable feeding the run.

        Returns:

            A single-use stream of the items at the pipeline's default output.

        Raises:

            TypeError: If ``other`` is a string, which could be a module name or an
                item, with a hint for each.

        Examples:

            >>> items = [{"x": 2}, {"x": 1}]
            >>> pipeline = Pipeline.from_module("sort", conf={"rule": {"field": "x"}})
            >>> list(items | pipeline)
            [{'x': 1}, {'x': 2}]
            >>> list({"x": 3} | pipeline)
            [{'x': 3}]
            >>> "hash" | pipeline
            Traceback (most recent call last):
            TypeError: ...ambiguous: ...pipeline('hash')...from_module('hash')...

        """
        if isinstance(other, str):
            msg = "a string before | is ambiguous: seed one item with "
            msg += f"pipeline({other!r}), or compose "
            msg += f"Pipeline.from_module({other!r}) | pipeline"
            raise TypeError(msg)

        if _is_seed(other):
            stream = self(other)
        else:
            # Raising from __ror__ interferes with __or__
            stream = NotImplemented

        return stream

    def open(self, seed: InputLike | None = None, /) -> PipelineRun[T_co]:
        """
        Starts a run fed by ``seed`` and returns it as a context manager.

        Use ``with`` for synchronous iteration or ``async with`` for asynchronous
        iteration. Leaving the ``with`` block, including by ``break`` or an exception,
        closes the run in the task that opened it. If you want a direct stream instead,
        call the pipeline.

        Args:

            seed: Items for the pipeline's open input: one item, an item stream, an
                async item stream, or an awaitable resolving to one of those. ``None``
                means no seed (default: None).

        Returns:

            A run that closes when its block exits.

        Examples:

            >>> pipeline = Pipeline.from_module("sort", conf={"rule": {"field": "x"}})
            >>>
            >>> with pipeline.open([{"x": 2}, {"x": 1}]) as stream:
            ...     for item in stream:
            ...         print(item)
            ...         break
            {'x': 1}

        """
        return _PipelineRun(self(seed))

    def map[R](
        self,
        fn: Callable[[T_co], R] | Callable[Concatenate[T_co, ...], R],
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
            >>> items = [{"x": 1}, {"x": 2}]
            >>> pipeline = Pipeline()
            >>> list(pipeline.map(lambda item: item["x"] * 10)(items))
            [10, 20]
            >>> list(pipeline.map(itemgetter("x"))(items))
            [1, 2]

        """
        flow = self._callable_workflow(
            fn, resources=resources, version=version, identity=identity, **kwargs
        )
        return Pipeline[R](flow, context=self.context, settings=self.settings)

    def pipe(
        self,
        name: ModuleNameLike,
        *,
        conf: FrozenConf | Conf | None = None,
        options: CallOptionsLike | None = None,
        embed: Embed | None = None,
    ) -> Pipeline[Item]:
        """
        Chains the next module by name by re-pointing the default output to it.

        Args:

            name: The module to append.
            conf: The module's configuration, if any.
            options: The call options forwarded to the module, if any.
            embed: The module a loop runs per item, with its configuration, if any.

        Returns:

            A new pipeline whose default output is the appended module.

        Examples:

            >>> pipeline = Pipeline().map(str).pipe("count")
            >>> list(pipeline([1, 2]))
            [{'count': 2}]

        """
        flow = self._module_workflow(name, conf=conf, options=options, embed=embed)
        return Pipeline[Item](flow, context=self.context, settings=self.settings)

    def __getattr__(self, name: str) -> Callable[..., Pipeline[Item]]:
        """Chains a built-in module by attribute. E.g., ``.sort()`` appends sort."""
        return partial(self.pipe, self._require_attribute(name))

    def _compose[R](self, other: PipelineDefinition[R]) -> Pipeline[R]:
        """Chains ``other`` after this pipeline and combines their resources."""
        flow = self._composed_workflow(other)
        context = self._combine_context(other.context)
        return Pipeline[R](flow, context=context, settings=self.settings)

    @overload
    def __or__[R](self, other: PipelineDefinition[R]) -> Pipeline[R]: ...
    @overload
    def __or__(self, other: ModuleNameLike) -> Pipeline[Item]: ...
    def __or__(self, other: object) -> PipelineDefinition[object]:
        """
        Chains a module name or another pipeline using ``|``.

        A pipeline on the right may have any number of nodes. Its nodes get fresh ids
        where needed. ``(a | b) | c`` and ``a | (b | c)`` build the same pipeline. Its
        resources join this pipeline's context. To chain a function, use ``.map``
        instead. To configure a module, use attribute chaining or
        ``.pipe(name, conf=...)``.

        Args:

            other: Module name (string or a ``Sources``/``Transforms``/``Sinks`` member)
                or a pipeline.

        Returns:

            A new pipeline whose default output is ``other``'s.

        Raises:

            TypeError: If ``other`` is a function.

            InvalidPipelineError: If ``other`` carries execution settings; a context
                with a mode, inputs, or test flag; duplicates a resource name; or its
                workflow cannot be appended (see ``Workflow.with_workflow``).

        Examples:

            >>> pipeline = Pipeline().map(str) | Pipeline().map(len)
            >>> list(pipeline([10, 200]))
            [2, 3]

        """
        return self._chain(other)

    @overload
    def first(self, seed: InputLike | None = None, /) -> T_co: ...
    @overload
    def first[D](self, seed: InputLike | None = None, /, *, default: D) -> T_co | D: ...
    def first[D](
        self, seed: InputLike | None = None, /, *, default: D | MissingType = MISSING
    ) -> T_co | D:
        """
        Runs the pipeline just long enough to read its first item.

        The run is closed as soon as the item is read.

        Args:

            seed: Items for the pipeline's open input: one item, an item stream, an
                async item stream, or an awaitable resolving to one of those. ``None``
                means no seed (default: None).

        Kwargs:

            default: The value returned when the pipeline produces no items.

        Returns:

            The first item at the pipeline's default output, or ``default``.

        Raises:

            EmptyPipelineError: If the pipeline produces no items and no
                ``default`` is given.

        Examples:

            >>> pipeline = Pipeline.from_module("sort", conf={"rule": {"field": "x"}})
            >>> pipeline.first([{"x": 2}, {"x": 1}])
            {'x': 1}
            >>> print(pipeline.first([], default=None))
            None

        """
        with self.open(seed) as stream:
            item = next(stream, default)

        if isinstance(item, MissingType):
            raise EmptyPipelineError

        return item

    @overload
    async def afirst(self, seed: InputLike | None = None, /) -> T_co: ...
    @overload
    async def afirst[D](
        self, seed: InputLike | None = None, /, *, default: D
    ) -> T_co | D: ...
    async def afirst[D](
        self, seed: InputLike | None = None, /, *, default: D | MissingType = MISSING
    ) -> T_co | D:
        """
        Asynchronously runs the pipeline just long enough to read its first item.

        The run is closed as soon as the item is read.

        Args:

            seed: Items for the pipeline's open input: one item, an item stream, an
                async item stream, or an awaitable resolving to one of those. ``None``
                means no seed (default: None).

        Kwargs:

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
            ...     print(await Pipeline.from_module("count").afirst([{"x": 1}]))
            >>>
            >>> run(main)
            {'count': 1}

        """
        async with self.open(seed) as stream:
            item = await anext(stream, default)

        if isinstance(item, MissingType):
            raise EmptyPipelineError

        return item


__all__ = ["Pipeline"]
