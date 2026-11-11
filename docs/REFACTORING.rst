Refactoring Guidelines
======================

These guidelines help contributors choose between equivalent implementations: how to map
a callable over values, and how to declare an ``attrs`` field.

Mapping callables
-----------------

This section helps contributors choose between ``map()``, ``repeat()``,
``functools.partial()``, and generator expressions in performance-sensitive
Python code. Prefer correct behavior and clear code first. Use these rankings
to choose between otherwise equivalent implementations, especially in hot paths.

Benchmark conventions
~~~~~~~~~~~~~~~~~~~~~

The ratios below come from a CPython 3.12.13 (macOS arm64) microbenchmark using a cheap
arithmetic function. ``sm`` means 16 elements and ``lg`` means 1,000 elements. Lower is
faster, with ``map()`` plus ``repeat()`` normalized to ``1.0x``. Ratios are guidance,
not cross-platform guarantees. To reproduce them on your machine, run the
`timing benchmarks`_.

Single-use timings include helper construction (including ``partial()`` and
``repeat()``). **Reused** timings exclude the one-time callable construction or
definition, because the callable is created before the timed mapping operation.
Comparisons of total work over multiple batches should count that setup **once**. Small
differences can be benchmark noise. Profile representative code before making
performance-only changes.

The examples use the following functions and values:

.. code-block:: python

    >>> from functools import partial
    >>> from itertools import repeat
    >>> def arg_func(arg: int, kwarg: int = 1) -> int:
    ...     return arg * kwarg + 1
    ...
    >>> def kw_func(arg: int, *, kwarg: int = 1) -> int:
    ...     return arg * kwarg + 1
    ...
    >>> class Runner:
    ...     def run(self, arg: int, *, kwarg: int = 1) -> int:
    ...         return arg * kwarg + 1
    ...
    >>> runner = Runner()
    >>> arg, kwarg = 2, 3
    >>> arg_values = [2, 4, 6]       # iterable of first-argument values
    >>> kwarg_values = [3, 5, 7]     # iterable of second-argument values

``kw_func()`` and ``runner.run()`` require ``kwarg`` to be passed by keyword;
``arg_func()`` does not. ``tuple(...)`` is used to force evaluation for benchmarking.
**Keep the ``map`` or generator lazy** in streaming code unless materialization is
required.

Quick selection rules
~~~~~~~~~~~~~~~~~~~~~

* **Avoid unnecessary per-item overhead:** Prefer a `positional generator`_ or
  `keyword generator`_ over ``map()`` with lambdas or keyword-bound ``partial()`` when
  the function is cheap or very simple.
* **Fixed first argument:** a `leading repeat`_, ``map(func, repeat(fixed), values)``.
* **Multiple fixed arguments:** a `positional partial`_,
  ``map(partial(func, fixed), values)``.
* **Fixed second argument:** a `positional repeat`_,
  ``map(func, values, repeat(fixed))``.
* **Keyword-only fixed argument:** a `keyword generator`_,
  ``(func(value, kwarg=fixed) for value in values)``.
* **Reusable keyword-bound callable:** consider a `named closure`_. Do not add a
  wrapper just to chase speed.

Approved: fixed first argument
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _leading repeat:

