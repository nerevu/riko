.. source: ../../../../ebay-search-api/README.rst

eBay Search API |travis|
========================

.. |travis| image:: https://img.shields.io/travis/reubano/ebay-search-api/master.svg
    :target: https://travis-ci.org/reubano/ebay-search-api

Introduction
------------

`eBay Search API <http://ebay-search-api.herokuapp.com>`_ is a `Flask <http://flask.pocoo.org>`_ (`About Flask`_) powered RESTful API wrapper to the `eBay search portal <https://www.ebay.com>`_. It exposes eBay item search over a simple, cacheable HTTP/JSON interface with interactive Swagger UI documentation served at the root URL, so clients can query listings without dealing with eBay's SDK or auth directly.

Requirements
------------

eBay Search API has been tested and known to work on the following configurations:

- MacOS X 10.9.5
- Ubuntu 14.04 LTS
- Python 2.7, 3.5, and 3.6

Framework
---------

Flask Extensions
^^^^^^^^^^^^^^^^

- Route caching with `Flask-Caching <https://pythonhosted.org/Flask-Caching/>`_.
- GZIPed responses with `Flask-Compress <https://github.com/libwilliam/flask-compress>`_.
- CORS support with `Flask-Cors <https://flask-cors.readthedocs.io/en/latest/>`_
- Enforced SSL with `Flask-SSLify <https://github.com/kennethreitz/flask-sslify>`_

Production Server
^^^^^^^^^^^^^^^^^

- `Memcached <https://memcached.org/>`_ (see `Cache backends`_ for which cache
  each configuration mode uses)
- `gunicorn <https://gunicorn.org/>`_
- `gevent <https://www.gevent.org/>`_

Quick Start
-----------

Preparation
^^^^^^^^^^^

*Check that the correct version of Python is installed*

.. code-block:: bash

    python -V

Activate your `virtualenv <http://docs.python-guide.org/en/latest/dev/virtualenvs/#virtualenvironments-ref>`_

Installation
^^^^^^^^^^^^

*Clone the repo*

.. code-block:: bash

    git clone git@github.com:reubano/ebay-search-api.git

*Install requirements*

.. code-block:: bash

    cd ebay-search-api
    pip install -r base-requirements.txt

*Run API server*

.. code-block:: bash

    ./manage.py serve

The ``manage`` command used in the rest of this readme comes from the
``manage.py`` package in ``dev-requirements.txt``
(``pip install -r dev-requirements.txt``); ``./manage.py <command>`` or
``python manage.py <command>`` works without it.

Now *view the API documentation* at ``http://localhost:5000``

Scripts
-------

eBay Search API comes with a built in script manager ``manage.py``. Use it to
start the server, run tests, and run linters. There is no database to
initialize.

Usage
^^^^^

.. code-block:: bash

    manage <command> [command-options] [manager-options]

Examples
^^^^^^^^

*Start server*

.. code-block:: bash

    manage serve

*Run tests*

.. code-block:: bash

    manage test

*Run linters*

.. code-block:: bash

    manage lint

Manager options
^^^^^^^^^^^^^^^

      -m MODE, --cfgmode=MODE  set the configuration mode, must be one of
                               ['Production', 'Development', 'Test'] defaults
                               to 'Development'. See `config.py` for details
      -f FILE, --cfgfile=FILE  set the configuration file (absolute path)

``-m`` always has a value (``Development`` when omitted), and the app loads the
mode before it looks at a file, so ``-f`` has no effect when run through
``manage`` (see `Known issues`_). The mode does not choose between the eBay
sandbox and production APIs; see `Sandbox or production`_.

Commands
^^^^^^^^

    runserver           Runs the flask development server
    serve               Runs the flask development server
    check               Check staged changes for lint errors
    lint                Check style with linters
    test                Run nose, tox, and script tests
    add_keys            Deploy staging app
    deploy              Deploy staging app
    install             Install requirements
    shell               Runs a Python shell inside Flask application context.

Command options
^^^^^^^^^^^^^^^

Type ``manage <command> --help`` to view any command's options

.. code-block:: bash

    manage serve --help

Output

