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

Running the server
------------------

*Development* (Flask-Script built-in, defaults to config mode ``Development``):

.. code-block:: bash

    python manage.py runserver

*Production* (from the ``Procfile``, via gunicorn + gevent):

.. code-block:: bash

    gunicorn "app:create_app('Production')" -w 3 -k gevent

Select the config mode explicitly with ``-m/--cfgmode`` (``Development``,
``Production``, or ``Test``; see ``config.py``).

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
DELETE  ``/api/logs/<id>``   Delete a log record
======  ===================  ============================================

Log record fields
^^^^^^^^^^^^^^^^^

Provided by the client:

* ``message`` *(required)* — the log message
* ``app_name`` *(required)* — name of the app emitting the log
* ``log_level`` *(required)* — e.g. ``debug``, ``info``, ``error``
* ``time`` — client timestamp (epoch milliseconds)
* ``user`` — optional user identifier
* ``client_id`` — passed as the ``client_id`` query parameter

Added automatically by the server (from the request):

* ``utc_created``, ``referrer``, ``user_agent``, ``browser``, ``platform``, ``ip_addr``

Usage Examples
--------------

*Create a log record*

.. code-block:: bash

    curl -X POST 'http://localhost:5000/api/logs' \
        -H 'Content-Type: application/json' \
        -d '{"message": "init message", "app_name": "ongeza", "log_level": "debug", "time": 1378285847621}'

*Batch logging* — send multiple newline-separated JSON records in one request:

.. code-block:: bash

    printf '%s\n%s' \
        '{"message":"first","app_name":"ongeza","log_level":"info"}' \
        '{"message":"second","app_name":"ongeza","log_level":"error"}' \
        | curl -X POST 'http://localhost:5000/api/logs' -H 'Content-Type: application/json' --data-binary @-

*List all logs*

.. code-block:: bash

    curl 'http://localhost:5000/api/logs'

*Search* (Flask-Restless query syntax) — e.g. all ``error`` level logs:

.. code-block:: bash

    curl -G 'http://localhost:5000/api/logs' \
        --data-urlencode 'q={"filters":[{"name":"log_level","op":"eq","val":"error"}]}'

*Delete a log record*

.. code-block:: bash

    curl -X DELETE 'http://localhost:5000/api/logs/1'

Management Commands
-------------------

``manage.py`` provides several database helpers:

============  ================================================================
command       description
============  ================================================================
``createdb``  Create the database tables if they don't exist
``cleardb``   Drop and recreate all tables (removes all content)
``prunedb``   Trim the ``Logs`` table down to the most recent 5000 records
``initdb``    Clear the database and seed it with a default log record
``runtests``  Run the test suite (``nosetests``)
============  ================================================================

License
-------

flogger is distributed under the MIT License.
