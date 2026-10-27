============
Contributing
============

Contributions are welcome, and they are greatly appreciated! Every little bit
helps, and credit will always be given. ``riko`` is a volunteer-maintained
project, so focused issues and pull requests are easier to review than broad
rewrites or bundles of unrelated changes.

These instructions describe the current ``features`` branch. That branch uses
Python 3.12 or newer, `uv`_ for dependency management, ``pytest`` for tests and
doctests, ``ruff`` for formatting and linting, ``pyright`` for type checking, and
``tox`` for the supported-version matrix.

Types of contributions
-----------------------

Start with an `issue`_ for bug reports, feature proposals, documentation
problems, and questions that require repository changes. Search existing issues
first.

Feedback & bug reports
^^^^^^^^^^^^^^^^^^^^^^^

A useful bug report includes:

* the ``riko`` version or commit;
* the Python version and operating system;
* the installation command and optional ``extras`` used;
* a minimal input and pipeline that reproduce the problem;
* the expected and actual behavior; and
* the complete traceback or relevant command output.

Remove credentials, tokens, private URLs, and sensitive data before posting.

Feature proposals
^^^^^^^^^^^^^^^^^

Explain the problem before proposing an API. Describe why existing ``modules`` or
ordinary Python composition are insufficient, and keep the initial scope narrow.
Large changes should be discussed before substantial implementation work begins.
Remember that this is a volunteer-driven project, and that contributions are
welcome :)

Documentation
^^^^^^^^^^^^^

``riko`` could always use more documentation, whether as part of the official
docs, in docstrings, or even on the web in blog posts, articles, and such. Feel
free to contribute any type of documentation.

Development setup
-----------------

Prerequisites
^^^^^^^^^^^^^

Install:

- Git;
- CPython 3.12, 3.13, or 3.14; and
- `uv`_.

The test matrix covers all three supported CPython versions. Using one version
locally is sufficient for normal development; run ``tox`` before requesting
review when a change could be version-specific.

The complete ``manage lint --all`` suite also invokes ``actionlint``,
``shellcheck``, and ``yamlfmt`` for workflow and YAML checks. CI installs those
tools automatically; install them locally if you want to run the complete lint
bundle before pushing.

Fork and clone
^^^^^^^^^^^^^^

Fork the repository, clone your fork, and add the upstream repository:

.. code-block:: bash

    git clone https://github.com/<your-username>/riko.git
    cd riko
    git remote add upstream https://github.com/nerevu/riko.git
    git fetch upstream

The documentation and APIs described here target ``features``. Start a focused
branch from the current upstream branch unless an issue or maintainer specifies
a different target:

.. code-block:: bash

    git switch -c your-change upstream/features

Install the development environment
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Install development dependencies and all optional feature groups. A single
``uv sync`` creates ``.venv`` and installs ``riko`` in editable mode:

.. code-block:: bash

    uv sync --group dev --all-extras

The repository's ``[tool.uv]`` ``cache-keys`` config rebuilds the local install
whenever a ``riko/`` source file changes, so no separate editable reinstall is
needed. Verify the environment:

.. code-block:: bash

    uv run python -c "import riko; print(riko.__version__)"
    uv run manage help

``manage`` is the preferred contributor interface for repository maintenance
commands. Run ``uv run manage help`` to list commands and ``uv run manage
<command> --help`` for command-specific options.

Manage command reference
------------------------

The common development commands are:

``manage test``
    - Runs pytest (or tox with ``--tox``).
    - Takes paths positionally or with repeatable ``--where``.
    - Uses ``--no-cov`` for faster focused runs.
    - ``--ratchet`` runs the whole suite and fails when it leaves more statements
      uncovered than the ceiling recorded in ``pyproject.toml``
      (``[tool.riko.coverage]``), and lowers the ceiling when it leaves fewer.
    - ``--ratchet`` refuses paths, ``--tox``, and ``--failed``, and measures coverage
      even with ``--no-cov``.

``manage prettify``
    - Sorts imports, applies Ruff fixes, and formats Python.
    - Limits the scope with ``--where``.
    - Formats YAML instead with ``--yaml``.