.. code-block:: text

    usage: manage serve [-?] [-t] [-T TIMEOUT] [-l] [-o] [-p PORT] [-h HOST]

    Runs the flask development server

    optional arguments:
      -?, --help            show this help message and exit
      -t, --threaded        Run multiple threads
      -T TIMEOUT, --timeout TIMEOUT
                            Fetch timeout
      -l, --live            Use live data
      -o, --offline         Offline mode
      -p PORT, --port PORT  The server port
      -h HOST, --host HOST  The server host

``-T``, ``-l`` and ``-o`` are accepted by ``serve`` but have no effect: the
server ignores them (``manage.py:36``). ``runserver`` takes only ``-t``, ``-p``
and ``-h``.

Example
^^^^^^^

*Start production server on port 1000*

.. code-block:: bash

    manage serve -p 1000 -m Production

Configuration
-------------

Config Variables
^^^^^^^^^^^^^^^^

The following configurations settings are available in ``config.py``:

======================== ================================================================ =========================================
variable                 description                                                      default value
======================== ================================================================ =========================================
__DOMAIN__               your custom domain                                               nerevu.com
CACHE_TIMEOUT            amount of time (in seconds) to cache ``search``, ``ship``,       60 minutes
                         ``item`` and ``lorem`` responses
CAT_CACHE_TIMEOUT        amount of time (in seconds) to cache the top-level category      7 days
                         list (``/category/``)
SUB_CAT_CACHE_TIMEOUT    amount of time (in seconds) to cache subcategory responses       24 hours
                         (``/category/<id or name>/``)
API_RESULTS_PER_PAGE     unused; the ``limit`` search parameter sets the result count     32
API_MAX_RESULTS_PER_PAGE unused; ``limit`` has no maximum                                 1024
API_URL_PREFIX           string to prefix each resource in the api url                    '/api/v1'
DEBUG_MEMCACHE           use memcached (see `Cache backends`_)                            ``True`` in Production, ``False`` in
                                                                                          Development and Test
HOST                     the host ``manage serve`` binds to when ``-h`` is omitted        ``127.0.0.1`` (``0.0.0.0`` in
                                                                                          Production)
======================== ================================================================ =========================================

Cache backends
^^^^^^^^^^^^^^

The cache backend depends on the ``HEROKU`` environment variable and the
configuration mode (``app/__init__.py:153-162``):

=============================== ================= =============================================
when                            backend           environment variables it reads
=============================== ================= =============================================
``HEROKU`` is set (any mode)    ``saslmemcached`` ``MEMCACHIER_SERVERS``, ``MEMCACHIER_USERNAME``,
                                                  ``MEMCACHIER_PASSWORD``
Production mode                 ``memcached``     ``MEMCACHE_SERVERS``
Development and Test modes      ``simple``        none (an in-process cache)
=============================== ================= =============================================

In Production mode without ``MEMCACHE_SERVERS`` the memcached server list is
``[None]``, so the cache is misconfigured (see `Known issues`_). ``HEROKU`` is
not set by Heroku itself; set it yourself (``heroku config:set HEROKU=true``).

Environment Variables
^^^^^^^^^^^^^^^^^^^^^

eBay Search API references the following environment variables:

======================== ==================== =========== =============================================
variable                 description          environment used by
======================== ==================== =========== =============================================
EBAY_DEV_ID              your eBay device ID              every eBay call
EBAY_LIVE_APP_ID         your eBay AppID      Production  every eBay call
EBAY_LIVE_CERT_ID        your eBay CertID     Production  ``item`` and ``category`` (Trading API)
EBAY_LIVE_TOKEN          your eBay Token      Production  ``item`` and ``category``; falls back to
                                                          ``envs.yml``
EBAY_SB_APP_ID           your eBay AppID      Sandbox     every eBay call
EBAY_SB_CERT_ID          your eBay CertID     Sandbox     ``item`` and ``category`` (Trading API)
EBAY_SB_TOKEN            your eBay Token      Sandbox     ``item`` and ``category``; falls back to
                                                          ``envs.yml``
HEROKU                   use the MemCachier               see `Cache backends`_; also sets the
                         cache                            ``<app>.herokuapp.com`` server name
STAGE                    use the stage name               on Heroku, the ``<app>-stage.herokuapp.com``
                                                          server name
