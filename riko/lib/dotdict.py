# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    riko.lib.dotdict
    ~~~~~~~~~~~~~~~~~~~

    Provides methods for creating dicts using dot notation
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

from functools import reduce

from builtins import *
from feedparser import FeedParserDict

from . import log

logger = log.Logger(__name__).logger


class DotDict(FeedParserDict):
    """A dictionary whose keys can be accessed using dot notation
    r = {'a': {'content': 'value'}}
    e.g. r['a.content'] -> ['a']['content']

    """
    def __init__(self, data=None, **kwargs):
        super(DotDict, self).__init__(self, **kwargs)
        self.update(data)

    def __getitem__(self, key):
        try:
            value = dict.__getitem__(self, key)
        except KeyError:
            value = super(DotDict, self).__getitem__(key)

        if hasattr(value, 'keys'):
            value = DotDict(value)

        return value

    def __setitem__(self, key, value):
        return dict.__setitem__(self, key, value)

    def _parse_key(self, key=None):
        try:
            keys = key.rstrip('.').split('.') if key else []
        except AttributeError:
            keys = [key['subkey']] if key else []

        return keys

    def _parse_value(self, value, key, default=None):
        try:
            parsed = value[key]
        except KeyError:
            parsed = value['value'] if 'value' in value else default
        except (TypeError, IndexError):
            if hasattr(value, 'append'):
                parsed = [v[key] for v in value]
            else:
                parsed = value

        return default if parsed is None else parsed

    def delete(self, key):
        keys = self._parse_key(key)
        last = keys[-1]

        try:
            del reduce(lambda i, k: DotDict(i).get(k), [self] + keys[:-1])[last]
        except KeyError:
            pass

    def set(self, key, value):
        keys = self._parse_key(key)
        first = keys[:-1]
        last = keys[-1]
        item = self.copy()
        reduce(lambda i, k: i.setdefault(k, {}), first, item)[last] = value
        dict.update(self, item)

    def get(self, key=None, default=None, **kwargs):
        keys = self._parse_key(key)
        value = DotDict(self.copy())

        for key in keys:

            try:
                key = int(key)
            except ValueError:
                pass

            value = self._parse_value(value, key, default)

        if hasattr(value, 'keys') and 'terminal' in value:
            # value fed in from another module
            feed = kwargs[value['terminal']]
            value = next(feed)[value.get('path', 'content')]
        elif hasattr(value, 'keys') and 'value' in value:
            value = value['value']

        return DotDict(value) if hasattr(value, 'keys') else value

    def update(self, data=None):
        if not data:
            return

        _dict = dict(data)
        dot_keys = [k for k in _dict if '.' in k]

        if dot_keys:
            # skip key if a subkey redefines it
            # i.e., 'author.name' has precedence over 'author'
            keys = ['.'.join(self._parse_key(k)[:-1]) for k in dot_keys]
            items = ((k, v) for k, v in _dict.items() if k not in keys)
        else:
            items = _dict.items()

        [self.set(key, value) for key, value in items]