``manage check``
    - Runs Ruff checks against staged Python files.
    - Is a fast pre-commit check, not a replacement for the full lint suite.

``manage lint``
    - Runs Ruff lint plus ``ruff format --check`` by default.
    - Selects standard checks additively:

      - ``--rst``, ``--docs``, ``--actions``, ``--yaml``, and ``--docstrings``.
      - ``--terms``: phrases the reserved-terms rules replace, internal phase codes,
        and the same phrases in the internal design notes.
      - ``--literals``: single-quoted values, and backticked or unquoted string
        defaults.
      - ``--deps``: missing, unused, and misplaced dependency checks, required
        dependencies imported only under ``TYPE_CHECKING``, optional extras imported
        outside a ``try`` that catches ``ImportError``, and pre-commit pins that differ
        from ``uv.lock``.
      - ``--bindings``: a ``Workflow`` bound to ``workflow`` rather than ``flow`` in
        code or doctests.
      - ``--tests``: stale generated tier indexes, tests outside a ``Test<Subject>``
        class, a subject owned by two files, and misplaced files.
      - ``--basenames``: two package modules sharing a file name.

    - Runs all standard checks, including all import-contract ones, with ``--all``.
    - Keeps type completeness, strict pylint, and distribution checks explicit via
      ``--check-types``, ``--verify-types``, ``--strict``, and ``--dist``.

``manage lint imports``
    - Checks internal import contracts.
    - Runs the canonical-import check when no selector is given.
    - Takes ``--canonical``, ``--relative``, and ``--architecture`` additively, or
      ``--all`` for all three.

``manage upgrade``
    - Upgrades every locked dependency to the newest version ``pyproject.toml`` allows
      (and at least a week old), then syncs the active environment to the new lock.
    - Upgrades only named packages with repeatable ``--package``.
    - Updates ``uv.lock`` alone with ``--no-sync``.
    - Skips with ``--daily`` when a full upgrade already succeeded today.
    - CI installs exactly what ``uv.lock`` pins and never upgrades, so commit the
      updated lock with the change it was tested against.

``manage codegen``
    - Regenerates derived repository artifacts.
    - Regenerates configuration types when no selector is given.
    - Takes ``--config``, ``--names``, ``--api``, ``--tests``, and ``--verbs``
      additively, or ``--all`` for every generator.

Daily development workflow
--------------------------

Use the narrowest feedback loop while implementing a change. Run a focused test
for the behavior you are changing:

.. code-block:: bash

    uv run manage test --no-cov tests/public/test_pipeline.py

Run documentation doctests directly when changing user-facing examples:

.. code-block:: bash

    uv run manage test --no-cov README.rst docs/COOKBOOK.rst docs/FAQ.rst

If the change modifies generator inputs, regenerate the affected artifacts before
formatting or testing them. Selectors are additive, so regenerate only what the
change owns:

.. code-block:: bash

    uv run manage codegen --config --names

Use ``manage codegen --all`` when a change spans several generated surfaces or
when doing an explicit full regeneration pass.

Preferred validation sequence
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Before requesting review, use this order. It keeps generated files current before
formatting, proves the changed behavior with a narrow test first, then widens to
the repository-wide checks:

1. Upgrade locked dependencies, so new tool releases surface locally rather
   than in CI.

   .. code-block:: bash

       uv run manage upgrade --daily

2. Regenerate any affected artifacts.

   .. code-block:: bash

       uv run manage codegen --config

   Choose the relevant ``--config``, ``--names``, and ``--api``
   selectors, or use ``--all`` when appropriate. Skip this step when no generated
   input changed.

3. Format the changed code (and YAML, when applicable).

   .. code-block:: bash

       uv run manage prettify
       uv run manage prettify --yaml

4. Run focused tests for the behavior being changed.

   .. code-block:: bash

       uv run manage test --no-cov tests/path/to/test_file.py