DIGITALOCEAN             use a custom domain              ``api.nerevu.com`` server name (checked only
                                                          when ``HEROKU`` is unset)
MEMCACHIER_SERVERS,      MemCachier                       see `Cache backends`_
MEMCACHIER_USERNAME,     credentials
MEMCACHIER_PASSWORD
MEMCACHE_SERVERS         memcached server                 Production mode; see `Cache backends`_
APP_SETTINGS             path to a config                 read only when neither a mode nor a file is
                         file                             given, so never through ``manage``
======================== ==================== =========== =============================================

Setting a server name (``HEROKU`` or ``DIGITALOCEAN``) also turns on forced SSL.

Sandbox or production
^^^^^^^^^^^^^^^^^^^^^

The configuration mode has no effect on which eBay environment is called. Each
request picks it with the ``sandbox`` query parameter: ``?sandbox=true`` uses the
sandbox hosts and the ``EBAY_SB_*`` variables; without it, every request goes to
production with the ``EBAY_LIVE_*`` variables. ``sandbox=true`` is part of the
cached URL, so sandbox and production responses are cached separately.

When ``EBAY_LIVE_TOKEN`` (or ``EBAY_SB_TOKEN``) is unset, the token is read from
the same-named key in ``envs.yml`` at the repository root. That file is
git-ignored; CI decrypts it from ``envs.yml.enc``. With neither, the ``item`` and
``category`` routes fail with an unhandled error (HTTP 500).

To set an environment variable, e.g. MY_ENV, *do the following*:

.. code-block:: bash

    echo 'export MY_ENV=value' >> ~/.profile

Usage Examples
--------------

All resources live under the ``/api/v1`` prefix (they are also reachable at
``/<resource>/`` and ``/api/<resource>/``). Every response is JSON of the form
``{"status": <reason>, "objects": <result>}``, where ``status`` is the HTTP
reason phrase of the response code (``"OK"`` for 200, ``"Not Found"`` for 404),
not the number. The interactive Swagger UI documentation is served at the root
URL.

The eBay endpoints (``search``, ``item``, ``ship`` and ``category``) accept
``sandbox=true`` (see `Sandbox or production`_) and ``country``: one of ``US``
(default), ``UK``, ``FR``, ``DE``, ``IT``, ``ES`` or ``CA``. Their query values
are parsed before use: ``true``/``false`` become booleans and numbers become
numbers.

========================================== ====== ===========================================
endpoint                                   method description
========================================== ====== ===========================================
``/api/v1/search/``                        GET    search listings (Finding API)
``/api/v1/item/<item_id>/``                GET    one item's details (Trading API)
``/api/v1/ship/<item_id>/``                GET    an item's shipping cost (Shopping API)
``/api/v1/category/``                      GET    the top-level categories (Trading API)
``/api/v1/category/<id or name>/``         GET    a category's subcategories (Trading API)
``/api/v1/category/<name>/subcategories/`` GET    also a category's subcategories
``/api/v1/lorem/``                         GET    a random "bacon ipsum" sentence
``/api/v1/cache/``                         DELETE delete every cached response
``/api/v1/cache/<base>/``                  DELETE delete one cached response (deletes nothing
                                                  today; see below)
========================================== ====== ===========================================

The ``/api/`` prefix has no ``/api/category/<id or name>/`` route; use
``/api/category/<name>/subcategories/`` there. A numeric name on that route is
looked up as a name, so it returns 404.

*Search for items by keyword*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?q=lego+millennium+falcon'

Accepts ``q`` (keywords) **or** ``cid`` (category id), plus optional ``country``
(``US``/``UK``, or any country listed above), ``verb``, ``sort_order``,
``limit``, and ``page``:

============== ======================= ==================================================
parameter      default                 description
============== ======================= ==================================================
``q``          none                    keywords (``q`` or ``cid`` is required)
``cid``        none                    category id (``q`` or ``cid`` is required)
``country``    ``US``                  the eBay site to search
``verb``       ``findItemsAdvanced``   one of ``findCompletedItems``,
                                       ``findItemsAdvanced``, ``findItemsByCategory``,
                                       ``findItemsByKeywords``, ``findItemsByProduct``,
                                       ``findItemsIneBayStores``, ``getHistograms``
