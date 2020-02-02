# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.bado.requests
~~~~~~~~~~~~~~~~~~
Provides functions for asynchronously fetching web pages

Examples:
    basic usage::

        >>> from riko import get_path
        >>> from riko.bado import requests as treq
"""

try:
    import treq
except ImportError:
    get = lambda _: lambda: None
    json_content = lambda _: lambda: None
else:
    get = treq.get
    json = treq.json_content
