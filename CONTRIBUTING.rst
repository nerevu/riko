============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every
little bit helps, and credit will always be given.

When contributing, please mimic the coding style/conventions used in this repo.
If you add new classes or functions, please add the appropriate doc blocks with
examples. Also, make sure the python linter and nose tests pass.

Ready to contribute? Here's how.

Types of Contributions
----------------------

Report Bugs
~~~~~~~~~~~

Report bugs at https://github.com/reubano/riko/issues.

If you are reporting a bug, please include:

* Your operating system name and version.
* Any details about your local setup that might be helpful in troubleshooting.
* Detailed steps to reproduce the bug.

Fix Bugs
~~~~~~~~

Look through the GitHub `issues`_ for anything tagged with ``bug`` and hack away.

Implement Features
~~~~~~~~~~~~~~~~~~

Look through the GitHub `issues`_ for anything tagged with ``feature`` and hack away.

Write Documentation
~~~~~~~~~~~~~~~~~~~

riko could always use more documentation, whether as part of the
official docs, in docstrings, or even on the web in blog posts, articles, and such.
Feel free to contribute any type of documentation.

Submit Feedback
~~~~~~~~~~~~~~~

The best way to send feedback is to file an issue at https://github.com/reubano/riko/issues.

If you are proposing a feature:

* Explain in detail how it would work.
* To make it easier to implement, Keep the scope as narrow as possible.
* Remember that this is a volunteer-driven project, and that contributions
  are welcome :)

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
    pip install -r dev-requirements.txt
    pip install -r optional-requirements.txt
    python setup.py develop

Or, if you only have ``virtualenv`` installed

.. code-block:: bash

    virtualenv --no-site-packages ~/.venvs/riko
    source ~/.venvs/riko/bin/activate
    pip install -r dev-requirements.txt
    pip install -r optional-requirements.txt
    python setup.py develop

3. Create a branch for local development

.. code-block:: bash

    git checkout -b name-of-your-bugfix-or-feature

4. Make your changes and run linter and tests

.. code-block:: bash

    manage lint
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

.. _issues: https://github.com/reubano/riko/issues
.. _repo: https://github.com/reubano/riko
.. _virtualenv: https://virtualenv.pypa.io/en/latest/index.html