``sort_order`` ``EndTimeSoonest``      one of ``BestMatch``, ``CurrentPriceHighest``,
                                       ``DistanceNearest``, ``EndTimeSoonest``,
                                       ``PricePlusShippingHighest``,
                                       ``PricePlusShippingLowest``, ``StartTimeNewest``
``limit``      ``10``                  results per page
``page``       ``1``                   the results page to return
============== ======================= ==================================================

Any other query parameter is passed through to the eBay Finding call as-is (for
example ``itemFilter`` or ``outputSelector``).

A search returns ``objects`` as
``{"results": {<item id>: <item>, ...}, "pages": <total pages>, "message": <error or null>}``.
``results`` is a mapping keyed by item id, not a list. Each item has these
fields:

============================== ====== ====================================================
field                          type   description
============================== ====== ====================================================
``id``                         str    item id (also the key in ``results``)
``url``                        str    item URL
``title``                      str    item title
``condition``                  str    condition display name
``item_type``                  str    listing type
``price``                      float  current price (``0`` when missing)
``buy_now_price``              float  Buy It Now price (``0`` when missing)
``shipping``                   float  shipping cost (``0`` when missing)
``price_and_shipping``         float  ``price`` + ``shipping``
``buy_now_price_and_shipping`` float  ``buy_now_price`` + ``shipping``
``end_date``                   str    listing end date, ``YYYY-MM-DD``
``end_time``                   str    listing end time, ``HH:MM``
``end_date_time``              int    approximate seconds from the start of 2010 to the
                                      end time (365-day years, no leap days), usable
                                      for sorting; not a Unix timestamp
``country``                    str    the ``country`` searched
``currency``                   str    the site currency (``USD``, ``GBP``, ``EUR`` or
                                      ``CAD``)
============================== ====== ====================================================

When eBay reports an error (including a connection error), the search still
returns 200 with an empty ``results`` and the eBay error text in ``message``.

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?q=guitar&sort_order=CurrentPriceHighest&limit=5&page=2'

*Search within a category*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?cid=267&country=UK'

*Get an item's details*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/item/18215047500/'

``objects`` is eBay's ``GetItem`` ``Item`` record unchanged (``ItemID``,
``Title``, ``SellingStatus``, ``ShippingDetails``, ``Seller`` and so on). If eBay
returns an error the route fails with HTTP 500 (see `Known issues`_).

*Calculate an item's shipping cost*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/ship/18215047500/?dest=US&code=94105&quantity=2'

============ ======== ==========================================================
parameter    default  description
============ ======== ==========================================================
``dest``     ``US``   destination country code
``code``     none     destination postal code; required when ``dest`` is ``US``
``quantity`` none     quantity to ship
``details``  none     include eBay's shipping details
``country``  ``US``   the eBay site of the item
============ ======== ==========================================================

Any other query parameter is passed through to the eBay ``GetShippingCosts``
call. ``objects`` is ``{"results": {...}}`` with ``item_id``,
``actual_shipping`` (float), ``actual_shipping_currency``,
``actual_shipping_service`` and ``actual_shipping_type``. When there is no cost
summary (for example ``dest=US`` without ``code``) the response is still 200,
and ``results`` holds ``item_id`` and a ``message`` such as
``Missing DestinationPostalCode``.

*List all top-level categories*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/category/'

``objects`` is a list of category records: ``id``, ``category`` (name),
``level``, ``parent_id`` and ``country``. eBay's values are passed through as
strings (``"id": "20081", "level": "1"``). The list is cached for 7 days, both
as a response and as the lookup the name route uses.

*List the subcategories of a category (by id or name)*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/category/267/'
    curl 'http://localhost:5000/api/v1/category/Books/'

The result is a list of category records as above, cached for 24 hours. A name
is matched case-insensitively against the top-level category names (URL-encoded
names such as ``Toys%20%26%20Hobbies`` work). An unknown name or id returns 404
with ``Category <name or id> doesn't exist. View <url> to see valid categories.``

*Get a random "bacon ipsum" sentence (handy for testing)*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/lorem/'

