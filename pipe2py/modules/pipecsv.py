# pipecsv.py
#
from urllib2 import urlopen
from pipe2py import util
from pipe2py.lib import unicodecsv as csv
from pipe2py.lib.dotdict import DotDict


def _gen_fieldnames(conf, reader, item, **kwargs):
    start = util.get_value(conf['col_row_start'], item, func=int, **kwargs)
    end = util.get_value(conf['col_row_end'], item, func=int, **kwargs)

    for i in xrange((end - start) + 1):
        yield reader.next()


def pipe_csv(context=None, _INPUT=None, conf=None, **kwargs):
    """This source fetches and parses a csv file to yield items.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        URL -- url
        skip -- number of header rows to skip
        col_mode -- column name source: row=header row(s),
                    custom=defined in col_name
        col_name -- list of custom column names
        col_row_start -- first column header row
        col_row_end -- last column header row
        separator -- column separator

    Yields (_OUTPUT):
    file entries

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
        url = util.get_value(conf['URL'], item, **kwargs)
        url = util.get_abspath(url)
        separator = util.get_value(conf_sep, item, encode=True, **kwargs)
        skip = util.get_value(conf['skip'], item, func=int, **kwargs)
        col_mode = util.get_value(conf_mode, item, **kwargs)

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
