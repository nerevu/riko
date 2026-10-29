# vim: sw=4:ts=4:expandtab
"""
Prepares pipe callables' calls and stamps their discovery metadata.

Shared by the execution layer and the module decorators, which both build calls from
plain wrappers.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING, Unpack

from riko.types._wrappers import is_wrapper_meta

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from riko.types._options import RawCallOptions
    from riko.types._wrappers import (
        ExtraName,
        Func,
        ModuleWrapper,
        PrepareConf,
        PreparedCall,
        Preparer,
        SplitterWrapperOutput,
        WrapperOutput,
    )
    from riko.types.modules import ModuleSubtype, ModuleType


def prepare_call(
    wrapper: Func[WrapperOutput | SplitterWrapperOutput],
    *_: ExtraName,
    conf: PrepareConf | None = None,
    **options: Unpack[RawCallOptions],
) -> PreparedCall:
    """
    Prepares a pipe's configuration and call options for reuse over many items.

    Calling the return value calls ``wrapper`` with its configuration, call options,
    ``context``, and keyword arguments. Can be pickled whenever ``wrapper`` can.

    Args:

        wrapper: The pipe to call.

        _: The names of the extra inputs delivered with each item. Unused, since
            ``wrapper`` sees each call's keyword arguments itself.

    Kwargs:

        conf: The module configuration.

        assign (str): The field results are assigned to. Defaults to the module
            name (or ``"content"`` for a source). Ignored when ``emit`` is true.

        emit (bool): Whether to emit results rather than assign them. Defaults to
            the parser's contract.

        field (str): The field whose value is passed to the pipe in place of the
            item.

        count (str): ``"first"`` stops after the first result. ``"all"`` keeps
            every result.

    Returns:

        A call that takes one item at a time.

    Examples:

        >>> def pipe(item=None, conf=None, context=None, **kwargs):
        ...     return iter([{**item, **conf, **kwargs}])
        >>>
        >>> call = prepare_call(pipe, conf={"x": 1}, emit=True)
        >>> list(call({"y": 2}, other="z"))
        [{'y': 2, 'x': 1, 'emit': True, 'other': 'z'}]

    """
    return partial(wrapper, conf=conf, **options)


def build_call(
    pipe: ModuleWrapper,
    *extras: ExtraName,
    conf: PrepareConf | None = None,
    **options: Unpack[RawCallOptions],
) -> PreparedCall:
    """
    Prepares ``pipe``'s configuration and call options once for reuse over many items.

    A pipe callable prepares its own call. A plain callable registered as a module
    carries no ``prepare``, so its configuration and call options are prepared with
    ``prepare_call``.

    Args:

        pipe: The pipe to call.

        extras: The names of the extra inputs delivered with each item: a named
            input stream under its port name, positional streams as ``others``, bound
            resources as ``resources``, and a loop's embed as ``embed``.

    Kwargs:

        conf: The module configuration.

        assign (str): The field results are assigned to. Defaults to the module
            name (or ``"content"`` for a source). Ignored when ``emit`` is true.

        emit (bool): Whether to emit results rather than assign them. Defaults to
            the parser's contract.

        field (str): The field whose value is passed to the pipe in place of the
            item.

        count (str): ``"first"`` stops after the first result. ``"all"`` keeps
            every result.

    Returns:

        A call that takes one item at a time.

    Examples:

        >>> def pipe(item=None, conf=None, context=None, **kwargs):
        ...     return iter([{**item, **conf}])
        >>>
        >>> list(build_call(pipe, conf={"x": 1})({"y": 2}))
        [{'y': 2, 'x': 1}]

    """
    prepare: Preparer | None = getattr(pipe, "prepare", None)

    if prepare is None:
        call = prepare_call(pipe, *extras, conf=conf, **options)
    else:
        call = prepare(*extras, conf=conf, **options)

    return call


def stamp_wrapper_meta(
    target: Callable[..., object],
    *,
    name: str,
    module_type: ModuleType | str,
    subtype: ModuleSubtype,
    subtypes: Iterable[ModuleSubtype],
    pollable: bool,
    loopable: bool,
    isasync: bool,
    sequential_inputs: bool = False,
    prepare: Preparer | None = None,
) -> None:
    """
    Stamps the discovery metadata every pipe callable carries onto ``target``.

    Afterwards ``target`` carries every attribute named in ``WRAPPER_META``, and a
    ``prepare`` that applies configuration and call options for reuse.

    Args:

        target: The callable to annotate in place.
        name: The module name.
        module_type: The module kind, e.g., "processor" (stored as ``type``).
        subtype: The primary module subtype.
        subtypes: Every subtype the module supports.
        pollable: Whether the module can be polled.
        loopable: Whether ``loop`` can embed the module.
        isasync: Whether ``target`` is an ``async_pipe``.

        sequential_inputs: Whether the module reads its input streams one at a time
            (default: False).

        prepare: Prepares a call for reuse over many items. Defaults to preparing
            ``target`` with its configuration and call options (default: None).

    Examples:

        >>> def pipe(item=None, **kwargs):
        ...     return iter([])
        >>>
        >>> stamp_wrapper_meta(
        ...     pipe,
        ...     name="mine",
        ...     module_type="processor",
        ...     subtype="transformer",
        ...     subtypes=("transformer",),
        ...     pollable=False,
        ...     loopable=True,
        ...     isasync=False,
        ... )
        >>> pipe.type, pipe.isasync
        ('processor', False)
        >>> list(pipe.prepare(conf={"x": 1})({"y": 2}))
        []

    """
    setattr(target, "name", name)  # noqa: B010
    setattr(target, "type", module_type)  # noqa: B010
    setattr(target, "subtype", subtype)  # noqa: B010
    setattr(target, "subtypes", frozenset(subtypes))  # noqa: B010
    setattr(target, "pollable", pollable)  # noqa: B010
    setattr(target, "loopable", loopable)  # noqa: B010
    setattr(target, "isasync", isasync)  # noqa: B010
    setattr(target, "sequential_inputs", sequential_inputs)  # noqa: B010
    preparer = prepare

    if preparer is None and is_wrapper_meta(target):
        preparer = partial(prepare_call, target)

    setattr(target, "prepare", preparer)  # noqa: B010
