Installation
------------

(You are using a `virtualenv`_, right?)

At the command line, install riko using either ``pip`` (recommended)

.. code-block:: bash

    pip install riko

or ``easy_install``

.. code-block:: bash

    easy_install riko

Detailed installation instructions
----------------------------------

If you have `virtualenvwrapper`_ installed, at the command line type:

.. code-block:: bash

    mkvirtualenv riko
    pip install riko

Or, if you only have ``virtualenv`` installed:

.. code-block:: bash

	virtualenv ~/.venvs/riko
	source ~/.venvs/riko/bin/activate
	pip install riko

Otherwise, you can install globally::

    pip install riko

.. _virtualenv: https://virtualenv.pypa.io/en/latest/index.html
.. _virtualenvwrapper: https://virtualenvwrapper.readthedocs.org/en/latest/