*Reset the cache (or clear a single resource by base)*

.. code-block:: bash

    curl -X DELETE 'http://localhost:5000/api/v1/cache/'
    curl -X DELETE 'http://localhost:5000/api/v1/cache/lorem/'

Both return HTTP 204 with an empty body. The first clears every cached
response. The second is intended to clear the cached ``/api/v1/lorem/``
response, but deletes nothing today: it looks up the key
``.../api/v1/cache/lorem/``, which is never cached (see `Known issues`_).

Responses are cached under the full request URL, query string included, so each
route alias and each distinct query has its own entry. ``search``, ``ship``,
``item`` and ``lorem`` are cached for ``CACHE_TIMEOUT`` (60 minutes), the
top-level category list for 7 days and subcategory lists for 24 hours, with
matching ``Cache-Control: public, max-age`` and ``Expires`` headers.

Documentation
-------------

For a list of available resources, example requests and responses, and code samples,
view the `online documentation <https://ebay-search-api.herokuapp.com/>`_.

Advanced Installation
---------------------

Production Server
^^^^^^^^^^^^^^^^^

Preparation
~~~~~~~~~~~

Getting ``gevent`` up and running is a bit tricky so follow these instructions carefully.

To use ``gevent``, you first need to install ``libevent``.

*Linux*

.. code-block:: bash

    apt-get install libevent-dev

*Mac OS X via* `homebrew <http://mxcl.github.com/homebrew/>`_

.. code-block:: bash

    brew install libevent

*Mac OS X via* `macports <http://www.macports.com/>`_

.. code-block:: bash

    sudo port install libevent

*Mac OS X via DMG*

`download on Rudix <http://rudix.org/packages-jkl.html#libevent>`_


Installation
~~~~~~~~~~~~

Now that libevent is handy, *install the remaining requirements*

.. code-block:: bash

    pip install -r requirements.txt

Or via the following if you installed libevent from macports

.. code-block:: bash

    sudo CFLAGS="-I /opt/local/include -L /opt/local/lib" pip install gevent
    pip install -r requirements.txt

Foreman
~~~~~~~

Finally, *install foreman*

.. code-block:: bash

    sudo gem install foreman

Now, you can *run the application* locally

.. code-block:: bash

    foreman start

You can also *specify what port you'd prefer to use*

.. code-block:: bash

    foreman start -p 5555

Deployment
^^^^^^^^^^

If you haven't `signed up for Heroku <https://api.heroku.com/signup>`_, go
ahead and do that. You should then be able to `add your SSH key to
Heroku <http://devcenter.heroku.com/articles/quickstart>`_, and also
`heroku login` from the commandline.

*Install heroku and create your app*

.. code-block:: bash

    sudo gem install heroku
    heroku create -s cedar app_name

*Add memcachier*

.. code-block:: bash

    heroku addons:add memcachier

*Push to Heroku*

.. code-block:: bash

    git push heroku master

*Start the web instance and make sure the application is up and running*

.. code-block:: bash

    heroku ps:scale web=1
    heroku ps

Now, we can *view the application in our web browser*

.. code-block:: bash

    heroku open

And anytime you want to redeploy, it's as simple as ``git push heroku master``.
Once you are done coding, deactivate your virtualenv with ``deactivate``.

Directory Structure
-------------------

.. code-block:: bash

    $ tree . | sed 's/+----/├──/; /.pyc/d; /.DS_Store/d'
    .
    ├── LICENSE
    ├── MANIFEST.in
    ├── Procfile
    ├── README.rst
    ├── app
    │   ├── __init__.py
    │   ├── api.py
    │   ├── doc_parser.py
    │   ├── frs.py
    │   ├── helper.py
    │   ├── static
    │   │   ├── favicon-16x16.png
    │   │   ├── favicon-32x32.png
    │   │   ├── index.html
    │   │   ├── oauth2-redirect.html
    │   │   ├── swagger-ui-bundle.js
    │   │   ├── swagger-ui-bundle.js.map
    │   │   ├── swagger-ui-standalone-preset.js
    │   │   ├── swagger-ui-standalone-preset.js.map
    │   │   ├── swagger-ui.css
    │   │   ├── swagger-ui.css.map
    │   │   ├── swagger-ui.js
    │   │   └── swagger-ui.js.map
    │   ├── templates
    │   │   └── index.html
    │   ├── tests
    │   │   ├── standard.rc
    │   │   ├── test.sh
    │   │   ├── test_site.py
    │   ├── utils.py
    │   ├── views.py
    ├── base-requirements.txt
    ├── config.py
    ├── dev-requirements.txt
    ├── ebay.yaml.enc
    ├── envs.yml.enc
    ├── helpers
    │   ├── check-stage
    │   ├── clean
    │   ├── pippy
    │   ├── srcdist
    │   └── wheel
    ├── manage.py
    ├── py2-requirements.txt
    ├── requirements.txt
    ├── runtime.txt
    ├── setup.cfg
    ├── setup.py
    └── tox.ini

