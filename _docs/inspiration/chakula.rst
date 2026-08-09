chakula
=======

|versions| |pypi|

*chakula* is a Python library and command-line rss feed monitor with behavior
similar to ``tail -f``. *chakula* is based off of rsstail.py_, but can be used as
a library to call a custom function each time new entries appear in the feed.

Usage
-----

::

    $ chakula --help
    positional arguments:
      urls                  The urls to tail (default: reads from stdin).

    optional arguments:
      -h, --help            show this help message and exit
      -i INTERVAL, --interval INTERVAL
                            Number of seconds between polling (default: 300s).
      -N ITERATIONS, --iterations ITERATIONS
                            Number of times to poll before quiting (default: inf).
      -I INITIAL, --initial INITIAL
                            Number of entries to show (default: all)
      -n DATE, --newer DATE
                            Date by which entries should be newer than
      -s FIELD, --show FIELD
                            Entry field to display (default: title).
      -t FORMAT, --time-format FORMAT
                            The date/time format (default: 'YYYY/MM/DD HH:MM:SS').
      -F FORMAT, --format FORMAT
                            The output format (overrides other format options).
      -c CACHE, --cache CACHE
                            File path to store feed information across multiple runs.
      -r, --reverse         Show entries in reverse order.
      -f, --fail            Exit on error.
      -u, --unique          Skip duplicate entries.
      -H, --heading         Show field headings.
      -v, --version         Show version and exit.
      -V, --verbose         Increase output verbosity.

    Format specifiers must have one the following forms:
      %(placeholder)[flags]s
      {placeholder:flags}

    Examples:
      chakula <url>
      echo '<url>' | chakula --reverse
      chakula -s pubdate -s title -s author <url1> <url2> <url3>
      chakula --interval 60s --newer "2011/12/20 23:50:12" <url>
      chakula --format '%(timestamp)-30s %(title)s\n' <url>
      chakula --format '%(title)s was written on %(pubdate)s\n' <url>
      chakula --format '{timestamp:<30} {title} {author}\n' <url>
      chakula --format '{timestamp:<20} {pubdate:^30} {author:>30}\n' <url>
      chakula --time-format '%Y/%m/%d %H:%M:%S' <url>
      chakula --time-format 'Day of the year: %j Month: %b' <url>

    Useful flags in this context are:
      %(placeholder)-10s - left align and pad
      %(placeholder)10s  - right align and pad
      {placeholder:<10}  - left align and pad
      {placeholder:>10}  - right align and pad
      {placeholder:^10}  - center align and pad

    Available fields: author, comments, created, desc, description,
    expired, id, link, pubdate, timestamp, title, updated, url

Installing
----------

The latest stable version of chakula can be installed from pypi_:

.. code-block:: bash

    $ pip install chakula

Similar projects
----------------

    - rsstail.py_
    - rsstail_
    - feedstail_
    - theyoke_
    - wag_

License
-------

*chakula* is released under the terms of the `Revised BSD License`_.

.. |travis| image:: https://img.shields.io/travis/reubano/chakula/master.svg
    :target: https://travis-ci.org/reubano/chakula

.. |versions| image:: https://img.shields.io/pypi/pyversions/chakula.svg
    :target: https://pypi.python.org/pypi/chakula

.. |pypi| image:: https://img.shields.io/pypi/v/chakula.svg
    :target: https://pypi.python.org/pypi/chakula

.. _rsstail.py:    http://github.com/gvalkov/rsstail.py/
.. _rsstail:    http://www.vanheusden.com/rsstail/
.. _feedstail:  http://pypi.python.org/pypi/feedstail/
.. _theyoke:    http://github.com/mackers/theyoke/
.. _wag:        http://github.com/knobe/wag/
.. _feedparser: http://code.google.com/p/feedparser/
.. _`Revised BSD License`: https://raw.github.com/reubano/chakula.py/master/LICENSE
.. _pypi:        https://pypi.python.org/pypi/chakula

