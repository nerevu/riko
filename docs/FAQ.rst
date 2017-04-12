riko FAQ
========

Index
-----

`What pipes are available`_ | `What file types are supported`_ | `What protocols are supported`_


What pipes are available?
-------------------------

Overview
^^^^^^^^

riko's available pipes are outlined below [#]_:

+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| Pipe name            | Pipe type | Pipe sub-type | Pipe description                                                                             |
+======================+===========+===============+==============================================================================================+
| `count`_             | operator  | aggregator    | counts the number of items in a feed                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `csv`_               | processor | source        | parses a csv file to yield items                                                             |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `currencyformat`_    | processor | transformer   | formats a number to a given currency string                                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `dateformat`_        | processor | transformer   | formats a date                                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `exchangerate`_      | processor | transformer   | retrieves the current exchange rate for a given currency pair                                |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `feedautodiscovery`_ | processor | source        | fetches and parses the first feed found on a site                                            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetch`_             | processor | source        | fetches and parses a feed to return the entries                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchdata`_         | processor | source        | fetches and parses an XML or JSON file to return the feed entries                            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchpage`_         | processor | source        | fetches the content of a given web site as a string                                          |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchsitefeed`_     | processor | source        | fetches and parses the first feed found on a site                                            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `fetchtext`_         | processor | source        | fetches and parses a text file                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `filter`_            | operator  | composer      | extracts items matching the given rules                                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `hash`_              | processor | transformer   | hashes the field of a feed item                                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `input`_             | processor | source        | prompts for text and parses it into a variety of different types, e.g., int, bool, date, etc |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `itembuilder`_       | processor | source        | builds an item                                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `join`_              | operator  | aggregator    | perform a SQL like join on two feeds                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `regex`_             | processor | transformer   | replaces text in fields of a feed item using regexes                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `refind`_            | processor | transformer   | finds text located before, after, or between substrings using regular expressions            |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `rename`_            | processor | transformer   | renames or copies fields in a feed item                                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `reverse`_           | operator  | composer      | reverses the order of source items in a feed                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `rssitembuilder`_    | processor | source        | builds an rss item                                                                           |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `simplemath`_        | processor | transformer   | performs basic arithmetic, such as addition and subtraction                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `slugify`_           | operator  | transformer   | slugifies text                                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `sort`_              | operator  | composer      | sorts a feed according to a specified key                                                    |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `split`_             | operator  | composer      | splits a feed into identical copies                                                          |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strconcat`_         | processor | transformer   | concatenates strings                                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strfind`_           | processor | transformer   | finds text located before, after, or between substrings                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strreplace`_        | processor | transformer   | replaces the text of a field of a feed item                                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `strtransform`_      | processor | transformer   | performs string transformations on the field of a feed item                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `subelement`_        | processor | transformer   | extracts sub-elements for the item of a feed                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `substr`_            | processor | transformer   | returns a substring of a field of a feed item                                                |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `sum`_               | operator  | aggregator    | sums a field of items in a feed                                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `tail`_              | operator  | composer      | truncates a feed to the last N items                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `timeout`_           | operator  | composer      | returns items from a stream until a certain amount of time has passed                        |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `tokenizer`_         | processor | transformer   | splits a string by a delimiter                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `truncate`_          | operator  | composer      | returns a specified number of items from a feed                                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `union`_             | operator  | composer      | merges multiple feeds together                                                               |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `uniq`_              | operator  | composer      | filters out non unique items according to a specified field                                  |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `urlbuilder`_        | processor | transformer   | builds a url                                                                                 |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `urlparse`_          | processor | transformer   | parses a URL into its six components                                                         |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `xpathfetchpage`_    | processor | source        | fetches the content of a given website as DOM nodes or a string                              |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| `yql`_               | processor | source        | fetches the result of a given YQL query                                                      |
+----------------------+-----------+---------------+----------------------------------------------------------------------------------------------+

Args
^^^^

riko ``pipes`` come in two flavors; ``operator`` and ``processor`` [#]_.
``operator``s operate on an entire ``stream`` at once. Example ``operator``s include ``pipecount``, ``pipefilter``,
and ``pipereverse``.

.. code-block:: python

    >>> from riko.modules.reverse import pipe
    >>>
    >>> stream = [{'title': 'riko pt. 1'}, {'title': 'riko pt. 2'}]
    >>> next(pipe(stream))
    {'title': 'riko pt. 2'}

``processor``s process individual ``items``. Example ``processor``s include
``pipefetchsitefeed``, ``pipehash``, ``pipeitembuilder``, and ``piperegex``.

.. code-block:: python

    >>> from riko.modules.hash import pipe
    >>>
    >>> item = {'title': 'riko pt. 1'}
    >>> stream = pipe(item, field='title')
    >>> next(stream)
    {'title': 'riko pt. 1', 'hash': 2853617420L}

Kwargs
^^^^^^

The following table outlines the available kwargs.

==========  ====  ================================================  =======
kwarg       type  description                                       default
==========  ====  ================================================  =======
conf        dict  The pipe configuration                            varies
extract     str   The key with which to get a value from `conf`     None
listize     bool  Ensure that an `extract` value is list-like       False
pdictize    bool  Convert `conf` / `extract` to a DotDict instance  varies
objectify   bool  Convert `conf` to an Objectify instance           varies
ptype       str   Used to convert `conf` items to a specific type.  pass
dictize     bool  Convert the input `item` to a DotDict instance    True
field       str   The key with which to get a value from the input  None
ftype       str   Converts the input `item` to a specific type      pass
count       str   The output count                                  all
assign      str   Attribute used to assign output                   varies
emit        bool  Return the output as is (don't assign)            varies
skip_if     func  Determines if processing should be skipped        None
inputs      dict  Values to be used in place of prompting the user  None
==========  ====  ================================================  =======

Notes
^^^^^

.. [#] See `Design Principles`_ for explanation on `pipe` types and sub-types
.. [#] See `Alternate workflow creation`_ for pipe composition examples

What file types are supported?
------------------------------

File types that riko supports are outlined below:

====================  =======================  ===========================================
File type             Recognized extension(s)  Supported pipes
====================  =======================  ===========================================
HTML                  html                     feedautodiscovery, fetchpage, fetchsitefeed
XML                   xml                      fetch, fetchdata
JSON                  json                     fetchdata
Comma separated file  csv, tsv                 csv
====================  =======================  ===========================================

What protocols are supported?
-----------------------------

Protocols that riko supports are outlined below:

========  =========================================
Protocol  example
========  =========================================
http      http://google.com
https     https://github.com/reubano/feed
file      file:///Users/reubano/Downloads/feed.xml
========  =========================================

.. _What pipes are available: #what-pipes-are-available
.. _What file types are supported: #what-file-types-are-supported
.. _What protocols are supported: #what-protocols-are-supported
.. _Design Principles: https://github.com/nerevu/riko/blob/master/README.rst#design-principles
.. _Alternate workflow creation: https://github.com/nerevu/riko/blob/master/docs/COOKBOOK.rst#synchronous-processing

.. _split: https://github.com/nerevu/riko/blob/master/riko/modules/split.py
.. _count: https://github.com/nerevu/riko/blob/master/riko/modules/count.py
.. _csv: https://github.com/nerevu/riko/blob/master/riko/modules/csv.py
.. _currencyformat: https://github.com/nerevu/riko/blob/master/riko/modules/currencyformat.py
.. _dateformat: https://github.com/nerevu/riko/blob/master/riko/modules/dateformat.py
.. _exchangerate: https://github.com/nerevu/riko/blob/master/riko/modules/exchangerate.py
.. _feedautodiscovery: https://github.com/nerevu/riko/blob/master/riko/modules/feedautodiscovery.py
.. _fetch: https://github.com/nerevu/riko/blob/master/riko/modules/fetch.py
.. _fetchdata: https://github.com/nerevu/riko/blob/master/riko/modules/fetchdata.py
.. _fetchpage: https://github.com/nerevu/riko/blob/master/riko/modules/fetchpage.py
.. _fetchsitefeed: https://github.com/nerevu/riko/blob/master/riko/modules/fetchsitefeed.py
.. _fetchtext: https://github.com/nerevu/riko/blob/master/riko/modules/fetchtext.py
.. _filter: https://github.com/nerevu/riko/blob/master/riko/modules/filter.py
.. _hash: https://github.com/nerevu/riko/blob/master/riko/modules/hash.py
.. _input: https://github.com/nerevu/riko/blob/master/riko/modules/input.py
.. _itembuilder: https://github.com/nerevu/riko/blob/master/riko/modules/itembuilder.py
.. _join: https://github.com/nerevu/riko/blob/master/riko/modules/join.py
.. _regex: https://github.com/nerevu/riko/blob/master/riko/modules/regex.py
.. _refind: https://github.com/nerevu/riko/blob/master/riko/modules/refind.py
.. _rename: https://github.com/nerevu/riko/blob/master/riko/modules/rename.py
.. _rssitembuilder: https://github.com/nerevu/riko/blob/master/riko/modules/rssitembuilder.py
.. _simplemath: https://github.com/nerevu/riko/blob/master/riko/modules/simplemath.py
.. _slugify: https://github.com/nerevu/riko/blob/master/riko/modules/slugify.py
.. _sort: https://github.com/nerevu/riko/blob/master/riko/modules/sort.py
.. _split: https://github.com/nerevu/riko/blob/master/riko/modules/split.py
.. _strconcat: https://github.com/nerevu/riko/blob/master/riko/modules/strconcat.py
.. _strfind: https://github.com/nerevu/riko/blob/master/riko/modules/strfind.py
.. _strreplace: https://github.com/nerevu/riko/blob/master/riko/modules/strreplace.py
.. _strtransform: https://github.com/nerevu/riko/blob/master/riko/modules/strtransform.py
.. _subelement: https://github.com/nerevu/riko/blob/master/riko/modules/subelement.py
.. _substr: https://github.com/nerevu/riko/blob/master/riko/modules/substr.py
.. _sum: https://github.com/nerevu/riko/blob/master/riko/modules/sum.py
.. _tail: https://github.com/nerevu/riko/blob/master/riko/modules/tail.py
.. _timeout: https://github.com/nerevu/riko/blob/master/riko/modules/timeout.py
.. _tokenizer: https://github.com/nerevu/riko/blob/master/riko/modules/tokenizer.py
.. _truncate: https://github.com/nerevu/riko/blob/master/riko/modules/truncate.py
.. _union: https://github.com/nerevu/riko/blob/master/riko/modules/union.py
.. _uniq: https://github.com/nerevu/riko/blob/master/riko/modules/uniq.py
.. _urlbuilder: https://github.com/nerevu/riko/blob/master/riko/modules/urlbuilder.py
.. _urlparse: https://github.com/nerevu/riko/blob/master/riko/modules/urlparse.py
.. _xpathfetchpage: https://github.com/nerevu/riko/blob/master/riko/modules/xpathfetchpage.py
.. _yql: https://github.com/nerevu/riko/blob/master/riko/modules/yql.py
