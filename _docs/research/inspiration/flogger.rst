.. source: ../../../../flogger/README.rst

flogger
=======

Introduction
------------

``flogger`` is a lightweight RESTful logging API built with `Flask <http://flask.pocoo.org>`_,
`Flask-Restless <https://flask-restless.readthedocs.io/>`_, and SQLAlchemy. Clients
(web pages, apps, scripts) ``POST`` log messages to it and it persists them to a
database, automatically enriching each record with request metadata (user agent,
browser, platform, referrer, IP address, and client id).

It exposes a single ``logs`` resource with full CRUD access, supports batch logging
(multiple newline-separated records in one request), and is CORS-enabled so it can be
called directly from the browser.

Requirements
------------

* Python 2.7
* A database (SQLite for development, PostgreSQL in production)

Installation
------------

*Clone the repo and install the requirements*

.. code-block:: bash

    git clone <repo-url> flogger
    cd flogger
    pip install -r requirements.txt

*Create the database*

.. code-block:: bash

    python manage.py createdb

Configuration
-------------

``manage.py`` takes two global options, given before the command:

* ``-m/--cfgmode`` selects a config class from ``config.py`` (default:
  ``Development``).
* ``-f/--cfgfile`` names a Flask config file. It is used only when no config
  mode is set, and ``manage.py`` always sets one, so today ``-f`` has no effect
  through ``manage.py``.

When the app is created with neither a mode nor a file (``create_app()``), it
reads the config file named by the ``APP_SETTINGS`` environment variable, if set.

===============  ======================================  =====
Mode             Database (``SQLALCHEMY_DATABASE_URI``)  Debug
===============  ======================================  =====
``Development``  ``sqlite:///<repo>/app.db``             on
``Production``   ``$DATABASE_URL``, else                 off
                 ``postgres://$USER@localhost/app``
``Test``         ``sqlite:///:memory:``                  off
===============  ======================================  =====

Environment variables:

* ``DATABASE_URL`` sets the Production database. When it is set, every mode also
  runs in Heroku mode: ``SERVER_NAME`` becomes ``flogger.herokuapp.com`` and
  ``initdb`` posts to that host instead of ``localhost``.
* ``SECRET_KEY`` sets Flask's secret key (default: ``key``).
* ``APP_SETTINGS``: see above.

API settings shared by all modes: methods ``GET``, ``POST``, ``DELETE``,
``PATCH``, ``PUT``; bulk ``PATCH``/``PUT`` and function evaluation enabled; at
most 1000 results per page; URL prefix ``/api``.

Running the server
------------------

*Development* (Flask-Script built-in, defaults to config mode ``Development``,
serves on port 5000):

.. code-block:: bash

    python manage.py runserver

*Production* (from the ``Procfile``, via gunicorn + gevent):

.. code-block:: bash

    gunicorn "app:create_app('Production')" -w 3 -k gevent

Select the config mode explicitly with ``-m/--cfgmode`` (``Development``,
``Production``, or ``Test``; see ``config.py`` and `Configuration`_).

API
---

All resources live under the ``/api`` prefix.

======  ===================  ============================================
Method  Endpoint             Description
======  ===================  ============================================
GET     ``/``                Redirects to ``/api``
GET     ``/api``             Welcome message
GET     ``/api/logs``        List / search log records
GET     ``/api/logs/<id>``   Retrieve a single log record
POST    ``/api/logs``        Create a log record (metadata added automatically)
PATCH   ``/api/logs/<id>``   Update a log record
PUT     ``/api/logs/<id>``   Update a log record (same as ``PATCH``)
PATCH   ``/api/logs``        Update every record matching the body's ``q``
                             filters
PUT     ``/api/logs``        Same as ``PATCH /api/logs``
DELETE  ``/api/logs/<id>``   Delete a log record
GET     ``/api/eval/logs``   Evaluate SQL functions (``count``, ``max``, ...)
                             over the records, given in ``q``
======  ===================  ============================================

Every response is JSON with permissive CORS headers
(``Access-Control-Allow-Origin: *``). ``GET /api/logs`` returns
``{"page", "objects", "total_pages", "num_results"}``, 10 records per page by
default. Use ``?page=N`` to page and ``?results_per_page=N`` (up to 1000) to change
the page size. A request body naming a field that is not in the table is rejected
with ``400``.

Log record fields
^^^^^^^^^^^^^^^^^

Provided by the client:

* ``message`` *(required)*, text, up to 512 characters: the log message
* ``app_name`` *(required)*, text, up to 16 characters: name of the app emitting
  the log
* ``log_level`` *(required)*, text, up to 16 characters: e.g. ``debug``,
  ``info``, ``error``
