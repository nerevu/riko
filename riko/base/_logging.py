# vim: sw=4:ts=4:expandtab
"""Provides riko's shared logger configuration and the per-module logger factory."""

from __future__ import annotations

from logging import (
    CRITICAL,
    DEBUG,
    ERROR,
    INFO,
    NOTSET,
    WARNING,
    Formatter,
    Logger,
    LogRecord,
    getLogger,
)

import pygogo as gogo
from pygogo.formatters import DATEFMT
from pygogo.handlers import stderr_hdlr

# https://stackoverflow.com/a/56944256/408556
GREY = "\x1b[38;21m"
YELLOW = "\x1b[33;21m"
RED = "\x1b[31;21m"
BOLD_RED = "\x1b[31;1m"
RESET = "\x1b[0m"
LOGGER_NAME = "riko"


# https://flask.palletsprojects.com/en/1.1.x/logging/#injecting-request-information
class DefaultFormatter(Formatter):
    def format(self, record: LogRecord) -> str:
        formats = {
            DEBUG: f"{GREY} {self._fmt} {RESET}",
            INFO: f"{GREY} {self._fmt} {RESET}",
            WARNING: f"{YELLOW} {self._fmt} {RESET}",
            ERROR: f"{RED} {self._fmt} {RESET}",
            CRITICAL: f"{BOLD_RED} {self._fmt} {RESET}",
        }

        log_fmt = formats.get(record.levelno)
        return Formatter(log_fmt, datefmt=self.datefmt).format(record)


def_format: str = "[%(levelname)s %(asctime)s] in %(module)s:%(lineno)s: %(message)s"
def_formatter: DefaultFormatter = DefaultFormatter(def_format, datefmt=DATEFMT)

going: gogo.Gogo = gogo.Gogo(
    LOGGER_NAME,
    low_hdlr=stderr_hdlr(),
    high_hdlr=stderr_hdlr(),
    low_level="debug",
    high_level="warning",
    low_formatter=def_formatter,
    high_formatter=def_formatter,
    monolog=True,
)


def set_log_level(level: int) -> None:
    """
    Sets the level every riko logger inherits.

    Args:

        level: The minimum level riko logs, e.g. ``logging.INFO``.

    Examples:

        >>> set_log_level(WARNING)

    """
    getLogger(LOGGER_NAME).setLevel(level)


def get_logger(name: str) -> Logger:
    """
    Gets the riko logger for a module name.

    Args:

        name: The module's ``__name__``.

    Returns:

        The module's logger, which follows ``set_log_level``.

    Examples:

        >>> get_logger("riko.modules.fetch").name
        'riko.modules.fetch'

    """
    logger: Logger = going.get_logger(name.removeprefix(f"{LOGGER_NAME}."))
    logger.setLevel(NOTSET)
    return logger


set_log_level(WARNING)