5. Run the complete local test suite with the coverage ratchet. Keep any
   lowered ceiling in ``pyproject.toml`` as part of the change.

   .. code-block:: bash

       uv run manage test --ratchet

6. Run the standard repository lint bundle.

   .. code-block:: bash

       uv run manage lint --all

7. Run both type-checking passes explicitly.

   .. code-block:: bash

       uv run manage lint --check-types
       uv run manage lint --verify-types

8. Run the supported-version matrix when the change affects packaging,
   dependencies, typing, async behavior, or interpreter-specific code.

   .. code-block:: bash

       uvx tox run

Steps 5--7 match the core test/lint/type checks used by CI. ``manage lint --all``
intentionally does not include the type checks, strict pylint, or distribution
checks, so keep the two pyright commands explicit.

Pre-commit hooks are optional but useful:

.. code-block:: bash

    uv run pre-commit install
    uv run pre-commit run --all-files

Tests and documentation
-----------------------

Behavior changes should include tests. Regression tests should fail before the
fix and pass after it. Prefer the narrowest test layer that proves the contract:

- public tests for supported API behavior;
- functional tests for end-to-end workflows;
- internal tests for implementation details; and
- doctests for concise, stable examples that belong in user documentation or
  docstrings.

Doctests are collected from ``README.rst``, files under ``docs/``, package
modules, and the test suite. Examples must be deterministic, network-independent
where practical (use ``get_path`` to read bundled fixtures offline), and concise
enough to remain readable.

When behavior changes, update the README, cookbook, FAQ, module docstring, or DAG
reference that users rely on. Do not document an API until the implementation and
tests support it.

Code and API conventions
------------------------

Please mimic the coding style/conventions used in this repo. If you add new
classes or functions, please add the appropriate docstrings with examples.
Docstrings, doctests, and ``__init__.py`` files follow the repository
documentation standard (``_docs/DOCUMENTATION_STANDARD.md``): annotations own
types, documentation audience follows the STABLE/EXTENSION/PRIVATE tiers, and
doctests show real returned values.

- Import application APIs from ``riko``.
- Import supported module-authoring decorators and protocols from ``riko.ext``.
- Treat underscore-prefixed modules and implementation details as private.
- Preserve sync and async output parity when a module exposes both ``pipe`` and
  ``async_pipe``.
- Keep pipelines single-use and iterator semantics explicit.
- Add type annotations for new public and extension-facing code.
- Let ``ruff`` format code instead of hand-tuning style around the formatter.
- Avoid unrelated formatting, renaming, or cleanup in a focused pull request.

Function names
^^^^^^^^^^^^^^

Name a function by what it does. When choosing among the general-purpose verbs
below, work down the table and take the first verb whose rule fits; its docstring
summary then starts with that verb's word:

.. begin verbs

