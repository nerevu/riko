lego
====

Introduction
------------

``lego`` is a command-line tool that compares eBay and Amazon Lego set prices to surface
arbitrage opportunities — Lego sets selling on eBay for meaningfully less than on Amazon.

It searches eBay for Lego sets in a given category, matches each item to its Amazon
listing by model number, compares the prices, and writes the matches whose price
difference exceeds a threshold to a CSV. It can also fetch eBay shipping costs and
factor them into the comparison.

``lego`` is powered by two companion services:

* `eBay Search API <https://github.com/reubano/ebay-search-api>`_
* `amzn-search-api <https://github.com/reubano/amzn-search-api>`_

How it works
------------

1. Search eBay (default category ``Toys & Games`` › ``Lego``, country ``UK``) for Lego
   sets, excluding accessories (keychains, minifigures, bags, etc.).
2. Parse each eBay item's Lego set/model number and look it up on Amazon.
3. Compare prices and keep the matches whose difference meets ``--min-price-diff``.
4. Optionally add eBay shipping costs.
5. Write results to CSV files (see `Output`_).

Intermediate eBay/Amazon results are cached locally (with expiry) to avoid repeat API
calls between runs.

.. note::

   ``lego`` is a legacy Python 2 project.

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
``-p, --shipping``            calculate eBay shipping cost
``-d, --destination``         shipping destination country (default ``US``)
``-z, --zipcode``             destination postal code (required if country is ``US``)
``-k, --keywords``            keywords to search (defaults to a curated Lego query)
``-f, --results-file``        results CSV filename (default ``results.csv``)
``-F, --unparsed-file``       CSV for eBay items with unparsable model numbers (``unparsed.csv``)
``-o, --unfound-file``        CSV for eBay items not found on Amazon (``unfound.csv``)
``-m, --min-price-diff``      minimum price-difference threshold (default ``10``)
``-r, --results-per-page``    eBay results per page to fetch (default ``100``)
``-M, --max-pages``           max eBay pages to fetch (default ``100``)
``-R, --research``            re-search null Amazon results
``-c, --country``             eBay country to search (default ``UK``)
``-C, --category``            eBay main category (default ``Toys & Games``)
``-S, --sub-category``        eBay sub-category (default ``Lego``)
``-i, --search-index``        Amazon search index (default ``Toys``)
============================  ==============================================================

Output
------

``lego`` writes up to three CSV files:

============  =================================================================
file          contents
============  =================================================================
``results.csv``   matched eBay/Amazon items meeting the price-difference threshold
``unparsed.csv``  eBay items whose Lego model number couldn't be parsed
``unfound.csv``   eBay items with no matching Amazon listing
============  =================================================================

Development
-----------

``manage.py`` (using ``manager``) provides dev and packaging tasks:

.. code-block:: bash

    python manage.py test        # run nose + script tests
    python manage.py lint        # flake8
    python manage.py clean       # remove *.pyc / *.pyo artifacts
    python manage.py buildmac    # build a standalone macOS binary (PyInstaller)
    python manage.py buildwin    # build a standalone Windows binary

License
-------

lego is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
