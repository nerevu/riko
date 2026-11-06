.. source: ../../../../amzn-search-api/README.rst

AMZN Search API |travis|
========================

.. |travis| image:: https://img.shields.io/travis/reubano/amzn-search-api/master.svg
    :target: https://travis-ci.org/reubano/amzn-search-api

Introduction
------------

`AMZN Search API <http://amzn-search-api.herokuapp.com>`_ is a `Flask <http://flask.pocoo.org>`_ (`About Flask`_) powered RESTful API wrapper to the `Amazon search portal <https://www.amazon.com/ref=nb_sb_noss_null>`_.

Requirements
------------

AMZN Search API has been tested and known to work on the following configurations:

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

    git clone git@github.com:reubano/amzn-search-api.git

*Install requirements*

.. code-block:: bash

    cd amzn-search-api
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

AMZN Search API comes with a built in script manager ``manage.py``. Use it to
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
``manage`` (see `Known issues`_).

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
CACHE_TIMEOUT            amount of time (in seconds) to cache responses                   60 minutes
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
configuration mode (``app/__init__.py:81-90``):

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

AMZN Search API references the following environment variables:

======================== ======================================== =================================================
variable                 description                              when missing
======================== ======================================== =================================================
AWS_ACCESS_KEY_ID        your AWS access key ID                   every search request aborts (``SystemExit``)
AWS_SECRET_ACCESS_KEY    your AWS access key secret               every search request aborts (``SystemExit``)
AWS_ASSOCIATE_TAG_US     your AWS Associate tag for US region     the tag ``na`` is sent
AWS_ASSOCIATE_TAG_UK     your AWS Associate tag for UK region     the tag ``na`` is sent
HEROKU                   use the MemCachier cache and the         see `Cache backends`_
                         ``<app>.herokuapp.com`` server name
STAGE                    on Heroku, use the ``<app>-stage``       the production server name
                         server name
DIGITALOCEAN             use the ``api.nerevu.com`` server name   no server name is set (and no forced SSL)
                         (checked only when ``HEROKU`` is unset)
MEMCACHIER_SERVERS,      MemCachier credentials (when ``HEROKU``  see `Cache backends`_
MEMCACHIER_USERNAME,     is set)
MEMCACHIER_PASSWORD
MEMCACHE_SERVERS         memcached server (Production mode)       see `Cache backends`_
APP_SETTINGS             path to a config file, read only when    ignored
                         neither a mode nor a file is given
======================== ======================================== =================================================

The associate tag is read per region as ``AWS_ASSOCIATE_TAG_<REGION>``. Setting
a server name (``HEROKU`` or ``DIGITALOCEAN``) also turns on forced SSL.

To set an environment variable, e.g. MY_ENV, *do the following*:

.. code-block:: bash

    echo 'export MY_ENV=value' >> ~/.profile

Usage Examples
--------------

All resources live under the ``/api/v1`` prefix (they are also reachable at
``/<resource>/`` and ``/api/<resource>/``). Every response is JSON of the form
``{"status": <reason>, "objects": <result>}``, where ``status`` is the HTTP
reason phrase of the response code (``"OK"`` for 200, ``"Bad Request"`` for
400), not the number. The interactive Swagger UI documentation is served at the
root URL.

=============================== ====== ===================================================
endpoint                        method description
=============================== ====== ===================================================
``/api/v1/search/``             GET    search Amazon (cached, see `Caching`_)
``/api/v1/lorem/``              GET    a random "bacon ipsum" sentence (cached)
``/api/v1/delete/<base>/``      GET    delete one cached response
``/api/v1/reset/``              GET    delete every cached response
=============================== ====== ===================================================

*Search for items by keyword*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?q=lego+millennium+falcon'

Accepts ``q`` (search term, required) plus optional ``condition``
(``New``/``Used``), ``region`` (``US``/``UK``), and ``limit``:

============= ========= ===========================================================
parameter     default   description
============= ========= ===========================================================
``q``         none      the search keywords (required)
``condition`` ``New``   item condition, ``New`` or ``Used``
``region``    ``US``    the Amazon site to search, ``US`` or ``UK``; it also picks
                        the ``AWS_ASSOCIATE_TAG_<REGION>`` variable
``limit``     ``10``    the number of results to return
============= ========= ===========================================================

