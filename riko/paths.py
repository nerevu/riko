# vim: sw=4:ts=4:expandtab
"""
riko.paths
~~~~~~~~~~
File/URL path resolution: locating bundled data files (``get_path``) and
normalizing file/http URLs to absolute form (``get_abspath``).
"""

from os import path
from pathlib import Path

PACKAGE_DIR = Path(__file__).parent.absolute()
ROOT_DIR = PACKAGE_DIR.parent


def get_path(name: str) -> str:
    if name.startswith(("http", "file:")):
        url = name
    else:
        url = f"file://{path.join(PACKAGE_DIR, 'data', name)}"

    return url


def get_abspath(url: str, offline: bool = False) -> str:
    if url.startswith(("http", "file:///")):
        pass
    elif url.startswith("file://"):
        abspath = (ROOT_DIR / url[7:]).absolute()
        url = f"file://{abspath}"
    elif offline:
        url = get_path(url)
    else:
        url = f"http://{url}" if url and "://" not in url else url

    return url
