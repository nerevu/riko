# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
riko.dotdict
~~~~~~~~~~~~
Provides a class for creating dicts with dot notation access
"""
from __future__ import (
    absolute_import, division, print_function, unicode_literals)

import pygogo as gogo

from functools import reduce
from builtins import *  # noqa pylint: disable=unused-import

logger = gogo.Gogo(__name__, monolog=True).logger


class DotDict(dict):
    """A dictionary whose keys can be accessed using dot notation
    >>> r = DotDict({'a': {'content': 'value'}})
    >>> r.get('a.content') == 'value'
    True
    >>> r['a.content'] == 'value'
    True
    """
    def __init__(self, data=None, **kwargs):
        self.update(data)

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
            try:
                parsed = value['value']
            except KeyError:
                parsed = default
        except (TypeError, IndexError):
            if hasattr(value, 'append'):
                parsed = [v[key] for v in value]
            else:
                parsed = value

        return default if parsed is None else parsed

    def __getitem__(self, key):
        keys = self._parse_key(key)
        value = super(DotDict, self).__getitem__(keys[0])

        if len(keys) > 1:
            return value['.'.join(keys[1:])]
        elif hasattr(value, 'keys') and 'value' in value:
            value = value['value']

        return DotDict(value) if hasattr(value, 'keys') else value

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
            stream = kwargs[value['terminal']]
            value = next(stream)[value.get('path', 'content')]
        elif hasattr(value, 'keys') and 'value' in value:
            value = value['value']

        return DotDict(value) if hasattr(value, 'keys') else value

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
        super(DotDict, self).update(item)

    def update(self, data=None):
        if not data:
            return

        _dict = dict(data)
        dot_keys = [d for d in _dict if '.' in d]

        if dot_keys:
            # skip key if a subkey redefines it
            # i.e., 'author.name' has precedence over 'author'
            keys = ['.'.join(self._parse_key(dk)[:-1]) for dk in dot_keys]
            items = ((k, v) for k, v in _dict.items() if k not in keys)
        else:
            items = _dict.items()

        [self.set(key, value) for key, value in items]