Every search uses ``SearchIndex=All`` and ``ResponseGroup=Medium``; these can't
be overridden. Any other query parameter is passed through to the Amazon
``ItemSearch`` call, and ``key``, ``secret`` and ``tag`` replace the AWS
credentials and associate tag for that request (see `Known issues`_).

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?q=guitar&condition=Used&region=UK&limit=5'

A successful search returns ``objects`` as a list of records, one per item:

============== ====== ============================================================
field          type   description
============== ====== ============================================================
``asin``       str    Amazon Standard Identification Number
``model``      str    model number
``url``        str    affiliate offer URL (carries the associate tag)
``title``      str    item title
``price``      float  Amazon price; ``0`` when Amazon gives no price
``country``    str    the ``region`` that was searched
``currency``   str    currency code of ``price``
``sales_rank`` str    Amazon sales rank, as a string
============== ====== ============================================================

Errors return the error message as ``objects``:

====== ===================================================================
status cause
====== ===================================================================
500    Amazon rejected the search (``SearchException``)
503    the request to Amazon failed; reported as
       ``Amazon Associates tag <tag> is invalid for region <region>``
400    the region lookup failed; reported as ``region '<X>' does not exist``
====== ===================================================================

Missing ``AWS_ACCESS_KEY_ID`` or ``AWS_SECRET_ACCESS_KEY`` raises ``SystemExit``
inside the request instead of returning an error response.

*Get a random "bacon ipsum" sentence (handy for testing)*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/lorem/'

*Delete a single cached url by base*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/delete/lorem/'

The response is ``{"objects": "Key: <url> deleted", "status": "OK"}`` whether or
not the entry existed.

Caching
^^^^^^^

``search`` and ``lorem`` responses are cached for ``CACHE_TIMEOUT`` (60
minutes) and sent with matching ``Cache-Control: public, max-age`` and
``Expires`` headers. The cache key is the full request URL, query string
included, so each route alias (``/search/``, ``/api/search/``,
``/api/v1/search/``) and each distinct query has its own entry. The delete
route removes the entry whose URL is its own URL with ``delete/`` removed, so it
must repeat the prefix and query string of the cached request:

.. code-block:: bash

    # clears the cached '/api/v1/search/?q=guitar', but not '/search/?q=guitar'
    curl 'http://localhost:5000/api/v1/delete/search/?q=guitar'

*Reset all caches*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/reset/'

Documentation
-------------

For a list of available resources, example requests and responses, and code samples,
view the `online documentation <https://amzn-search-api.herokuapp.com/>`_.

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
    ├── test.txt
    └── tox.ini

Contributing
------------

*First time*

1. Fork
2. Clone
3. Code (if you are having problems committing because of git pre-commit
   hook errors, just run ``manage check`` to see what the issues are.)
4. Use spaces **not** tabs
5. Add upstream ``git remote add upstream https://github.com/reubano/amzn-search-api.git``
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

- Amazon has retired the Product Advertising API 4.0 that ``python-amazon-simple-product-api``
  (``app/api.py:9``) calls, so every search route documented here is intended; today
  the upstream calls fail.
- ``key``, ``secret`` and ``tag`` query parameters replace the AWS credentials
  and associate tag for that request (``app/views.py:282-289`` passes the query
  string to ``Amazon(**kwargs)``, which reads them at ``app/api.py:181-183``).
- Missing AWS keys raise ``SystemExit`` inside the request handler
  (``app/api.py:185-186``) instead of returning an error response.
- In Production mode without ``MEMCACHE_SERVERS`` (and ``HEROKU`` unset) the
  memcached server list is ``[None]`` (``app/__init__.py:86-88``).
- ``-f/--cfgfile`` and ``APP_SETTINGS`` are never read when started through
  ``manage``: ``-m`` defaults to ``Development`` (``manage.py:26-27``) and
  ``create_app`` checks the mode first (``app/__init__.py:71-76``).
- ``serve`` accepts ``-T``, ``-l`` and ``-o`` but ignores them (``manage.py:36``).
- A non-integer ``limit`` raises ``ValueError`` (HTTP 500), since
  ``int(limit)`` runs outside the error handling (``app/views.py:285``).
- ``manage lint --strict`` runs pylint with ``tests/standard.rc``, but the file
  is ``app/tests/standard.rc`` (``manage.py:86``).

License
-------

AMZN Search API is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
