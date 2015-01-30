# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecsv
    ~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchCSV
"""

from __future__ import (
    absolute_import, division, print_function, with_statement,
    unicode_literals)

import unicodecsv as csv

from urllib2 import urlopen
from pipe2py.lib import utils
from pipe2py.lib.dotdict import DotDict


class DictReader(csv.DictReader):
    def __init__(self, *args, **kwargs):
        strings = {k: str(v) for k, v in kwargs.items()}
        csv.DictReader.__init__(self, *args, **strings)


def pipe_csv(context=None, item=None, conf=None, **kwargs):
    """A source that fetches and parses a csv file to yield items. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : URL -- url
        skip -- number of initial rows to skip
        col_mode -- column name source: row=header row,
                    custom=defined in col_name
        col_name -- list of custom column names
        separator -- column separator

    Yields
    ------
    _OUTPUT : items

    Note:
    Current restrictions:
      separator must be 1 character
      assumes every row has exactly the expected number of fields, as defined
      in the header
    """
    conf = DotDict(conf)
    conf_sep = conf['separator']
    conf_mode = conf['col_mode']
    col_name = conf['col_name']

    for item in _INPUT:
        item = DotDict(item)
        url = utils.get_value(conf['URL'], item, **kwargs)
        url = utils.get_abspath(url)
        separator = utils.get_value(conf_sep, item, encode=True, **kwargs)
        skip = int(utils.get_value(conf['skip'], item, **kwargs))
        col_mode = utils.get_value(conf_mode, item, **kwargs)

        f = urlopen(url)

        if col_mode == 'custom':
            fieldnames = [DotDict(x).get() for x in col_name]
        else:
            fieldnames = None

        if context and context.verbose:
            print("pipe_csv loading:", url)

        for i in xrange(skip):
            f.next()

        reader = DictReader(
            f, fieldnames, encoding='utf-8', delimiter=separator)

        for row in reader:
            yield row

        f.close()

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
