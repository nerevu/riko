# vim: sw=4:ts=4:expandtab

"""Provides the ``manage`` command's log-level flags and uncaught-exception hook."""

from __future__ import annotations

from logging import DEBUG, ERROR, INFO, WARNING, Logger
from traceback import format_exception
from typing import TYPE_CHECKING

from riko.base._logging import get_logger

if TYPE_CHECKING:
    from types import TracebackType

logger: Logger = get_logger(__name__)


def resolve_log_level(verbose: int = 0, quiet: bool = False) -> int:
    """
    Resolves the log level the ``-v``/``-q`` flags select.

    Args:

        verbose: How many times ``-v`` was given. One selects INFO, 2+ select DEBUG.
        quiet: Whether ``-q`` was given. Selects ERROR and wins over ``verbose``.

    Returns:

        The selected ``logging`` level (WARNING when no flag is given).

    """
    if quiet:
        level = ERROR
    elif verbose >= 2:
        level = DEBUG
    elif verbose == 1:
        level = INFO
    else:
        level = WARNING

    return level


def exception_hook(
    etype: type[BaseException], value: BaseException | None, tb: TracebackType | None
) -> None:
    """
    Logs an uncaught exception's last two traceback lines as an error.

    Args:

        etype: The exception's class.
        value: The exception instance.
        tb: The exception's traceback.

    """
    exception = format_exception(etype, value, tb)

    try:
        info, error = exception[-2:]
    except ValueError:
        info, error = "", exception[0]

    logger.error(f"Exception in:\n{info}\n{error}")
