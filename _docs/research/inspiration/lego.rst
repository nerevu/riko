.. source: ../../../../lego/README.rst

lego
====

Introduction
------------

``lego`` is a command-line tool that compares eBay and Amazon Lego set prices to surface
arbitrage opportunities — Lego sets selling on eBay for meaningfully less than on Amazon.

It searches eBay for Lego sets in a given category, matches each item to its Amazon
listing by model number, compares the prices, and writes the matches to a CSV. It can
also fetch eBay shipping costs and factor them into the comparison.

Writing only the matches whose price difference exceeds a threshold is intended. Today
every eBay/Amazon match is written, and a ``meets_threshold`` column marks the rows whose
difference reaches ``--min-price-diff`` (see `Price comparison`_).

``lego`` is powered by two companion services:

* `eBay Search API <https://github.com/reubano/ebay-search-api>`_
* `amzn-search-api <https://github.com/reubano/amzn-search-api>`_

``lego`` calls them at hardcoded addresses (``EBAY_API_BASE_URL`` and
``AMZN_API_BASE_URL`` in ``Lego/main.py``):

* ``http://ebay-search-api.herokuapp.com/api/v1``
* ``http://amzn-search-api.herokuapp.com/api/v1``

There is no option or environment variable to point ``lego`` elsewhere; edit those two
constants to use another deployment (``main.py`` has commented-out ``localhost:5000``
alternatives). Both hosted services return ``503 Application Error`` today, so a run
cannot reach eBay or Amazon (see `Known issues`_).

How it works
------------

1. Search eBay (default category ``Toys & Games`` › ``Lego``, country ``UK``) for Lego
   sets, excluding accessories (keychains, minifigures, bags, etc.; see `Search filters`_).
2. Parse each eBay item's Lego set/model number and look it up on Amazon (see
   `Model-number matching`_).
3. Compare prices and keep the matches whose difference meets ``--min-price-diff``
   (intended; today every match is kept and flagged with ``meets_threshold``).
4. Optionally add eBay shipping costs.
5. Write results to CSV files (see `Output`_).

Intermediate eBay/Amazon results are cached locally (with expiry) to avoid repeat API
calls between runs (see `Caching`_).

.. note::

   ``lego`` is a legacy Python 2 project.

Search filters
^^^^^^^^^^^^^^

The category is resolved by asking the eBay service for the sub-categories of
``--category`` and taking the first whose name starts with ``--sub-category``
(case-insensitive). If none matches, ``lego`` prints ``Sub-category <name> doesn't
exist`` with a link to the valid sub-categories. No eBay search runs, so the run ends
with ``Error getting Amazon results.`` (or ``No results found meeting your criteria``
when the Amazon cache still holds entries).

Without ``--keywords``, the eBay keywords are::

    lego -(key,keychain,keyring,key+chain,key+ring,mini,minifig,minifigs,minifigure,minifigures,miniature,miniatures,packets,figure,bag,sun,promo)

The exclude list is hardcoded in ``Lego/main.py``. ``--keywords`` replaces the whole
string, exclusions included.

Every eBay search also applies these hardcoded filters (``Request.get_ebay_search_options``
in ``Lego/api.py``):

* ``Condition`` = ``New``, ``ListingType`` = ``All``
* ``Brand`` = ``LEGO``, ``Item Type`` in ``Box Sets`` or ``Not Specified``
* sorted by ``EndTimeSoonest``

Every Amazon search uses ``Condition`` = ``New`` and ``ResponseGroup`` = ``Medium``
(``CONDITION`` and ``RESPONSE_GROUP`` in ``Lego/main.py``) plus ``--search-index``.

Model-number matching
^^^^^^^^^^^^^^^^^^^^^

A model number is any all-digit token longer than two characters in the lowercased eBay
title. The title is split on whitespace and on ``,`` ``-`` ``;`` ``/`` ``(`` ``)``, and
each piece is stripped of leading and trailing ``:`` ``,`` ``(`` ``)`` ``.`` ``#``
characters and the letters of ``new`` and ``no`` (``n``, ``e``, ``w``, ``o``) before
the digit test (``Request.get_model_nums`` in ``Lego/api.py``). A title can yield
several model numbers.

Each model number is searched on Amazon as ``lego <model>``, taking only the first
result (``AMZN_SEARCH_LIMIT = 1`` in ``Lego/utils.py``). So an eBay item produces one
results row per model number found on Amazon.

* An item with no model number goes to ``unparsed.csv``.
* An item with model numbers but no Amazon result goes to ``unfound.csv``.

The ``matching_model`` column is ``1`` when the eBay model number is the Amazon item's
model or appears among the model numbers parsed from the Amazon title, and ``0``
otherwise.

Price comparison
^^^^^^^^^^^^^^^^

For each eBay/Amazon pair (``Request.get_master_list`` in ``Lego/api.py``):

