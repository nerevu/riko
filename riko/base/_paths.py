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
PYPROJECT = ROOT_DIR / "pyproject.toml"


def is_http_url(url: str) -> bool:
    """
    Reports whether ``url`` is an ``http://`` or ``https://`` URL.

    Args:

        url: The URL to check.

    Returns:

        Whether ``url`` is fetched over HTTP(S).

    Examples:

        >>> is_http_url("https://example.com/feed.xml")
        True
        >>> is_http_url("httpfeed.xml")
        False

    """
    return url.startswith(("http://", "https://"))


def normalize_url(url: str, absolute: bool = True, offline: bool = False) -> str:
    """
    Normalizes a URL, host, or file name to a URL.

    URLs pass through unchanged, except relative ``file://`` paths when ``absolute`` is
    set.

    Args:

        url: A URL, host, or file name.
        absolute: Whether to resolve a relative ``file://`` path.
        offline: Whether a bare name is a bundled data file rather than a web host.

    Returns:

        The URL to open.

    Examples:

        >>> normalize_url("example.com/feed.xml")
        'http://example.com/feed.xml'
        >>> normalize_url("ftp://example.com/data.csv")
        'ftp://example.com/data.csv'

    """
    relative_file = url.startswith("file://") and not url.startswith("file:///")

    if absolute and relative_file:
        abspath = (ROOT_DIR / url[7:]).absolute()
        url = f"file://{abspath}"
    elif "://" in url or (not absolute and url.startswith("file:")):
        pass
    elif offline:
        url = f"file://{path.join(PACKAGE_DIR, 'data', url)}"
    elif url:
        url = f"http://{url}"

    return url


def get_path(name: str) -> str:
    """
    Gets the ``file://`` URL for a bundled data file name.

    A name that is already a URL (``http://``, ``ftp://``, ``file:``, …) passes
    through unchanged.

    Args:

        name: A file name in riko's bundled ``data`` directory, or a URL.

    Returns:

        The URL to read.

    Examples:

        >>> get_path("http_fixture.csv")
        'file://.../data/http_fixture.csv'
        >>> get_path("https://example.com/feed.xml")
        'https://example.com/feed.xml'
        >>> get_path("ftp://example.com/data.csv")
        'ftp://example.com/data.csv'

    """
    return normalize_url(name, absolute=False, offline=True)


@overload
def get_temp_file(as_path: Literal[True]) -> str: ...
@overload
def get_temp_file(as_path: Literal[False] = ...) -> IO[bytes]: ...
def get_temp_file(as_path: bool = False) -> str | IO[bytes]:
    if as_path:
        with NamedTemporaryFile(delete=False) as fp:
            return fp.name
    else:
        return NamedTemporaryFile(delete=True, delete_on_close=False)
