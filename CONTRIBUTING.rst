============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

When contributing, please mimic the coding style/conventions used in this repo.
If you add new classes or functions, please add the appropriate doc blocks with
examples. Also, make sure the python linter and tests pass.

Ready to contribute? Here's how.

Types of Contributions
----------------------

Feedback & Bug Reports
~~~~~~~~~~~~~~~~~~~~~~

The best way to send feedback or report a bug is to file an issue at
https://github.com/nerevu/riko/issues.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Bug Fixes
~~~~~~~~~

Look through the GitHub `issues`_ for anything tagged with ``bug`` and hack away.

Feature Implementation
~~~~~~~~~~~~~~~~~~~~~~

Look through the GitHub `issues`_ for anything tagged with ``feature`` and hack away.

If you are *proposing* a feature:

* Explain in detail how it would work.
* To make it easier to implement, Keep the scope as narrow as possible.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

Documentation
~~~~~~~~~~~~~

riko could always use more documentation, whether as part of the
official docs, in docstrings, or even on the web in blog posts, articles, and such.
Feel free to contribute any type of documentation.

Get Started!
------------

Ready to contribute? Here's how to set up ``riko`` for local development.

1. Fork the ``riko`` repo on GitHub and clone

.. code-block:: bash

    git clone git@github.com:<your_username>/riko.git
    cd riko

2. Setup a new `virtualenv`_ with ``virtualenvwrapper``

.. code-block:: bash

    mkvirtualenv --no-site-packages riko

Or, if you only have ``virtualenv`` installed

.. code-block:: bash

    virtualenv --no-site-packages ~/.venvs/riko
    source ~/.venvs/riko/bin/activate

3. Install required modules

Python3

.. code-block:: bash

    pip install -r dev-requirements.txt
    pip install -r optional-requirements.txt
    pip install -r requirements.txt

Python2

.. code-block:: bash

    pip install -r dev-requirements.txt
    pip install -r optional-requirements.txt
    pip install -r py2-requirements.txt

4. Run setup develop script

.. code-block:: bash

    python setup.py develop

5. Create a branch for local development

.. code-block:: bash

    git checkout -b name-of-your-bugfix-or-feature

6. Make your changes and run linter and tests

.. code-block:: bash

    manage lint
    manage test

    # or to run the full integration tests
    tox

5. Commit your changes and push your branch to GitHub

.. code-block:: bash

    git add .
    git commit -m "Your detailed description of your changes."
    git push origin name-of-your-bugfix-or-feature

6. Submit a pull request on the riko `repo`_.

Pull Request Guidelines
-----------------------

Before you submit a pull request, check that it meets these guidelines:

1. The pull request includes tests.
2. If the pull request adds functionality, the docs should be updated: Put
   your new functionality into a function with a docstring, and add the
   feature to the list in README.rst.

.. _issues: https://github.com/nerevu/riko/issues
.. _repo: https://github.com/nerevu/riko
.. _virtualenv: https://virtualenv.pypa.io/en/latest/index.html
