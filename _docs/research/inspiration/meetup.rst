meetup
======

Introduction
------------

``meetup`` is a command-line tool for administering a `Meetup <https://www.meetup.com>`_
group. Given a CSV export of meetup attendees, it extracts new or changed member
contacts for a given meetup date and writes them out as `vCards <https://en.wikipedia.org/wiki/VCard>`_
(handy for importing into a contact manager or mailing list). Phone numbers are
normalized with an international country code.

It was built to manage the *Arusha Coders* group (Tanzania, country code ``255``).

Commands
--------

============  =================================================================
command       description
============  =================================================================
``email``     Get email addresses of new members (output as vCard)
``phone``     Get phone numbers of new members (output as vCard)
``changed``   Get members whose contact info changed since a prior meetup
``ver``       Show the ``meetup`` version
============  =================================================================

Input / output
--------------

**Input** is a CSV of attendees with the columns::

    Date, First Name, Last Name, E-mail Address, Phone, Organization

**Output** is a vCard written to the destination file (or STDOUT). Records are
de-duplicated, and phone numbers beginning with ``0`` (or lacking a ``+``) are
converted to international format using the country ``--code``.

Requirements
------------

* Python 2.7
* `tabutils <https://github.com/reubano/tabutils>`_, ``pyconvert``, ``manage.py``,
  ``python-dateutil``

Installation
------------

*Development install*

.. code-block:: bash

    git clone https://github.com/reubano/meetup.git
    cd ./meetup
    virtualenv .env && source .env/bin/activate
    pip install -e .

Usage
-----

.. code-block:: bash

    meetup <command> [source] [dest] [options]

``source`` defaults to STDIN and ``dest`` defaults to STDOUT, so commands can be piped.

Options
^^^^^^^

======================  ===============================================================
option                  description
======================  ===============================================================
``-d, --date``          the meetup date to use (defaults to the 1st Wednesday of the month)
``-c, --code``          the phone country code (default ``255``)
``-r, --dry-run``       print results instead of writing a vCard
``-h, --help``          show help and exit
======================  ===============================================================

Examples
^^^^^^^^

*Show help*

.. code-block:: bash

    meetup -h

*Export new members' emails from a meetup on a given date to a vCard file*

.. code-block:: bash

    meetup email attendees.csv new_members.vcf --date 9/2/15

*Preview new phone numbers without writing a file*

.. code-block:: bash

    meetup phone attendees.csv --date 9/2/15 --dry-run

*Pipe input from STDIN and write the vCard to STDOUT*

.. code-block:: bash

    cat attendees.csv | meetup changed -d 9/2/15 > changed.vcf

*Use a different country code*

.. code-block:: bash

    meetup phone attendees.csv contacts.vcf --code 1

Development
-----------

``manage.py`` (using ``manager``) provides dev tasks:

.. code-block:: bash

    python manage.py test      # run nose + script tests
    python manage.py lint      # flake8
    python manage.py tox       # test across Python versions
    python manage.py coverage  # coverage report

License
-------

meetup is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