* The eBay price is ``ebay_price_and_shipping`` (price plus listed shipping). With
  ``--shipping``, the price plus the fetched shipping cost is used instead when a cost was
  found.
* ``price_diff`` is the **absolute** difference between the Amazon price and that eBay
  price, so it is also large when eBay is the more expensive side.
* ``meets_threshold`` is ``price_diff >= --min-price-diff``.

Filtering rows by ``meets_threshold`` is built (``Request.update_sorted_list``) but
switched off by the hardcoded ``FILTER_AMAZON_MATCHES = False`` in ``Lego/main.py``; set
it to ``True`` to keep, per eBay item, only the first match that meets the threshold.
The sort switches ``MATCHING_MODEL_SORT``, ``MATCHING_PRICE_DIFF_SORT`` and
``MATCHING_RANK_SORT`` beside it are also hardcoded to ``False``.

Caching
^^^^^^^

Responses are cached as YAML files in a ``cache/`` directory relative to the current
working directory (``Lego/utils.py``). A file expires when it is older than its lifetime,
measured from the file's modification time:

=================================  ========  ===============================================
file                               lifetime  contents
=================================  ========  ===============================================
``cache/matching.yml``             1 week    the resolved eBay sub-category and its id
``cache/ebay_search_results.yml``  2 hours   eBay search results, keyed by eBay id
``cache/ebay_ship_costs.yml``      2 hours   ``--shipping`` costs, keyed by eBay id
``cache/ebay_img_urls.yml``        2 hours   image URLs for ``unparsed.csv``/``unfound.csv``
``cache/amzn_search_results.yml``  6 hours   Amazon results, keyed by eBay id
=================================  ========  ===============================================

When a cache is reused:

* ``matching.yml`` is refetched when ``--country``, ``--category`` or ``--sub-category``
  differs from the cached one, and a refetch discards the cached eBay results.
* ``ebay_search_results.yml`` is reused only if it is for the same ``--country`` and holds
  at least ``--results-per-page`` × ``--max-pages`` items (10,000 at the defaults), so at
  the defaults eBay is searched again on almost every run. ``--keywords`` is not checked:
  a cached search is reused for new keywords (see `Known issues`_).
* Amazon, shipping and image entries are reused per eBay id. A cached "not found on
  Amazon" entry is reused too unless ``--research`` is given.
* New Amazon, shipping and image entries are appended to their file, and each append
  resets the file's age, so older entries in it stay cached as well.

Delete ``cache/`` to force fresh searches.

Requirements
------------

* Python 2.7
* Network access to the eBay and Amazon search APIs

Installation
------------

*Clone the repo and install*

.. code-block:: bash

    git clone https://github.com/reubano/lego
    cd lego
    pip install -r requirements.txt
    python setup.py install   # installs the `lego` script

Usage
-----

.. code-block:: bash

    lego [options]

Examples
^^^^^^^^

*Show help*

.. code-block:: bash

    lego -h

*Run with defaults* (UK, Toys & Games › Lego, min price difference of 10)

.. code-block:: bash

    lego

*Search a different country and require a larger price gap, with verbose output*

.. code-block:: bash

    lego --country US --min-price-diff 25 --verbose

``--min-price-diff`` only changes the ``meets_threshold`` column today; it does not drop
rows.

*Include eBay shipping costs to a US destination*

.. code-block:: bash

    lego --shipping --destination US --zipcode 94105

*Search custom keywords and fetch more pages*

.. code-block:: bash

    lego --keywords "lego star wars" --results-per-page 100 --max-pages 5

Options
^^^^^^^

============================  ==============================================================
option                        description
============================  ==============================================================
``-v, --verbose``             increase output verbosity
``-V, --version``             display version and exit
``-s, --sandbox``             use the eBay sandbox
``-p, --shipping``            calculate eBay shipping cost (one eBay call per item, cached)
``-d, --destination``         shipping destination country (default ``US``)
``-z, --zipcode``             destination postal code (required if country is ``US``; passed
                              to the eBay service as is, ``lego`` does not check it)
``-k, --keywords``            keywords to search (defaults to a curated Lego query; see
                              `Search filters`_)
``-f, --results-file``        results CSV filename (default ``results.csv``)
``-F, --unparsed-file``       CSV for eBay items with unparsable model numbers (``unparsed.csv``)
``-o, --unfound-file``        CSV for eBay items not found on Amazon (``unfound.csv``)
``-m, --min-price-diff``      minimum price-difference threshold, an integer (default
                              ``10``); sets the ``meets_threshold`` column
``-r, --results-per-page``    eBay results per page to fetch (default ``100``, at most
                              ``100``)
``-M, --max-pages``           max eBay pages to fetch (default ``100``, at most ``100``)
``-R, --research``            re-search null Amazon results
``-c, --country``             eBay country to search, also the Amazon region (default
                              ``UK``)
