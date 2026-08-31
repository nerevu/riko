# vim: sw=4:ts=4:expandtab
"""
Obtains and parses user input.

Use this module any time you need to obtain and parse user input to wire into
another pipe. Not loopable.

The value is read from ``inputs`` when given, falls back to ``conf["default"]``
under ``test``, and otherwise prompts on stdin.

Valid Date Values

Obvious date formats:

    Jan. 12, 2001
    10/21/1958
    15 JUN 06

Plus some unusual formats as well:

    now
    today
    yesterday
    tomorrow
    +3 days
    -10 weeks
    last year
    next month
    1181230100

Note: Relative date/time calculations reference the current UTC time. Timezones
are not currently supported.

Examples:
    Basic usage::

        >>> from riko.modules.input import pipe
        >>>
        >>> conf = {"prompt": "How old are you?", "type": "int"}
        >>> next(pipe(conf=conf, inputs={"content": "30"}))
        30
        >>> conf["test"] = True
        >>> next(pipe(conf=conf))
        0

Attributes:
    OPTS: Processor wrapper options.
    DEFAULTS: Default processor configuration.

"""

from logging import Logger
from typing import Any, cast

import pygogo as gogo

from riko.cast import CastType, SourceOpts, cast_value
from riko.types._collections import Inputs
from riko.types._configs import InputObjconf
from riko.types._options import Defaults, Opts
from riko.types._scalars import PrimitiveValue
from riko.types._streams import Item

from . import processor

OPTS: Opts = SourceOpts
DEFAULTS: Defaults = {
    "type": "text",
    "default": "",
    "prompt": "Enter text",
    "test": False,
    "input_key": "content",
}
logger: Logger = gogo.Gogo(__name__, monolog=True).logger


def parser(
    _: Item,
    extraction: object,
    objconf: InputObjconf,
    skip: bool = False,
    **kwargs: object,
) -> PrimitiveValue:
    """
    Obtains one user input value and casts it.

    Reads ``inputs[input_key]`` when ``inputs`` is given, falls back to
    ``default`` when skipping, and otherwise prompts on stdin.

    Args:
        _: The item. Unused.
        extraction: The extracted conf value. Unused.
        objconf: The pipe configuration, containing `prompt`, `default`, `type`
            and `input_key`.
        skip: Whether to use ``default`` instead of prompting.

    Returns:
        The value cast to ``objconf.type``.

    Examples:
        >>> from meza.fntools import Objectify
        >>>
        >>> inputs = {"age": "30"}
        >>> conf = {"prompt": "How old are you?", "type": "int", "input_key": "age"}
        >>> objconf = Objectify(conf)
        >>> parser(None, None, objconf, inputs=inputs)
        30

    """
    if inputs := cast(Inputs | None, kwargs.get("inputs")):
        value = inputs.get(objconf.input_key, objconf.default)
    elif objconf.test or skip or kwargs.get("test"):
        value = objconf.default
    else:
        raw = input(f"{objconf.prompt} (default={objconf.default}) ")
        value = raw or objconf.default

    return cast_value(value, CastType(objconf.type)) if objconf.type else value


@processor(DEFAULTS, isasync=True, **OPTS)
def async_pipe(*args: Any, **kwargs: object) -> PrimitiveValue:
    """
    Asynchronously prompts for text and casts it into another type.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            prompt (str): Command line prompt shown when reading from stdin
                (default: "Enter text").

            default (scalar): Value used when the input is missing or skipped
                (default: "").

            type (str): Type to cast the value to, one of "bool", "date",
                "datetime", "decimal", "float", "int", "location", "none",
                "pass", "text", "url" (default: "text").

            input_key (str): Key read from ``inputs`` to find the value — not
                the field it is assigned to (default: "content").

            test (bool): Whether to use ``default`` instead of prompting
                (default: False).

        context (Context): the execution context

    Kwargs:
        inputs (dict): Values used in place of prompting, keyed by
            ``input_key``, e.g. ``{"content": "30"}``.

        test (bool): Whether to use ``default`` instead of prompting. Same
            effect as ``conf["test"]``.

        assign (str): Field the value is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit the value directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<value>`` when ``emit`` is True (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item is given

    Examples:
        >>> from riko import run
        >>>
        >>> async def main():
        ...     conf = {"prompt": "How old are you?", "type": "int"}
        ...     result = await async_pipe(conf=conf, inputs={"content": "30"})
        ...     print(next(result))
        >>>
        >>> run(main)
        30

    """
    return parser(*args, **kwargs)


@processor(DEFAULTS, **OPTS)
def pipe(*args: Any, **kwargs: object) -> PrimitiveValue:
    """
    Prompts for text and casts it into another type.

    Args:
        item (Item | Items): The entry, or stream of entries. Unused.

        conf (dict): The pipe configuration.

            prompt (str): Command line prompt shown when reading from stdin
                (default: "Enter text").

            default (scalar): Value used when the input is missing or skipped
                (default: "").

            type (str): Type to cast the value to, one of "bool", "date",
                "datetime", "decimal", "float", "int", "location", "none",
                "pass", "text", "url" (default: "text").

            input_key (str): Key read from ``inputs`` to find the value — not
                the field it is assigned to (default: "content").

            test (bool): Whether to use ``default`` instead of prompting
                (default: False).

        context (Context): the execution context

    Kwargs:
        inputs (dict): Values used in place of prompting, keyed by
            ``input_key``, e.g. ``{"content": "30"}``.

        test (bool): Whether to use ``default`` instead of prompting. Same
            effect as ``conf["test"]``.

        assign (str): Field the value is nested under. Ignored when ``emit`` is
            True (default: "content").

        emit (bool): Whether to emit the value directly rather than assign it.
            Overrides ``assign`` (default: True).

    Yields:
        - ``<value>`` when ``emit`` is True (default)
        - ``{<assign>: <value>}`` when ``emit`` is False and no item given
        - merged ``{Item, <assign>: <value>}`` when ``emit`` is False and item is given

    Examples:
        >>> import datetime
        >>> from datetime import datetime as dt, UTC
        >>>
        >>> conf = {"prompt": "How old are you?", "type": "int"}
        >>> next(pipe(conf=conf, inputs={"content": "30"}))
        30
        >>> next(pipe(conf=conf, inputs={"content": "30"}, emit=False))
        {'content': 30}
        >>> now = dt.now(UTC)
        >>> conf = {"prompt": "When were you born?", "type": "date"}
        >>> next(pipe(conf=conf, inputs={"content": "5/4/82"})).year
        1982
        >>> stream = pipe(conf={"type": "date"}, inputs={"content": "tomorrow"})
        >>> next(stream) > now.date()
        True
        >>> matrix = [
        ...     ("float", "1", 1.0),
        ...     ("bool", "true", True),
        ...     ("text", "hello", "hello")]
        >>>
        >>> for t, c, r in matrix:
        ...     kwargs = {"conf": {"type": t}, "inputs": {"content": c}}
        ...     next(pipe(**kwargs))
        1.0
        True
        'hello'
        >>> inputs = {"content": "google.com"}
        >>> next(pipe(conf={"type": "url"}, inputs=inputs))
        'http://google.com'
        >>> inputs = {"content": "palo alto, ca"}
        >>> result = next(pipe(conf={"type": "location"}, inputs=inputs))
        >>> sorted(result)[:5]
        ['admin1', 'admin2', 'admin3', 'city', 'country']
        >>> result["city"]
        'city'

    """
    return parser(*args, **kwargs)
