"""
riko.helpers
~~~~~~~~~~~~

Provides misc helper functions
"""

import logging
import pdb
from json.decoder import JSONDecodeError
from logging import Formatter
from traceback import format_exception

import pygogo as gogo
from pygogo.formatters import DATEFMT

# https://stackoverflow.com/a/56944256/408556
GREY = "\x1b[38;21m"
YELLOW = "\x1b[33;21m"
RED = "\x1b[31;21m"
BOLD_RED = "\x1b[31;1m"
RESET = "\x1b[0m"


# https://flask.palletsprojects.com/en/1.1.x/logging/#injecting-request-information
class DefaultFormatter(Formatter):
    def format(self, record):
        FORMATS = {
            logging.DEBUG: f"{GREY} {self._fmt} {RESET}",
            logging.INFO: f"{GREY} {self._fmt} {RESET}",
            logging.WARNING: f"{YELLOW} {self._fmt} {RESET}",
            logging.ERROR: f"{RED} {self._fmt} {RESET}",
            logging.CRITICAL: f"{BOLD_RED} {self._fmt} {RESET}",
        }

        log_fmt = FORMATS.get(record.levelno)
        return Formatter(log_fmt).format(record)


def_format = "[%(levelname)s %(asctime)s] in %(module)s:%(lineno)s: %(message)s"
def_formatter = DefaultFormatter(def_format, datefmt=DATEFMT)

logger = gogo.Gogo(
    __name__,
    low_formatter=def_formatter,
    high_formatter=def_formatter,
    monolog=True,
).logger
logger.propagate = False


def log(message=None, ok=True, r=None, exit_on_completion=False, **_):
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
        exit(0 if ok else 1)
    else:
        return ok


def get_verbosity(verbosity="", debug=False, max_verbosity=3, **_):
    def_verbosity = "3" if debug else "1"
    return min(int(verbosity or def_verbosity), max_verbosity)


def exception_hook(etype, value=None, tb=None, debug=False, callback=None, **_):
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


def slugify(text):
    return text.lower().strip().replace(" ", "-")


def select_by_id(_result, _id, id_field):
    try:
        result = next(r for r in _result if _id == r[id_field])
    except StopIteration:
        result = {}

    return result
