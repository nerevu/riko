.. source: ../../../../chakula/README.rst

chakula
=======

|versions| |pypi|

*chakula* is a Python library and command-line rss feed monitor with behavior
similar to ``tail -f``. *chakula* is based off of rsstail.py_, but can be used as
a library to call a custom function after each feed is polled (see
`Library usage`_).

Usage
-----

::

    $ chakula --help
    positional arguments:
      urls                  The urls to tail (default: reads from stdin).

    optional arguments:
      -h, --help            show this help message and exit
      -i INTERVAL, --interval INTERVAL
                            Number of seconds between polling (default: 5m).
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

URLs come from the command line, or one per line from stdin when none are given.
Running ``chakula`` with no URLs and nothing piped in prints the help and exits
with status 0.

How polling works
-----------------

Each poll fetches every URL in turn, prints the entries that pass the filters
below, and then sleeps for ``--interval`` before the next poll. The first poll
starts immediately.

``-i/--interval``
    Seconds between polls. Accepts a plain number of seconds or a number with an
    ``s``, ``m``, or ``h`` suffix (``60``, ``60s``, ``1m``, ``1h``). The default
    is ``5m`` (300 seconds). Values under 60 seconds crash on the second poll
    (see `Known issues`_), so ``60s`` is the shortest working interval.

``-N/--iterations``
    Number of polls before exiting with status 0. Without it *chakula* keeps
    polling, but each poll adds a stack frame, so a run ends with a
    ``RecursionError`` after roughly 990 polls (about 3.4 days at the default
    interval). Use ``-N`` (or a scheduler such as ``cron`` with ``--cache``) for
    long-running use.

``-I/--initial``
    Applies to the first poll only: it keeps the first N entries of each feed
    in feed order, before the ``--newer`` filter and before ``--reverse``.
    Later polls show every new entry.

``-n/--newer``
    Any date ``dateutil`` can parse. Its date and time fields are compared
    as-is with the entry's UTC publish date, so a time zone in the value is
    ignored. Each feed's cutoff is the later of ``--newer`` and the feed's last
    update date from the previous poll or the cache. An entry is shown only
    when its publish date is after the cutoff. An entry dated exactly at a
    ``--newer`` cutoff is still shown; one dated exactly at the stored last
    update is not. Feeds whose entries have no publish date fail whenever a
    cutoff applies (see `Known issues`_).

``-r/--reverse``
    Reverses each feed's entries for that poll (after ``--initial`` and
    ``--newer``).

``-u/--unique``
    Skips entries whose id was already printed, across all feeds and polls.
    The seen ids live in memory only, for the life of the process; they are
    not saved to the cache.

``-c/--cache``
    A pickle file holding, per URL, the feed's ``etag``, ``modified`` date,
    and last ``updated`` date. It is read at start (a missing file means an
    empty cache) and rewritten after every poll. Later runs send ``etag`` and
    ``modified`` with the request (a conditional GET) and use ``updated`` as
    the feed's cutoff, so a rerun shows only entries published after the
    stored ``updated`` date. ``updated`` is the feed's own update date, or, when
    the feed has none, the newest entry update date seen.

``-f/--fail``
    Any feed error, or any error while filtering or printing a feed's entries,
    stops *chakula* with a traceback and exit status 1. Without ``-f`` the
    error's traceback is logged, the rest of that feed's entries for the poll
    are skipped, and polling continues with the next URL. Exit status stays 0.
    A fetch or filter error leaves the feed's cache state unchanged, so the
    next poll retries the same entries. A printing error happens after the
    state is updated, so the entries that failed to print are not retried. A feed counts as an error when ``feedparser`` flags it
    as malformed, except for a character encoding override.

With several URLs, each feed should have its own cutoff, but today a feed with
no stored state (every feed on the first poll, or one whose last fetch failed)
inherits the previous feed's ``etag``, ``modified``, and ``updated``. For
example, tailing a feed of 2020 entries followed by a feed of 2015 entries
prints only the 2020 entries; the 2015 feed on its own prints both of its
entries. Tail feeds in separate processes when that matters (see
`Known issues`_).

Fields
------

======================  ==================================================
Field                   Value
======================  ==================================================
``author``              entry author
``id``                  entry id (the key ``--unique`` dedupes on)
``title``               entry title
``link``, ``url``       entry link
``description``         entry description (``--show`` puts it on its own
                        line); ``desc`` is an alias
