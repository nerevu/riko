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

from os import path
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import IO, Literal, overload

PACKAGE_DIR = Path(__file__).parent.parent.absolute()
ROOT_DIR = PACKAGE_DIR.parent
TESTS_DIR = ROOT_DIR / "tests"
DOCS_DIR = ROOT_DIR / "docs"


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


def get_path(name: str) -> str:
    """
    Builds the ``file://`` URL for a bundled data file name.

    A name that is already an ``http`` or ``file:`` URL passes through unchanged.

    Args:

        name: A file name in riko's bundled ``data`` directory, or a URL.

    Returns:

        The URL to read.

    """
    return normalize_url(name, absolute=False, offline=True)


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