* ``time``, integer: client timestamp (epoch milliseconds)
* ``user``, text, up to 32 characters: optional user identifier
* ``client_id``, text, up to 8 characters: passed as the ``client_id`` query
  parameter (a ``client_id`` in the body is replaced by the query parameter, or
  by ``null`` when there is none)

Added automatically by the server (from the request):

* ``utc_created`` (datetime): intended to be the UTC time the record is created.
  Today every record gets the time the server process started, because the
  default is computed once when the app loads.
* ``referrer`` (up to 64 characters), ``user_agent`` (up to 256), ``browser``
  (up to 16), ``platform`` (up to 16), ``ip_addr`` (up to 15, so IPv4 only)

The server sets these on ``POST`` only, replacing any values the client sends;
``PATCH`` and ``PUT`` can change them. Every record also gets an integer ``id``.
PostgreSQL rejects values longer than these limits; SQLite does not enforce
string lengths.

Usage Examples
--------------

*Create a log record*

.. code-block:: bash

    curl -X POST 'http://localhost:5000/api/logs' \
        -H 'Content-Type: application/json' \
        -d '{"message": "init message", "app_name": "ongeza", "log_level": "debug", "time": 1378285847621}'

*Batch logging*: send multiple newline-separated JSON records in one request:

.. code-block:: bash

    printf '%s\n%s' \
        '{"message":"first","app_name":"ongeza","log_level":"info"}' \
        '{"message":"second","app_name":"ongeza","log_level":"error"}' \
        | curl -X POST 'http://localhost:5000/api/logs' -H 'Content-Type: application/json' --data-binary @-

Each line is handled as its own request, but only the last line's result is
returned; errors for the earlier lines are not reported. Do not end the body
with a newline: the empty last line fails with ``400`` (``Unable to decode
data``) after the earlier records are saved. The example uses ``printf '%s\n%s'``
for that reason. The split applies to every request method.

*List all logs*

.. code-block:: bash

    curl 'http://localhost:5000/api/logs'

*Search* (Flask-Restless query syntax), e.g. all ``error`` level logs:

.. code-block:: bash

    curl -G 'http://localhost:5000/api/logs' \
        --data-urlencode 'q={"filters":[{"name":"log_level","op":"eq","val":"error"}]}'

*Delete a log record*

.. code-block:: bash

    curl -X DELETE 'http://localhost:5000/api/logs/1'

Management Commands
-------------------

``manage.py`` provides several database helpers:

==============  ================================================================
command         description
==============  ================================================================
``createdb``    Create the database tables if they don't exist
``cleardb``     Drop and recreate all tables (removes all content)
``prunedb``     Trim the ``Logs`` table down to the most recent 5000 records
                (intended; see below)
``initdb``      Clear the database and seed it with a default log record
                through a running server (see below)
``runtests``    Run the test suite (``nosetests``) (intended; not working)
``checkstage``  Run ``app/tests/test.sh`` as a git pre-commit check (intended;
                not working)
``runserver``   Run the development server (Flask-Script built-in)
==============  ================================================================

``prunedb`` deletes ``count - 5000`` rows when the table holds more than 5000,
then prints how many were pruned and the new count. The 5000 cap is fixed in
code. The query has no ``ORDER BY``, so which rows go is up to the database
(usually the lowest ids, i.e. the oldest). ``bin/prunedb`` runs it in
``Production`` mode for scheduled use.

``initdb`` runs ``cleardb`` and then posts the seed record over HTTP to
``localhost:5001`` (change the port with ``-p/--port``). A server must already be
running on that port; ``runserver`` uses 5000 by default, so either pass ``-p
5000`` or start the server on 5001. With no server listening, the command fails
with a connection error and leaves the database empty; any response other than
``201`` is printed.

``runtests`` and ``checkstage`` fail with ``NameError`` because ``call`` is
never imported. There is no ``app/tests`` directory, and ``nose`` is not in
``requirements.txt``.

Known issues
------------

* ``utc_created`` holds the server process start time, not the insert time
  (``app/models.py:13`` passes ``dt.utcnow()`` instead of ``dt.utcnow``).
* ``prunedb`` deletes rows in unspecified order (``manage.py:68-70``).
* ``runtests`` and ``checkstage`` raise ``NameError`` (``manage.py:24``, ``:32``).
* ``-f/--cfgfile`` is ignored because ``-m`` always has a value
  (``manage.py:13-15``, ``app/__init__.py:32-37``).
* A batch request's response covers only its last line; a trailing newline
  turns it into a ``400`` (``app/__init__.py:63-69``).

License
-------

flogger is distributed under the MIT License.
