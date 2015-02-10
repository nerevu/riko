# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.lib.dotdict
    ~~~~~~~~~~~~~~

    Provides methods for creating dicts using dot notation
"""

from . import utils
from itertools import starmap
from feedparser import FeedParserDict


class DotDict(FeedParserDict):
    """A dictionary whose keys can be accessed using dot notation
    r = {'a': {'content': 'value'}}
    e.g. r['a.content'] -> ['a']['content']

    """
    def __init__(self, dict=None, **kwargs):
        super(DotDict, self).__init__(self, **kwargs)
        self.update(dict)

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
            # remove any trailing '.'
            keys = key.rstrip('.').split('.') if key else []
        except AttributeError:
            keys = [key['subkey']] if key else []

        return keys

    def _parse_value(self, value, key, default=None):
        try:
            value = value[key]
        except (KeyError, TypeError):
            contains = ['value', 'content', 'utime']
            value = value if key in set(contains) else None

        return value or default

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
        encode = kwargs.pop('encode', None)
        func = kwargs.pop('func', None)

        for key in keys:
            if not value:
                break

            try:
                key = int(key)
            except ValueError:
                pass

            value = self._parse_value(value, key, default)

        if hasattr(value, 'keys') and 'terminal' in value:
            # value fed in from another module
            value = kwargs[utils.pythonise(value['terminal'])].next()
        elif hasattr(value, 'keys') and 'value' in value:
            value = value['value']

        value = value.encode('utf-8') if value and encode else value
        value = func(value) if value and func else value
        value = DotDict(value) if hasattr(value, 'keys') else value
        return value

    def update(self, dict=None):
        if not dict:
            return

        try:
            keys = ['.'.join(self._parse_key(k)[:-1]) for k in dict if '.' in k]
        except AttributeError:
            items = dict
        else:
            # skip key if a subkey redefines it
            # i.e., 'author.name' has precedence over 'author'
            items = ((k, v) for k, v in dict.iteritems() if k not in keys)

        list(starmap(self.set, items))