``map`` + ``repeat`` (1.0x sm, 1.0x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when mapper accepts multiple iterables:

.. code-block:: python

    >>> tuple(map(arg_func, repeat(arg), kwarg_values))
    (7, 11, 15)

.. _positional partial:

``map`` + inline positional ``partial`` (1.2x sm, 1.1x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when several leading args are fixed, or the mapper accepts only one
iterable (e.g., ``multiprocessing.Pool.imap``):

.. code-block:: python

    >>> tuple(map(partial(arg_func, arg), kwarg_values))
    (7, 11, 15)

``map`` + bound positional ``partial`` (1.2x sm, 1.1x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when callable is reused (e.g., in a loop).
Reused: **1.1x sm, 1.1x lg**, excluding construction:

.. code-block:: python

    >>> bound_arg = partial(arg_func, arg)
    >>> tuple(map(bound_arg, kwarg_values))
    (7, 11, 15)
    >>> tuple(map(bound_arg, kwarg_values))  # reuse example
    (7, 11, 15)

A single-use named ``partial`` is not inherently faster than an inline one
when both measurements include construction.

Approved: fixed second argument
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. _positional repeat:

``map`` + ``repeat`` (1.0x sm, 1.0x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when ``kwarg`` can be passed positionally:

.. code-block:: python

    >>> tuple(map(arg_func, arg_values, repeat(kwarg)))
    (7, 13, 19)

.. _positional generator:

Positional generator expression (1.2x sm, 1.2x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when readability matters more than performance:

.. code-block:: python

    >>> tuple(arg_func(item, kwarg) for item in arg_values)
    (7, 13, 19)

.. _keyword generator:

Keyword generator expression (1.3x sm, 1.4x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when ``kwarg`` must be passed by keyword:

.. code-block:: python

    >>> tuple(kw_func(item, kwarg=kwarg) for item in arg_values)
    (7, 13, 19)

.. _named closure:

``map`` + named closure (1.4x sm, 1.4x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Preferred when callable is reused (e.g., in a loop), or more complex logic is needed.
Reused: **1.3x sm, 1.4x lg**, excluding definition:

.. code-block:: python

    >>> def bound_kwarg(item: int) -> int:
    ...     return kw_func(item, kwarg=kwarg)
    ...
    >>> tuple(map(bound_kwarg, arg_values))
    (7, 13, 19)

Disapproved for performance-oriented mapping
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``map`` + lambda args (1.2x sm, 1.3x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Prefer the `positional repeat`_ instead:

.. code-block:: python

    >>> tuple(map(lambda item: arg_func(item, kwarg), arg_values))
    (7, 13, 19)

``map`` + lambda kwarg (1.4x sm, 1.4x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Prefer the `keyword generator`_ instead:

.. code-block:: python

    >>> tuple(map(lambda item: kw_func(item, kwarg=kwarg), arg_values))
    (7, 13, 19)

``map`` + inline keyword ``partial`` (2.2x sm, 2.2x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Prefer the `keyword generator`_ instead:

.. code-block:: python

    >>> tuple(map(partial(kw_func, kwarg=kwarg), arg_values))
    (7, 13, 19)

``map`` + keyword-argument ``partial`` (2.2x sm, 2.2x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Prefer a `named closure`_ instead.
Reused: **2.1x sm, 2.2x lg**, excluding construction:

.. code-block:: python

    >>> bound_kwarg_partial = partial(kw_func, kwarg=kwarg)
    >>> tuple(map(bound_kwarg_partial, arg_values))
    (7, 13, 19)

``map`` + bound-method keyword ``partial`` (2.3x sm, 2.3x lg)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Prefer the `keyword generator`_ when mapping, or a `named closure`_ when an API needs a
single-argument callable:

.. code-block:: python

    >>> tuple(map(partial(runner.run, kwarg=kwarg), arg_values))
    (7, 13, 19)

Correctness and refactoring checks
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **Preserve call signatures.** A keyword-only parameter cannot be converted into a
  positional argument merely to use ``repeat()``.
* **Preserve binding time.** ``partial(func, arg)`` captures the function and argument
  objects at construction. A named wrapper referencing outer names may observe later
  reassignment of those names. Do not interchange them without checking the intended
  behavior.
* **Preserve callable identity and reuse.** Do not inline a stored, registered, cached,
  or repeatedly used ``partial`` if distinct instances would alter lifecycle or identity
  behavior.
* **Preserve evaluation order and laziness.** ``map()`` stops at the shortest input
  iterable. An unbounded ``repeat()`` is safe alongside a finite input. Avoid inserting
  ``tuple()`` into a live streaming pipeline just to match the benchmark examples.
* **Respect mapper APIs.** Built-in ``map()`` accepts multiple iterables.
  ``multiprocessing.Pool.imap()`` accepts one. For multiprocessing, use picklable
  callables and arguments. A top-level function bound by ``partial`` is often more
  appropriate than a local closure.
* **Rank only per-item callables.** The rankings cover a callable invoked once per
  mapped item. A callable invoked once per call or once per group (a group reducer, a
  one-time setup call) gains nothing from switching forms; what matters there is the
  per-item work inside it. Read a config attribute, a bound method, or any other lookup
  that is constant for the whole mapping into a local once, before the loop or closure,
  instead of repeating it per item.
* **Benchmark the actual lifecycle.** Include setup for one-off operations, amortize it
  for reused callables, and use representative batch sizes and functions. A much more
  expensive ``func`` can make these relative differences insignificant.

These are **performance preferences**, not a requirement to rewrite clear, correct code
without evidence of a bottleneck.

Declaring ``attrs`` fields
--------------------------

Shape each field by answering two questions: who supplies its value, and who reads it.

Quick selection rules
~~~~~~~~~~~~~~~~~~~~~

* **Callers supply it and read it:** a plain field, ``name: str``.
* **Callers read it, but only the class's own methods set it:** a public attribute with a
  private constructor keyword, ``inputs: T = field(alias="_inputs")``.
* **Only the instance reads and sets it:** a private attribute nobody supplies,
  ``_closing: bool = field(default=False, init=False)``.
* **Computed from other fields:** a ``cached_property``, not a field.
* **Avoid** naming the field itself ``_inputs``. ``attrs`` strips the underscore from
  the constructor keyword, so the attribute becomes private while ``inputs=`` stays
  public. That is the inverse of the alias.

The examples use these imports:

.. code-block:: python

    >>> from functools import cached_property
    >>> from attrs import define, evolve, field

Public attribute, private keyword
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``alias="_x"`` when the value must agree with the rest of the instance, so only a
method that keeps them in step may set it. Readers still use ``plan.inputs``, and the
method sets it through ``evolve(..., _inputs=...)``. The underscore keyword tells
callers not to pass it:

.. code-block:: python

    >>> @define(frozen=True)
    ... class Plan:
    ...     query: str
    ...     inputs: dict[str, int] | None = field(default=None, alias="_inputs")
    ...
    ...     def with_inputs(self, values: dict[str, int]) -> "Plan":
    ...         query = self.query.format(**values)
    ...         return evolve(self, query=query, _inputs=values)
    ...
    >>> plan = Plan("limit {q}").with_inputs({"q": 2})
    >>> plan.query, plan.inputs
    ('limit 2', {'q': 2})
    >>> Plan("limit {q}", inputs={"q": 2})
    Traceback (most recent call last):
    TypeError: Plan.__init__() got an unexpected keyword argument 'inputs'...

Avoid: private attribute, public keyword
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A field named ``_inputs`` gets the constructor keyword ``inputs``. Any caller can then
set the value without the method that keeps it in step, and readers need a property to
reach it:

.. code-block:: python

    >>> @define(frozen=True)
    ... class Inverted:
    ...     query: str
    ...     _inputs: dict[str, int] | None = None
    ...
    >>> Inverted("limit {q}", inputs={"q": 2})._inputs
    {'q': 2}

Private state nobody supplies
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use ``init=False`` for an instance's own working state, such as a session's closing flag.
``evolve`` does not carry an ``init=False`` field. The copy gets the default again, so
keep these fields off frozen definitions that are derived with ``evolve``:

.. code-block:: python

    >>> @define
    ... class Session:
    ...     name: str
    ...     _closing: bool = field(default=False, init=False)
    ...
    ...     def close(self) -> None:
    ...         self._closing = True
    ...
    >>> session = Session("a")
    >>> session.close()
    >>> session._closing, evolve(session, name="b")._closing
    (True, False)

Derived values
~~~~~~~~~~~~~~

Store what an instance is built from and derive the rest. A ``cached_property`` cannot
drift from the fields it reads, and no caller can supply a conflicting value:

.. code-block:: python

    >>> @define(frozen=True)
    ... class Report:
    ...     title: str
    ...
    ...     @cached_property
    ...     def slug(self) -> str:
    ...         return self.title.lower().replace(" ", "-")
    ...
    >>> Report("Daily Rates").slug
    'daily-rates'

.. _timing benchmarks: ../benchmarks/func_benchmarks.py
