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

- `Memcached <https://memcached.org/>`_
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

    manage serve

Now *view the API documentation* at ``http://localhost:5000``

Scripts
-------

AMZN Search API comes with a built in script manager ``manage.py``. Use it to
start the server, run tests, and initialize the database.

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

    manage manage serve --help

Output

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
API_RESULTS_PER_PAGE     the number of results returned per page                          24
API_MAX_RESULTS_PER_PAGE the maximum number of results returned per page                  1024
API_URL_PREFIX           string to prefix each resource in the api url                    '/api/v1'
======================== ================================================================ =========================================

Environment Variables
^^^^^^^^^^^^^^^^^^^^^

AMZN Search API references the following environment variables:

======================== ========================================
variable                 description
======================== ========================================
AWS_ACCESS_KEY_ID        your AWS access key ID
AWS_SECRET_ACCESS_KEY    your AWS access key secret
AWS_ASSOCIATE_TAG_US     your AWS Associate tag for US region
AWS_ASSOCIATE_TAG_UK     your AWS Associate tag for UK region
======================== ========================================

To set an environment variable, e.g. MY_ENV, *do the following*:

.. code-block:: bash

    echo 'export MY_ENV=value' >> ~/.profile

Usage Examples
--------------

All resources live under the ``/api/v1`` prefix (they are also reachable at
``/<resource>/`` and ``/api/<resource>/``). Every response is JSON of the form
``{"status": <code>, "objects": <result>}``.

*Search for items by keyword*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?q=lego+millennium+falcon'

Accepts ``q`` (search term, required) plus optional ``condition``
(``New``/``Used``), ``region`` (``US``/``UK``), and ``limit``:

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/search/?q=guitar&condition=Used&region=UK&limit=5'

*Get a random "bacon ipsum" sentence (handy for testing)*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/lorem/'

*Delete a single cached url by base*

.. code-block:: bash

    curl 'http://localhost:5000/api/v1/delete/lorem/'

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
4. Use tabs **not** spaces
5. Add upstream ``git remote add upstream https://github.com/reubano/amzn-search-api.git``
6. Rebase ``git rebase upstream/master``
7. Test ``manage test``
8. Push ``git push origin master``
9. Submit a pull request

*Continuing*

1. Code (if you are having problems committing because of git pre-commit
   hook errors, just run ``manage check`` to see what the issues are.)
2. Use tabs **not** spaces
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

License
-------

AMZN Search API is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