+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| Verb          | Summary     | Meaning                | Raises                   | Returns              | Rule                           | Example                |
|               | starts with |                        |                          |                      |                                |                        |
+===============+=============+========================+==========================+======================+================================+========================+
| ``load``      | Loads       | Acquire through an     | Acquisition failure      | The acquired data or | **MUST** cross an acquisition  | ``load_settings``      |
|               |             | external, ambient, or  | normally surfaces        | state                | boundary                       |                        |
|               |             | provider boundary      |                          |                      |                                |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``validate``  | Validates   | Check a contract       | **MUST** raise for an    | ``None``             | **MUST NOT** transform or      | ``Workflow.validate``  |
|               |             |                        | invalid value            |                      | return a replacement value;    |                        |
|               |             |                        |                          |                      | observationally idempotent     |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``require``   | Requires    | Enforce that a         | **MUST** raise when the  | The value, narrowed  | **MUST NOT** silently default, | ``require_str``        |
|               |             | required value,        | requirement fails        | to a usable form;    | repair, or substitute; **MAY** |                        |
|               |             | object, or             |                          | ``None`` for a       | use lookup or context          |                        |
|               |             | precondition exists    |                          | precondition         |                                |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``resolve``   | Resolves    | Determine the          | **MUST NOT** treat a     | The effective value, | **MUST** involve reference,    | ``resolve_format``     |
|               |             | effective value from a | missing match as an      | possibly a fallback  | context, fallback, or          |                        |
|               |             | reference, context,    | error when a fallback is |                      | precedence; chooses what       |                        |
|               |             | fallback, or           | part of the contract;    |                      | applies rather than            |                        |
|               |             | precedence             | **MAY** raise for        |                      | canonicalizing the input       |                        |
|               |             |                        | invalid input            |                      |                                |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``parse``     | Parses      | Turn a representation  | **MUST** raise for       | A semantic structure | **MUST NOT** use resolution    | ``Workflow.parse``     |
|               |             | or grammar into        | malformed input          | of a different type  | context; the input is a        |                        |
|               |             | semantic structure     |                          | than the input       | representation *of* the output |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``normalize`` | Normalizes  | Rewrite an accepted    | **MUST** raise for an    | The canonical form,  | **MUST** be idempotent;        | ``normalize_url``      |
|               |             | form as its canonical  | invalid form             | itself an accepted   | **MUST NOT** use resolution    |                        |
|               |             | equivalent             |                          | form                 | context                        |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``build``     | Builds      | Assemble a new         | **MAY** raise when       | A new composite      | Creates a new artifact from    | ``build_conf``         |
|               |             | semantic artifact      | construction fails       | artifact             | semantic components;           |                        |
|               |             |                        |                          |                      | dependencies should be         |                        |
|               |             |                        |                          |                      | explicit                       |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+
| ``get``       | Gets        | Query or compute a     | **MAY** raise for        | Information about    | **MUST NOT** acquire external  | ``get_document_shape`` |
|               |             | value from explicit    | invalid input            | the inputs           | or ambient state; does not     |                        |
|               |             | semantic inputs        |                          |                      | canonicalize or construct a    |                        |
|               |             |                        |                          |                      | substantial artifact           |                        |
+---------------+-------------+------------------------+--------------------------+----------------------+--------------------------------+------------------------+

.. end verbs

When two verbs both seem to fit, the pair's test decides:

.. begin verb-pairs

+-----------------------------+------------------------------------------------------------------------------------------+
| Mistaken pair               | Test                                                                                     |
+=============================+==========================================================================================+
| ``get`` / ``load``          | Does it read external or ambient state? Then ``load``.                                   |
+-----------------------------+------------------------------------------------------------------------------------------+
| ``validate`` / ``require``  | Does it return the checked value, or guard a precondition before an action? Then         |
|                             | ``require``; ``validate`` checks a contract and returns ``None``.                        |
+-----------------------------+------------------------------------------------------------------------------------------+
| ``require`` / ``resolve``   | Does absence get a fallback? Then ``resolve``; ``require`` raises instead.               |
+-----------------------------+------------------------------------------------------------------------------------------+
| ``resolve`` / ``normalize`` | Does the contract fix the default (``normalize``), or does the caller supply it          |
|                             | (``resolve``)?                                                                           |
+-----------------------------+------------------------------------------------------------------------------------------+
| ``parse`` / ``normalize``   | Is the output a different type than the input? Then ``parse``.                           |
+-----------------------------+------------------------------------------------------------------------------------------+
| ``build`` / ``get``         | Is the result a substantial new artifact? Then ``build``.                                |
+-----------------------------+------------------------------------------------------------------------------------------+

.. end verb-pairs

A function that does two of these things is named for the guarantee its callers
rely on, and its summary may describe the inner step. ``require_from_keys``
builds a guard, but the guard requires, so it is a ``require``.

Defaults split ``normalize`` from ``resolve``: filling an omitted field with the
default its contract fixes rewrites a shorthand, so it is a ``normalize``;
substituting a default the caller supplies is a fallback, so it is a ``resolve``.

``require`` is the general narrow-or-raise verb, not "``resolve`` that raises":
``require(resolve(...))`` is one specialization of it, which is why guards such
as ``require_str`` and ``require_mapping`` use it. ``build`` covers what other
code bases call ``prepare``, ``convert``, or ``make``.

