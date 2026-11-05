.. source: ../../../../meetup/README.rst

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
``changed``   Get members whose contact info changed since a prior meetup,
              i.e. since their earlier rows in the file
``ver``       Show the ``meetup`` version (intended; ``meetup ver`` is not a
              command today, see `Known issues`_)
============  =================================================================

"New" and "changed" are decided from the order of the rows in the file; see
`How new and changed are decided`_.

Input / output
--------------

**Input** is a CSV of attendees with the columns::

    Date, First Name, Last Name, E-mail Address, Phone, Organization

The rows must be in chronological order (earliest meetup first). Header names are
lowercased and underscored on read (``E-mail Address`` becomes ``e_mail_address``),
and other columns are not used to select rows.

**Output** is a vCard written to the destination file (or STDOUT). Records are
de-duplicated, and phone numbers beginning with ``0`` (or lacking a ``+``) are
converted to international format using the country ``--code``.

* A leading ``0`` is replaced by ``+<code>`` (``0755123456`` becomes
  ``+255755123456``); any other number without a leading ``+`` gets ``+<code>`` prepended.
  Blank phone numbers stay blank.
* vCards are built by ``pyconvert`` (``pyconvert.io.to_vcard``). ``phone`` and
  ``changed`` put every contact in the vCard group (``CATEGORIES``) ``Arusha Coders``,
  which is hardcoded in ``meetup/main.py``; ``email`` sets no group.
* With ``--dry-run`` nothing is written to ``dest``; the selected values are printed to
  STDOUT on one line instead (``New emails: a@x.com, b@y.com``,
  ``New phone numbers: ...`` or ``Modified contacts: ...``).

How new and changed are decided
-------------------------------

A row belongs to the meetup when its ``Date`` and ``--date`` parse (with
``python-dateutil``) to exactly the same date and time, so ``9/2/15`` is
2 September 2015, and a ``--date`` with a time of day matches only rows with that same
time.

``email``
    Keeps the first row for each email address, in file order, then the rows on
    ``--date``. An email address is new if its first row is on that date.

``phone``
    Cleans the phone numbers, keeps the first row for each number, then the rows on
    ``--date``. A number is new if its first row is on that date, so an existing member
    who brings a new number is included.

``changed``
    Cleans the phone numbers and builds a contact key from the first name, last name,
    email, phone and organization: the non-blank values joined without separators,
    lowercased, with spaces removed, then hashed with MD5. Keeps the first row for each
    key, in file order, then the rows on ``--date``, grouped (and sorted) by email
    address. So a row on ``--date`` is selected when that exact contact combination never
    appeared in an earlier row. There is no separate "prior meetup" option: every earlier
    row in the file counts.

    Members whose email address is new on ``--date`` are meant to be left out
    (intended); today they are included too (see `Known issues`_).

Requirements
------------

* Python 2.7
* `tabutils <https://github.com/reubano/tabutils>`_, ``pyconvert``, ``manage.py``,
  ``python-dateutil``

``meetup`` needs tabutils 0.18.0 or later (``process.group`` and
``process.unique(pred=...)`` first appear there). tabutils is now published as
`meza <https://github.com/reubano/meza>`_. ``python-dateutil`` is installed as a tabutils
dependency.

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
``-d, --date``          the meetup date to use (defaults to the 1st Wednesday of the month,
                        computed when ``meetup`` starts)
``-c, --code``          the phone country code (default ``255``)
``-r, --dry-run``       print results instead of writing a vCard (a flag; takes no value)
``-h, --help``          show help and exit
======================  ===============================================================

Every command (``email``, ``phone``, ``changed``) takes the same options.

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

Known issues
------------

* ``changed`` never leaves out new members. ``get_modded`` reads ``source`` twice
  (``meetup/main.py:89`` and ``:96``). The first pass is consumed in full when the rows
  are grouped (tabutils' ``group`` sorts its input), and tabutils does not rewind a file
  object, so the second pass, which finds the new email addresses, reads nothing. This
  happens for a file argument and for STDIN alike.
* ``meetup ver`` is not a command. ``ver`` is registered on the ``Manager`` in
  ``meetup/__init__.py:25,91-94``, but ``bin/meetup`` runs ``meetup.main.manager``, a
  different ``Manager``. The version is ``__version__`` in ``meetup/__init__.py``.
* ``changed`` crashes with ``TypeError`` on a row whose first name, last name, email,
  phone and organization are all blank (``reduce`` over an empty list,
  ``meetup/main.py:61``).

License
-------

meetup is distributed under the `MIT License <http://opensource.org/licenses/MIT>`_.
