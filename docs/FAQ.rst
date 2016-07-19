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

+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| Pipe name         | Pipe type | Pipe sub-type | Pipe description                                                                             |
+===================+===========+===============+==============================================================================================+
| count             | operator  | aggregator    | counts the number of items in a feed                                                         |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| csv               | processor | source        | parses a csv file to yield items                                                             |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| currencyformat    | processor | transformer   | formats a number to a given currency string                                                  |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| dateformat        | processor | transformer   | formats a date                                                                               |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| exchangerate      | processor | transformer   | retrieves the current exchange rate for a given currency pair                                |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| feedautodiscovery | processor | source        | fetches and parses the first feed found on a site                                            |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| fetch             | processor | source        | fetches and parses a feed to return the entries                                              |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| fetchdata         | processor | source        | fetches and parses an XML or JSON file to return the feed entries                            |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| fetchpage         | processor | source        | fetches the content of a given web site as a string                                          |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| fetchsitefeed     | processor | source        | fetches and parses the first feed found on a site                                            |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| filter            | operator  | composer      | extracts items matching the given rules                                                      |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| hash              | processor | transformer   | hashes the field of a feed item                                                              |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| input             | processor | source        | prompts for text and parses it into a variety of different types, e.g., int, bool, date, etc |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| itembuilder       | processor | source        | builds an item                                                                               |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| regex             | processor | transformer   | replaces text in fields of a feed item using regexes                                         |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| rename            | processor | transformer   | renames or copies fields in a feed item                                                      |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| reverse           | operator  | composer      | reverses the order of source items in a feed                                                 |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| rssitembuilder    | processor | source        | builds an rss item                                                                           |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| simplemath        | processor | transformer   | performs basic arithmetic, such as addition and subtraction                                  |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| sort              | operator  | composer      | sorts a feed according to a specified key                                                    |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| split             | operator  | composer      | splits a feed into identical copies                                                          |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| strconcat         | processor | transformer   | concatenates strings                                                                         |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| stringtokenizer   | processor | transformer   | splits a string by a delimiter                                                               |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| strreplace        | processor | transformer   | replaces the text of a field of a feed item                                                  |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| strtransform      | processor | transformer   | performs string transformations on the field of a feed item                                  |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| subelement        | processor | transformer   | extracts sub-elements for the item of a feed                                                 |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| substr            | processor | transformer   | returns a substring of a field of a feed item                                                |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| tail              | operator  | composer      | truncates a feed to the last N items                                                         |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| truncate          | operator  | composer      | returns a specified number of items from a feed                                              |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| union             | operator  | composer      | merges multiple feeds together                                                               |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| uniq              | operator  | composer      | filters out non unique items according to a specified field                                  |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| urlbuilder        | processor | transformer   | builds a url                                                                                 |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| xpathfetchpage    | processor | source        | fetches the content of a given website as DOM nodes or a string                              |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+
| yql               | processor | source        | fetches the result of a given YQL query                                                      |
+-------------------+-----------+---------------+----------------------------------------------------------------------------------------------+

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