A ``resolve`` function may still raise. What it must not do is treat absence as an
error when a fallback is part of its contract: missing input falls back, while
input that is present but invalid raises. For example, ``resolve_format`` picks an
explicit format, then the destination's extension, then ``json``, so
``resolve_format("out", None)`` returns ``json`` while
``resolve_format(None, "bogus")`` raises ``ValueError``. Raising alone does not
make a function a ``require``. Name it ``require`` when its purpose is to enforce
that a needed value exists, and it never falls back to a default.

Specialized verbs are not alternatives to weigh against the table: use ``cast``
for coercion, ``compile`` for the compiler, ``generate``/``gen_`` for code
generation and Python generators, ``migrate`` for version migration,
``serialize``, ``register``, ``read``/``write``/``open``/``close``, and
``is``/``has`` for predicates.

Adding or changing a built-in module
------------------------------------

A built-in module change commonly requires work in several places:

1. Update the implementation under ``riko/modules/``.
2. Update the corresponding ``<Name>Conf`` ``TypedDict`` contract in
   ``riko/types/modules.py``.
3. Regenerate the parse-time ``objconf`` types in
   ``riko/coercion/_configs.py`` from that contract:

   .. code-block:: bash

       uv run manage codegen --config

4. If the module catalog changed (for example, a built-in was added or removed),
   regenerate the discovery names and module ids too:

   .. code-block:: bash

       uv run manage codegen --names

   The selectors are additive, so a new module normally uses one command:

   .. code-block:: bash

       uv run manage codegen --config --names

5. Add or update sync and async tests where both execution paths exist. Place
   each test by the rules in ``tests/__init__.py``: pick the tier, then the file
   whose row in that tier's index names the test's subject, and put the test in
   that subject's ``Test<Subject>`` class. An asynchronous test is a native ``async def`` decorated with ``async_test``
   from ``tests/__init__.py``. Never wrap a coroutine in a synchronous test
   body. A test stays a plain ``def`` under ``skipif_issync`` only when the
   synchronous path is deliberately what it exercises (for example, the
   synchronous execution driving an async-only module). If the synchronous
   runner is incidental, drop it and write the test as a native ``async def``.
6. Import async primitives such as ``fail_after``, ``checkpoint``, or
   ``async_sleep`` from ``riko.bado._backend``, never from ``anyio`` directly.
   CI also runs the suite without the async extra, and a module-level
   ``import anyio`` fails collection before ``async_test`` can skip anything.
7. Add deterministic examples to the module docstring or cookbook.
8. Update the FAQ catalog when adding, removing, or materially changing a
   built-in module.
9. Run the preferred validation sequence above.

The configuration drift guard (``tests/internal/test_codegen.py``) fails when
the ``<Name>Conf`` contracts and ``riko/coercion/_configs.py`` fall out of sync.
Generated discovery names and ids have their own drift guards under
``tests/internal/``.

Pull request checklist
----------------------

Before requesting review, confirm that:

- the pull request has one clear purpose;
- the description explains the problem, approach, and user-visible effect;
- tests cover the change and pass locally;
- ``manage lint --all`` and both pyright passes succeed;
- documentation is updated for user-visible behavior;
- all affected generated artifacts are current;
- no secrets, local paths, build artifacts, or unrelated edits are included; and
- the pull request targets the branch agreed in the issue or discussion.

Reviewers may ask for a smaller patch, additional tests, or changes to public
API shape. That is normal maintenance work, not a rejection of the contribution.

Useful links
------------

- `README`_
- `Cookbook`_
- `FAQ`_
- `Installation guide`_
- `Issue tracker`_
- `Repository`_

.. _uv: https://docs.astral.sh/uv/
.. _issue: https://github.com/nerevu/riko/issues
.. _README: README.rst
.. _Cookbook: docs/COOKBOOK.rst
.. _FAQ: docs/FAQ.rst
.. _Installation guide: docs/INSTALLATION.rst
.. _Issue tracker: https://github.com/nerevu/riko/issues
.. _Repository: https://github.com/nerevu/riko