``-C, --category``            eBay main category (default ``Toys & Games``)
``-S, --sub-category``        eBay sub-category (default ``Lego``)
``-i, --search-index``        Amazon search index (default ``Toys``)
============================  ==============================================================

Output
------

``lego`` writes up to three CSV files:

================  =================================================================
file              contents
================  =================================================================
``results.csv``   matched eBay/Amazon items meeting the price-difference threshold
                  (intended; today every match, with a ``meets_threshold`` column)
``unparsed.csv``  eBay items whose Lego model number couldn't be parsed
``unfound.csv``   eBay items with no matching Amazon listing
================  =================================================================

Each file is written in the current directory (or at the given path), only when it has
rows, and replaces any existing file. Files are UTF-8 with a byte-order mark (for Excel
on Windows), and rows are sorted by eBay end time, soonest first.

results.csv
^^^^^^^^^^^

One row per eBay item and Amazon match, so one eBay item can produce several rows. The
"unique" count printed at the end is the number of distinct eBay ids. Columns, in order
(``Request.keys`` in ``Lego/api.py``):

===================================  ==========================================================
column                               description
===================================  ==========================================================
``ebay_item_type``                   eBay item type
``ebay_end_date``                    listing end date
``ebay_end_time``                    listing end time
``ebay_id``                          eBay item id
``amzn_asin``                        Amazon ASIN
``ebay_url``                         eBay listing URL
``amzn_url``                         Amazon listing URL
``ebay_price_and_shipping``          eBay price plus listed shipping
``ebay_price_and_actual_shipping``   eBay price plus fetched shipping (empty without
                                     ``--shipping`` or when no cost was found)
``amzn_price``                       Amazon price
``amzn_sales_rank``                  Amazon sales rank (``99999999`` when Amazon has none)
``ebay_model``                       model number parsed from the eBay title
``amzn_model``                       Amazon model
``ebay_title``                       eBay title
``amzn_title``                       Amazon title
``matching_model``                   ``1`` if the model numbers agree, else ``0`` (see
                                     `Model-number matching`_)
``price_diff``                       absolute price difference (see `Price comparison`_)
``meets_threshold``                  ``True`` if ``price_diff >= --min-price-diff``
===================================  ==========================================================

unparsed.csv and unfound.csv
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

One row per eBay item, with the columns ``ebay_end_date``, ``ebay_end_time``,
``ebay_id``, ``ebay_url``, ``ebay_price_and_shipping``, ``ebay_title`` and
``ebay_img_url``. ``ebay_img_url`` is fetched from eBay per item (cached; eBay's
"no image" placeholder when the item has none), so each new row costs one more eBay call.

Exit status
^^^^^^^^^^^

=====  ======================================================================
code   when
=====  ======================================================================
``0``  ``results.csv`` was written (prints ``Success! Wrote N entries (M unique)
       to results.csv``), or ``--version``
``1``  no rows to write: prints ``No results found meeting your criteria``.
       "Criteria" means any match at all, not the price threshold.
``1``  Amazon returned nothing: prints ``Error getting Amazon results.``
``1``  any other error: prints ``ERROR: <message>`` and a traceback
``1``  interrupted with Ctrl-C: prints ``Aborted by user request.``
=====  ======================================================================

Development
-----------

``manage.py`` (using ``manager``) provides dev and packaging tasks:

.. code-block:: bash

    python manage.py test        # run nose, script, and built-binary tests
    python manage.py lint        # flake8
    python manage.py clean       # remove *.pyc / *.pyo artifacts
    python manage.py buildmac    # build a standalone macOS binary (PyInstaller)
    python manage.py buildwin    # build a standalone Windows binary

Known issues
------------

* The hosted companion services are down: on 2026-11-04 both
  ``ebay-search-api.herokuapp.com`` and ``amzn-search-api.herokuapp.com`` answered
  ``503 Application Error``. ``Ebay.get_subcategories`` then returns no sub-categories
  (``Lego/api.py:193-202``), so no eBay search runs and, with an empty cache, the run
  ends with ``Error getting Amazon results.`` (``Lego/main.py:313-329``). A run cannot produce
  results until both services are back.
* A cached eBay search is reused for different ``--keywords``, and for smaller
  ``--results-per-page``/``--max-pages`` values, within its 2-hour lifetime:
  ``check_ebay_search_results`` compares only the country and the item count
  (``Lego/utils.py:252-262``).
* The threshold filter is off and cannot be turned on from the command line
  (``FILTER_AMAZON_MATCHES = False``, ``Lego/main.py:25``).
* Cache expiry is by file modification time, and appends reset it, so Amazon, shipping
  and image entries can outlive their stated lifetime (``Lego/utils.py:21-53``).

License
-------

lego is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
