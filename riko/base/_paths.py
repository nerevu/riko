# vim: sw=4:ts=4:expandtab
"""
File and URL path resolution for bundled data and external resources.

Examples:

    Basic usage::

        >>> from riko import get_path
        >>>
        >>> get_path("spreadsheet.csv").startswith("file://")
        True

"""

from functools import partial
from os import path
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Literal, overload

PACKAGE_DIR = Path(__file__).parent.parent.absolute()
ROOT_DIR = PACKAGE_DIR.parent


def normalize_url(url: str, absolute: bool = True, offline: bool = False) -> str:
    passable = ("http", "file:///" if absolute else "file:")

    if url.startswith(passable):
        pass
    elif absolute and url.startswith("file://"):
        abspath = (ROOT_DIR / url[7:]).absolute()
        url = f"file://{abspath}"
    elif offline:
        url = f"file://{path.join(PACKAGE_DIR, 'data', url)}"
    else:
        url = f"http://{url}" if url and "://" not in url else url

    return url


get_path: partial[str] = partial(normalize_url, absolute=False, offline=True)


@overload
def get_temp_file(as_path: Literal[True]) -> str: ...  # noqa: E704
@overload
def get_temp_file(as_path: Literal[False] = ...) -> IO[bytes]: ...  # noqa: E704
def get_temp_file(as_path: bool = False) -> str | IO[bytes]:  # noqa: E302
    if as_path:
        with NamedTemporaryFile(delete=False) as fp:
            return fp.name
    else:
        return NamedTemporaryFile(delete=True, delete_on_close=False)
