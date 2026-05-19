# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko
~~~~
Provides functions for analyzing and processing streams of structured data

Examples:
    basic usage::

        >>> from itertools import chain
        >>> from functools import partial
        >>> from riko.modules import itembuilder, strreplace
        >>> from riko.collections import SyncPipe
        >>>
        >>> ib_conf = {
        ...     'attrs': [
        ...         {'key': 'link', 'value': 'www.google.com', },
        ...         {'key': 'title', 'value': 'google', },
        ...         {'key': 'author', 'value': 'Tommy'}]}
        >>>
        >>> sr_conf = {
        ...     'rule': [{'find': 'Tom', 'param': 'first', 'replace': 'Tim'}]}
        >>>
        >>> items = itembuilder.pipe(conf=ib_conf)
        >>> pipe = partial(strreplace.pipe, conf=sr_conf, field='author')
        >>> replaced = map(pipe, items)
        >>> next(chain.from_iterable(replaced)) == {
        ...     'link': 'www.google.com', 'title': 'google',
        ...     'strreplace': 'Timmy', 'author': 'Tommy'}
        True
"""
from os import path as p
from importlib.metadata import version, metadata

# https://github.com/astral-sh/uv/issues/7533#issuecomment-2472804995
meta = metadata("riko")

PACKAGE_INFO = {
    "__version__": version("riko"),
    "__title__": meta["Name"],
    "__package_name__": meta["Name"],
    "__description__": meta.get("Summary") or meta.get("Description", ""),
    "__license__": meta.get("License-Expression") or meta.get("License", ""),
    "__author__": meta.get("Author", ""),
    "__email__": meta.get("Author-email", ""),
}


def __getattr__(name: str) -> str:
    if name in PACKAGE_INFO:
        return PACKAGE_INFO[name]
    else:
        msg = f"module {__name__} has no attribute {name}"
        raise AttributeError(msg)


__copyright__ = "Copyright 2015 Reuben Cummings"

PARENT_DIR = p.abspath(p.dirname(__file__))
ENCODING = "utf-8"


def get_path(name):
    return "file://%s" % p.join(PARENT_DIR, "data", name)
