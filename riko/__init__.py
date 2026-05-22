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

from meza import compat

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


def get_path(name: str):
    if name.startswith("http") or name.startswith("file:"):
        url = name
    else:
        url = f"file://{p.join(PARENT_DIR, "data", name)}"

    return url


def get_abspath(url: str, offline=False):
    if url.startswith("http"):
        pass
    elif url.startswith("file:///"):
        pass
    elif url.startswith("file://"):
        parent = p.dirname(p.dirname(__file__))
        rel_path = url[7:]
        abspath = p.abspath(p.join(parent, rel_path))
        url = "file://%s" % abspath
    elif offline:
        url = get_path(url)
    else:
        url = "http://%s" % url if url and "://" not in url else url

    return compat.decode(url)


def replacer(content: str, old: str, new="_") -> str:
    if old:
        replaced = content.replace(old, new)
    elif content[0].isdecimal() or not content[0].isascii():
        replaced = f"{new}{content}"
    else:
        replaced = content

    return replaced


class Context(object):
    """The context of a pipeline
        verbose = debug printing during compilation and running
        describe_input = return pipe input requirements
        describe_dependencies = return a list of sub-pipelines used
        test = takes input values from default (skips the console prompt)
        inputs = a dictionary of values that overrides the defaults
            e.g. {'name one': 'test value1'}
        submodule = takes input values from inputs (or default)
    """

    def __init__(self, **kwargs):
        self.verbose = kwargs.get('verbose', False)
        self.test = kwargs.get('test', False)
        self.describe_input = kwargs.get('describe_input', False)
        self.describe_dependencies = kwargs.get('describe_dependencies', False)
        self.inputs = kwargs.get('inputs', {})
        self.submodule = kwargs.get('submodule', False)

    def __repr__(self):
        content = f"verbose={self.verbose}, test={self.test}, "
        content += f"describe_input={self.describe_input}, "
        content = f"describe_dependencies={self.describe_dependencies}, "
        content = f"inputs={self.inputs}, submodule={self.submodule}"
        return f"Context({content})"
