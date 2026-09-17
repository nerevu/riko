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

Explain the problem before proposing an API. Describe why existing ``pipes`` or
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
    Run pytest. Paths may be passed positionally or with repeatable ``--where``;
    use ``--no-cov`` for faster focused runs and ``--tox`` for the tox runner.

``manage prettify``
    Sort imports, apply Ruff fixes, and format Python. Use ``--where`` to limit
    the scope and ``--yaml`` when formatting YAML instead.

``manage check``
    Run Ruff checks against staged Python files. This is a fast pre-commit check,
    not a replacement for the full lint suite.

``manage lint``
    Run Ruff lint plus ``ruff format --check`` by default. Standard checks may be
    selected additively with ``--rst``, ``--docs``, ``--actions``, ``--yaml``, and
    ``--docstrings``. ``manage lint --all`` runs all standard checks, including
    all import-contract checks. Type completeness, strict pylint, and distribution
    checks remain explicit via ``--check-types``, ``--verify-types``, ``--strict``,
    and ``--dist``.

``manage lint imports``
    Check internal import contracts. With no selector it runs the canonical-import
    check. Use ``--canonical``, ``--relative``, and ``--architecture`` additively,
    or ``--all`` for all three.

``manage codegen``
    Regenerate derived repository artifacts. With no selector it regenerates
    configuration types. Use ``--config``, ``--names``, ``--pipes``, and ``--api``
    additively, or ``--all`` for every generator.

Daily development workflow
--------------------------

Use the narrowest feedback loop while implementing a change. Run a focused test
for the behavior you are changing:

.. code-block:: bash

    uv run manage test --no-cov tests/public/test_collections.py

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

1. Regenerate any affected artifacts.

   .. code-block:: bash

       uv run manage codegen --config

   Choose the relevant ``--config``, ``--names``, ``--pipes``, and ``--api``
   selectors, or use ``--all`` when appropriate. Skip this step when no generated
   input changed.

2. Format the changed code (and YAML, when applicable).

   .. code-block:: bash

       uv run manage prettify
       uv run manage prettify --yaml

3. Run focused tests for the behavior being changed.

   .. code-block:: bash

       uv run manage test --no-cov tests/path/to/test_file.py

4. Run the complete local test suite.

   .. code-block:: bash

       uv run manage test --no-cov

5. Run the standard repository lint bundle.

   .. code-block:: bash

       uv run manage lint --all

6. Run both type-checking passes explicitly.

   .. code-block:: bash

       uv run manage lint --check-types
       uv run manage lint --verify-types

7. Run the supported-version matrix when the change affects packaging,
   dependencies, typing, async behavior, or interpreter-specific code.

   .. code-block:: bash

       uvx tox run

Steps 4--6 match the core test/lint/type checks used by CI. ``manage lint --all``
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
- Preserve sync and async output parity when a module exposes both paths.
- Keep pipelines single-use and iterator semantics explicit.
- Add type annotations for new public and extension-facing code.
- Let ``ruff`` format code instead of hand-tuning style around the formatter.
- Avoid unrelated formatting, renaming, or cleanup in a focused pull request.

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

5. Add or update sync and async tests where both execution paths exist.
6. Add deterministic examples to the module docstring or cookbook.
7. Update the FAQ catalog when adding, removing, or materially changing a
   built-in module.
8. Run the preferred validation sequence above.

The configuration drift guard (``tests/internal/test_gen_config.py``) fails when
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
