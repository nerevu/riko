# pipecsv.py
#
import csv, codecs

from urllib2 import urlopen
from pipe2py import util


class UTF8Recoder:
    """
    Iterator that reads an encoded stream and reencodes the input to UTF-8
    """
    def __init__(self, f, encoding):
        self.reader = codecs.getreader(encoding)(f)

    def __iter__(self):
        return self

    def next(self):
        return self.reader.next().encode("utf-8")

class UnicodeReader:
    """
    A CSV reader which will iterate over lines in the CSV file "f",
    which is encoded in the given encoding.
    """

    def __init__(self, f, dialect=csv.excel, encoding="utf-8", **kwds):
        f = UTF8Recoder(f, encoding)
        self.reader = csv.reader(f, dialect=dialect, **kwds)

    def next(self):
        row = self.reader.next()
        return [unicode(s, "utf-8") for s in row]

    def __iter__(self):
        return self


def pipe_csv(context=None, _INPUT=None, conf=None, **kwargs):
    """This source fetches and parses a csv file to yield items.

    Keyword arguments:
    context -- pipeline context
    _INPUT -- not used
    conf:
        URL -- url
        skip -- number of header rows to skip
        col_mode -- column name source: row=header row(s), custom=defined in col_name
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
    col_name = conf['col_name']

    for item in _INPUT:
        url = util.get_value(conf['URL'], item, **kwargs)
        sep = util.get_value(conf['separator'], item, **kwargs).encode('utf-8')
        skip = int(util.get_value(conf['skip'], item, **kwargs))
        col_mode = util.get_value(conf['col_mode'], item, **kwargs)
        row_start = int(util.get_value(conf['col_row_start'], item, **kwargs))
        row_end = int(util.get_value(conf['col_row_end'], item, **kwargs))

        f = urlopen(url)

        if context and context.verbose:
            print "pipe_csv loading:", url

        for i in xrange(skip):
            f.next()

        reader = UnicodeReader(f, delimiter=sep)
        fieldnames = []

        if col_mode == 'custom':
            fieldnames = [util.get_value(x) for x in col_name]
        else:
            for row in xrange((row_end - row_start) +1):
                row = reader.next()
                fieldnames.extend(row)

        for rows in reader:
            d = dict(zip(fieldnames, rows))
            yield d

        if item.get('forever'):
            # _INPUT is pipeforever and not a loop,
            # so we just yield our item once
            break
