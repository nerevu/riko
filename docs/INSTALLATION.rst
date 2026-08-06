Installing riko
===============

``riko`` is a pure Python package. It has been tested and is known to work on
Python 3.12, 3.13, and 3.14.

The published PyPI release may lag the ``features`` branch. ``pip install riko``
installs the published release; install from the branch when you need the APIs
described by the current repository documentation.

Create an isolated environment
------------------------------

(You are using a `virtualenv`_, right?) An isolated environment avoids conflicts
with system packages. With the standard library ``venv`` module:

.. code-block:: bash

    python3.12 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip

On Windows PowerShell, activate the environment with:

.. code-block:: powershell

    py -3.12 -m venv .venv
    .venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip

Install riko
------------

At the command line, install the latest release available on PyPI:

.. code-block:: bash

    pip install riko

Confirm which release was installed:

.. code-block:: bash

    python -c "import riko; print(riko.__version__)"

If that version is older than the version shown in ``pyproject.toml``, the
repository documentation may describe APIs that have not yet been published.

Optional dependencies
---------------------

``riko`` installs a slim core by default. Install only the optional ``extras``
your application needs (quote the brackets so your shell doesn't interpret them).

========================  ==================  =============================
Feature                   Dependency          Installation
========================  ==================  =============================
Async API                 `AnyIO`_, `httpx`_  ``pip install "riko[async]"``
Accelerated xml parsing   `lxml`_             ``pip install "riko[perf]"``
Accelerated feed parsing  `fastfeedparser`_   ``pip install "riko[perf]"``
Streaming json parsing    ``ijson``           ``pip install "riko[perf]"``
OFX/QIF export            csv2ofx             ``pip install "riko[finance]"``
========================  ==================  =============================

- ``async`` enables the ``AsyncPipe`` and ``AsyncCollection`` APIs.
- ``perf`` enables accelerated / streaming parser paths; without ``lxml``, ``riko``
  falls back to the builtin Python xml parser; without ``fastfeedparser`` it falls back
  to `feedparser`_.
- ``finance`` enables the ``ofx`` and ``qif`` export targets; without it
  ``list_targets()`` won't include them.

Install several groups together:

.. code-block:: bash

    pip install "riko[async,perf,finance]"

Install for development with uv
-------------------------------

``riko`` uses `uv`_ for its locked development environment. A single
``uv sync`` from a checkout creates ``.venv``, installs ``riko`` in editable
mode, and pulls in the dev dependencies and every extra:

.. code-block:: bash

    uv sync --group dev --all-extras

``riko``'s ``[tool.uv]`` ``cache-keys`` config rebuilds the local install
whenever a ``riko/`` source file changes, so there's no separate editable
reinstall step. Run project commands with ``uv run`` (it re-syncs first, picking
up any source edits):

.. code-block:: bash

    uv run manage test --no-cov
    uv run manage lint

See the `contributing guide`_ for focused tests, type checks, tox, pre-commit,
and module-development conventions.

Verify the installation
-----------------------

A self-contained ``flow`` confirms that the package imports and basic module
chaining work:

.. code-block:: python

    >>> from riko import SyncPipe
    >>>
    >>> conf = {'attrs': {'key': 'content', 'value': 'a'}}
    >>> next(SyncPipe('itembuilder', conf=conf).count())
    {'count': 1}

For the asynchronous API, first install the ``async`` extra, then use
``AsyncPipe`` with ``async for`` or ``await`` as shown in the `cookbook`_.

Troubleshooting
---------------

Unsupported Python version
^^^^^^^^^^^^^^^^^^^^^^^^^^

``riko`` requires Python 3.12 or newer. Check the interpreter used by ``pip``
rather than assuming the ``python`` and ``pip`` commands point to the same
environment:

.. code-block:: bash

    python --version
    python -m pip --version

Source edits are not taking effect
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In the uv development environment, ``uv sync`` (and every ``uv run``) rebuilds
the local install when a ``riko/`` source file changes, thanks to the
repository's ``cache-keys`` config. Re-sync to force it:

.. code-block:: bash

    uv sync --group dev --all-extras

Missing optional dependency
^^^^^^^^^^^^^^^^^^^^^^^^^^^

Install the relevant ``extra`` rather than adding individual dependencies
manually, e.g.:

.. code-block:: bash

    pip install "riko[async]"

When reporting an installation problem, include the Python version, operating
system, complete command, package version, and full error output in the
`issue tracker`_.

Uninstall
---------

Remove ``riko`` from the active environment with:

.. code-block:: bash

    pip uninstall riko

.. _virtualenv: https://virtualenv.pypa.io/en/latest/index.html
.. _uv: https://docs.astral.sh/uv/
.. _AnyIO: https://anyio.readthedocs.io/
.. _httpx: https://www.python-httpx.org/
.. _fastfeedparser: https://github.com/kagisearch/fastfeedparser
.. _feedparser: https://feedparser.readthedocs.io/
.. _lxml: https://lxml.de/
.. _contributing guide: ../CONTRIBUTING.rst
.. _cookbook: COOKBOOK.rst
.. _issue tracker: https://github.com/nerevu/riko/issues
