# -*- coding: utf-8 -*-
# vim: sw=4:ts=4:expandtab
"""
    pipe2py.modules.pipecsv
    ~~~~~~~~~~~~~~~~~~~~~~~

    http://pipes.yahoo.com/pipes/docs?doc=sources#FetchCSV
"""

from urllib2 import urlopen
from pipe2py.lib import utils
from pipe2py.lib import unicodecsv as csv
from pipe2py.lib.dotdict import DotDict


def _gen_fieldnames(conf, reader, item, **kwargs):
    start = int(utils.get_value(conf['col_row_start'], item, **kwargs))
    end = int(utils.get_value(conf['col_row_end'], item, **kwargs))

    for i in xrange((end - start) + 1):
        yield reader.next()


def pipe_csv(context=None, _INPUT=None, conf=None, **kwargs):
    """A source that fetches and parses a csv file to yield items. Loopable.

    Parameters
    ----------
    context : pipe2py.Context object
    _INPUT : pipeforever pipe or an iterable of items or fields
    conf : URL -- url
        skip -- number of header rows to skip
        col_mode -- column name source: row=header row(s),
                    custom=defined in col_name
        col_name -- list of custom column names
        col_row_start -- first column header row
        col_row_end -- last column header row
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

        if context and context.verbose:
            print "pipe_csv loading:", url

        for i in xrange(skip):
            f.next()

        reader = csv.UnicodeReader(f, delimiter=separator)
        fieldnames = []

        if col_mode == 'custom':
            fieldnames = [DotDict(x).get() for x in col_name]
        else:
            fieldnames = _gen_fieldnames(conf, reader, item, **kwargs)

        for rows in reader:
            yield dict(zip(fieldnames, rows))

        f.close()

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
