# vim: sw=4:ts=4:expandtab
"""
riko._logging
~~~~~~~~~~~~~
Colorized logging formatter, verbosity parsing, a ``log`` helper, and the
``exception_hook`` used by the dev CLI (pdb on error when ``debug``).
"""

import pdb  # noqa: T100
import sys
from collections.abc import Callable
from json.decoder import JSONDecodeError
from logging import CRITICAL, DEBUG, ERROR, INFO, WARNING, Formatter, Logger, LogRecord
from traceback import format_exception
from types import TracebackType

import pygogo as gogo
import requests
from pygogo.formatters import DATEFMT

# https://stackoverflow.com/a/56944256/408556
GREY = "\x1b[38;21m"
YELLOW = "\x1b[33;21m"
RED = "\x1b[31;21m"
BOLD_RED = "\x1b[31;1m"
RESET = "\x1b[0m"


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
        return Formatter(log_fmt).format(record)


def_format: str = "[%(levelname)s %(asctime)s] in %(module)s:%(lineno)s: %(message)s"
def_formatter: DefaultFormatter = DefaultFormatter(def_format, datefmt=DATEFMT)

logger: Logger = gogo.Gogo(
    __name__,
    low_formatter=def_formatter,
    high_formatter=def_formatter,
    monolog=True,
).logger
logger.propagate = False


def log(
    message: str | None = None,
    ok: bool = True,
    r: requests.Response | None = None,
    exit_on_completion: bool = False,
    **_: object,
) -> bool | None:
    if r is not None:
        ok = r.ok

        try:
            message = r.json().get("message")
        except JSONDecodeError:
            message = r.text

    if message and ok:
        logger.info(message)
    elif message:
        logger.error(message)

    if exit_on_completion:
        sys.exit(0 if ok else 1)
    else:
        return ok


def get_verbosity(
    verbosity: str = "", debug: bool = False, max_verbosity: int = 3, **_: object
) -> int:
    def_verbosity = "3" if debug else "1"
    return min(int(verbosity or def_verbosity), max_verbosity)


def exception_hook(
    etype: type[BaseException],
    value: BaseException | None = None,
    tb: TracebackType | None = None,
    debug: bool = False,
    callback: Callable[..., None] | None = None,
    **_: object,
) -> None:
    exception = format_exception(etype, value, tb)

    try:
        info, error = exception[-2:]
    except ValueError:
        info, error = "", exception[0]

    message = f"Exception in:\n{info}\n{error}"
    log(message, ok=False)

    if debug:
        pdb.post_mortem(tb)

    callback() if callback else None