``pubdate``             entry publish date, formatted with ``--time-format``
``updated``             entry update date, formatted with ``--time-format``
``created``             entry creation date as a raw ``struct_time`` (not
                        formatted); empty when the entry has none
``timestamp``           the current UTC time when the entry is printed, not
                        an entry date
``expired``             always ``None`` (intended; not implemented)
``comments``            always ``None`` (intended; not implemented)
======================  ==================================================

A missing text field prints as an empty string. Every field is computed for
every entry, whichever ones are shown, so an entry without a publish date or
an update date fails to print (see `Known issues`_).

``--show`` may be repeated; the shown fields are joined by two spaces and each
entry ends with a newline. ``--heading`` prefixes each field with its title-cased
name (``Pubdate: 2020/01/01 00:00:00  Title: a one``), except ``timestamp``.
``--format`` takes either ``%(field)s`` or ``{field}`` placeholders (whichever
style appears more often wins); a literal ``\n`` in it becomes a newline.

Library usage
-------------

``chakula.tail(urls, iteration=0, interval=300, extra=None, **kwargs)`` runs the
same polling loop as the command line. Its log messages (including the debug
line ``Writing N new entries``) go to standard output. ``interval`` is in seconds (60 or more,
see `Known issues`_). ``extra`` is the per-URL state that ``--cache`` stores; it
is updated in place and returned when ``iterations`` is reached.

=================  ======================================================
Keyword            Meaning
=================  ======================================================
``iterations``     number of polls (default: unbounded, see ``-N`` above)
``initial``        entries to keep on the first poll (``-I``)
``newer``          a ``time.struct_time`` cutoff (``-n``)
``reverse``        reverse each feed's entries (``-r``)
``seen``           a ``set`` of already printed entry ids; pass ``set()``
                   to dedupe (``-u``)
``fail``           re-raise feed errors (``-f``)
``stream``         where entries are written (default: ``sys.stdout``)
``formatter``      a callable taking an entry and returning the text to
                   write (default: the title plus a newline); see
                   ``chakula.formatter.Formatter``
``logger``         the logger to use
``write_handler``  called as ``write_handler(entries)`` with the entries
                   just written for one feed
``tail_handler``   called as ``tail_handler(extra)`` once at the end of
                   every poll; ``--cache`` uses it to save ``extra``
=================  ======================================================

``write_handler`` runs after every feed on every poll, with an empty list when
the feed had nothing new, so check the list before acting on it.

.. code-block:: pycon

    >>> import io
    >>> import chakula
    >>>
    >>> out = io.StringIO()
    >>> calls = []
    >>> extra = chakula.tail(
    ...     ['a.rss'], iterations=1, stream=out,
    ...     write_handler=lambda entries: calls.append([e.title for e in entries]),
    ... )
    Writing 2 new entries
    maximum number of iterations reached: 1
    >>> out.getvalue()
    'a one\na two\n'
    >>> calls
    [['a one', 'a two']]
    >>> list(extra)
    ['a.rss']

Here ``a.rss`` is a local RSS 2.0 file with two dated items; any URL or path
``feedparser`` accepts works.

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

Known issues
------------

- An ``--interval`` under 60 seconds raises ``ZeroDivisionError`` when the
  second poll logs its sleep time (``chakula/__init__.py:111-121``).
- An unbounded run (no ``-N``) ends in ``RecursionError`` after roughly 990
  polls because each poll recurses (``chakula/__init__.py:156``).
- Feeds share state on polls where a feed has none of its own: the previous
  feed's ``etag``/``modified``/``updated`` carry over to it, hiding its entries
  or sending another feed's ``etag`` (``chakula/__init__.py:140-144``).
- An entry with no publish date raises ``AttributeError`` whenever a cutoff
  applies (``chakula/__init__.py:94``), and an entry with no publish or update
  date raises ``TypeError`` when printed, whichever fields are shown
  (``chakula/formatter.py:70``, ``:77``). Either way the whole feed is skipped
  for that poll (or *chakula* exits with ``-f``).
- An interval with a known suffix but a non-numeric value (``am``) is accepted
  instead of rejected, because the error is built but not raised
  (``chakula/main.py:89``); the run then fails with ``TypeError`` on the second
  poll.
- ``expired`` and ``comments`` always print ``None`` and ``created`` is not
  formatted (``chakula/formatter.py:29-31``, ``:76-79``).

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
