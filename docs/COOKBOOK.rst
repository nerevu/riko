riko Cookbook
=============

Index
-----

`User input`_ | `Alternate conf value entry`_

User input
----------

Some workflows require user input (via the ``pipeinput`` pipe). By default,
``pipeinput`` prompts the user via the console, but in some situations this may
not be appropriate, e.g., testing or integrating with a website. In such cases,
the input values can instead be read from the workflow's ``inputs`` kwarg (a
set of values passed into every pipe).

.. code-block:: python

    >>> from riko.modules.pipeinput import pipe
    >>> conf = {'prompt': 'How old are you?', 'type': 'int'}
    >>> pipe(conf=conf, inputs={'content': '30'}).next()
    {'content': 30}

Alternate ``conf`` value entry
------------------------------

Some workflows have ``conf`` values that are wired from other pipes

.. code-block:: python

    >>> from riko import get_url
    >>> from riko.modules.pipefetch import pipe
    >>>
    >>> conf = {'url': {'subkey': 'url'}}
    >>> result = pipe({'url': get_url('feed.xml')}, conf=conf)
    >>> set(next(result).keys()) == {
    ...     'updated', 'updated_parsed', 'pubDate', 'author', 'y:published',
    ...     'title', 'comments', 'summary', 'content', 'link', 'y:title',
    ...     'dc:creator', 'author.uri', 'author.name', 'id', 'y:id'}
    True