Contributing
------------

*First time*

1. Fork
2. Clone
3. Code (if you are having problems committing because of git pre-commit
   hook errors, just run ``manage check`` to see what the issues are.)
4. Use spaces **not** tabs
5. Add upstream ``git remote add upstream https://github.com/reubano/ebay-search-api.git``
6. Rebase ``git rebase upstream/master``
7. Test ``manage test``
8. Push ``git push origin master``
9. Submit a pull request

*Continuing*

1. Code (if you are having problems committing because of git pre-commit
   hook errors, just run ``manage check`` to see what the issues are.)
2. Use spaces **not** tabs
3. Update upstream ``git fetch upstream``
4. Rebase ``git rebase upstream/master``
5. Test ``manage test``
6. Push ``git push origin master``
7. Submit a pull request

Contributors
------------

.. code-block:: bash

    $ git shortlog -sn
        95  Reuben Cummings

About Flask
-----------

`Flask <http://flask.pocoo.org>`_ is a BSD-licensed microframework for Python based on
`Werkzeug <http://werkzeug.pocoo.org/>`_, `Jinja2 <http://jinja.pocoo.org>`_ and good intentions.

Known issues
------------

- eBay has decommissioned the Finding and Shopping APIs that ``ebaysdk.finding`` and
  ``ebaysdk.shopping`` (``app/api.py:13,15``) call, so the routes built on them are
  intended; today those upstream calls fail.
- ``DELETE /cache/<base>/`` deletes nothing: it strips ``delete/`` from its own
  URL (``app/views.py:277``), which contains ``cache/``, so the key it deletes
  is never a cached URL.
- ``DELETE /cache/`` and ``/cache/<base>/`` set status 204 with a message
  (``app/views.py:284``); a 204 response carries no body, so the message is
  never sent.
- ``/item/<item_id>/`` reads ``response['Item']`` outside its error handling
  (``app/views.py:241-242``); an eBay error response has no ``Item``, so the
  route fails with a ``KeyError`` (HTTP 500).
- The search route's 500 branch never runs: ``Ebay.execute`` catches eBay
  connection errors and returns them as data (``app/api.py:154-178``), so
  upstream failures come back as 200 with ``message`` set.
- With no ``EBAY_*_TOKEN`` variable and no ``envs.yml``, the Trading routes
  (``item``, ``category``) fail opening the file (``app/api.py:30-34,216,221``).
- Query parameters ``appid``, ``devid``, ``certid``, ``token`` and
  ``config_file`` replace the configured eBay credentials for that request:
  every view passes the query string into the API constructors
  (``app/api.py:113-128,214-221``).
- In Production mode without ``MEMCACHE_SERVERS`` (and ``HEROKU`` unset) the
  memcached server list is ``[None]`` (``app/__init__.py:158-160``).
- ``-f/--cfgfile`` and ``APP_SETTINGS`` are never read when started through
  ``manage``: ``-m`` defaults to ``Development`` (``manage.py:26-27``) and
  ``create_app`` checks the mode first (``app/__init__.py:143-148``).
- ``serve`` accepts ``-T``, ``-l`` and ``-o`` but ignores them (``manage.py:36``).
- ``manage lint --strict`` runs pylint with ``tests/standard.rc``, but the file
  is ``app/tests/standard.rc`` (``manage.py:86``).

License
-------

eBay Search API is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
