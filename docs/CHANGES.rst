Changelog
=========

v0.73.0 (2026-08-05)
--------------------

Legacy removal — the ``legacy`` branch is the ``v0.72.x`` release; these are the
changes on top of it. See the "Upgrading from the ``legacy`` branch" section of
``docs/MIGRATION.rst`` for verified before/after behavior.

Changes
~~~~~~~

- **Remove the legacy nested-loop JSON shape** (a ``loop`` module carrying its
  submodule under ``conf["embed"]["value"]``) and its input converter. The
  canonical forms are the compact loop (top-level ``embed``) and, for processor
  loops, a direct node. The terminal ``output`` node marker is retained; only its
  treatment as a resolvable virtual module was removed.

- **Remove the legacy ``Context`` describe kwargs** (``describe_input=`` /
  ``describe_dependencies=`` and the ``_mode_from_kwargs`` translation). Pass
  ``mode=ExecutionMode.…``; the derived read-only properties are kept.

- **Remove ``Objconf`` entirely** (it was a deprecated factory in ``v0.72.0``).
  Import ``DynamicConf`` from ``riko.ext.config``.

- Promote ``get_path`` into the stable surface (``riko.__all__``); clean up the
  public API surface.

- Complete async parity: add lazy async streams and structured pool execution;
  split ``helpers.py`` / ``utils.py`` into focused private modules.

Bugfixes
~~~~~~~~

- Unify the HTTP backend regardless of params.

- Preserve falsy non-``None`` typed-sort defaults instead of ``""``; treat falsy
  values as present rather than missing (only ``None`` becomes ``[]`` in
  ``listize``).

- Distinguish ``list`` vs ``tuple`` in the repr cache and bypass it for unhashable
  args; support true union dataclasses.

- Don't mutate a compiled module's ``__name__``.

v0.72.2 (2026-08-05)
--------------------

Changes
~~~~~~~

- Add a GitHub publishing workflow.

Bugfixes
~~~~~~~~

- Add missing README links and a lint option.

v0.72.1 (2026-08-05)
--------------------

Bugfixes
~~~~~~~~

- Stop masking legitimate module import errors.

- Fail gracefully on filter parse errors; raise on unsupported filter operations.

- Preserve falsy non-``None`` ``DotDict`` values; use an empty string for the URL
  cast default.

- Cast ``"now"`` as a ``datetime``; pass ``_tzinfo`` for zone-less
  ``struct_time``.

- Gracefully parse missing indexes; use the correct command help text.

v0.72.0 (2026-08-03)
--------------------

New
~~~

- Add sub-module looping (per-parent loop semantics).

- Add async pubsub and async pipe compilation.

- Support split-module compilation.

Changes
~~~~~~~

- **Replace Twisted with AnyIO** as the async runtime. Twisted is no longer
  imported or importable; ``riko.bado`` now runs on AnyIO. See the
  "Twisted replaced by AnyIO" note in ``docs/MIGRATION.rst``.

- Make the compact loop form canonical and document loop behavior.

- Emit lowercase compilation kwargs; use ``int``/``float`` instead of
  ``number``.

- Make ``issync``/``isasync`` public; rename CLIs.

Bugfixes
~~~~~~~~

- Fail ``SyncCollection`` on exception instead of on close.

- Always consume the memoized ``__aiter__``.

v0.71.2 (2026-07-23)
--------------------

Changes
~~~~~~~

- Drop PyPy support and update documentation.

Bugfixes
~~~~~~~~

- Make date parsing deterministic.

- Fix file resource clean-up.

- Harden feed entry text fallbacks; handle feed entries without
  descriptions.

- Fix py3.12/py3.13 optional/non-optional CI regressions.

v0.71.1 (2026-07-23)
--------------------

Changes
~~~~~~~

- Bump pyasn1, soupsieve, and cryptography dependencies.

v0.71.0 (2026-07-21)
--------------------

Changes
~~~~~~~

- **Replace ``Objconf`` with ``DynamicConf``.** ``Objconf(...)`` becomes a
  compatibility factory (emits ``DeprecationWarning``); it is removed outright in
  a later release. See the "``Objconf`` is removed" note in
  ``docs/MIGRATION.rst``.

- Complete the async lifecycle and source parity; achieve sync/async
  chaining parity.

- Autogenerate ``riko/types/configs.py`` with drift detection.

- Rename the console script; sort tests into public/internal/functional.

v0.70.0 (2026-07-21)
--------------------

New
~~~

- Dynamically generate modules and metadata (derived module catalog).

- Add bare-bones DAG format with ``convert-dag``/``compile`` CLIs; refactor
  codegen.

Changes
~~~~~~~

- **Establish a three-tier public API boundary** (stable ``riko``/``riko.api``,
  extension ``riko.ext``, private ``_*``). See the "Three-tier import surface"
  note in ``docs/MIGRATION.rst``.

- **Add pipe/collection lifecycle** — ``SyncPipe``/``AsyncPipe``/collections
  are now single-execution; re-iteration no longer silently re-runs and
  chaining onto a ``CLOSED``/``FAILED`` pipe raises ``PipelineStateError``.
  See the "Single-execution pipe lifecycle" note in ``docs/MIGRATION.rst``.

- **Convert the ``Context`` describe booleans to an ``ExecutionMode`` enum**
  (``describe_input``/``describe_dependencies`` are now read-only properties).
  See the "ExecutionMode replaces the describe booleans" note in
  ``docs/MIGRATION.rst``.

- Make ``OperatorReturnKind`` an enum; add inference diagnostics.

- Split ``riko/modules/__init__.py`` into leaf submodules; remove shared
  mutable ``Module`` state.

Security
~~~~~~~~

- Harden XML parsing against XXE/entity-expansion (disable entity
  resolution, DTD loading, and network access under lxml).

Bugfixes
~~~~~~~~

- Correct date arithmetic; apply stable sorts in reverse rule order; stop
  equating both-missing values on joins.

- Handle PEP 604 unions in ``fromdict``; clean up worker pools on exit.

- Enforce timeout deadlines on blocking sync reads; treat async ``timeout=0``
  as "no timeout" (consistent with sync).

- Harden pub/sub ``close``/``send`` against exhausted generators and
  receive-queue overflow; deliver only the kwargs a user ``func`` declares.

- Guard ``fcntl`` for Windows compatibility.

- Numerous correctness fixes to casting, iteration, and typing.

v0.69.0 (2026-07-14)
--------------------

Changes
~~~~~~~

- Refactor pipe compilation; centralize caching; intelligently generate
  assignments.

- Replace ``ItemArg`` with ``Item``.

- Add async timeout parsing.

Performance
~~~~~~~~~~~

- Cache filter rules and ``_from_hashable``; optimize conf, date, and file
  parsing; bypass the cache for dynamic confs.

v0.68.1 (2026-07-13)
--------------------

Bugfixes
~~~~~~~~

- Fix remaining lint errors; correct the ijson version spec.

v0.68.0 (2026-07-13)
--------------------

New
~~~

- Add pub/sub, ``fetchtable``, the ``aggregate`` pipe, pipe exporting, and
  async URL encoding/decoding.

Changes
~~~~~~~

- Major refactor: enable pipeline compilation; go all-in on ``uv``; move
  dependencies to ``pyproject.toml``.

- Migrate the test suite to pytest; deprecate Python 2.

Bugfixes
~~~~~~~~

- Return ``unique_everseen`` elements; improve RSS pub/upd and field/value
  parsing.

v0.67.0 (2026-07-13)
--------------------

Changes
~~~~~~~

- Bump minimum supported version to Python 3.7; add black and a prettify
  command.

Bugfixes
~~~~~~~~

- Properly add setup requirements; clean up docblocks.

v0.35.1 (2016-07-22)
--------------------

Bugfixes
~~~~~~~~

- Fix makefile lint command. [Reuben Cummings]

- Update pygogo requirement (fixes #2) [Reuben Cummings]

v0.35.0 (2016-07-19)
--------------------

New
~~~

- Limit the number of unique items tracked. [Reuben Cummings]

- Add grouping ability to count pipe. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fix processor metadata. [Reuben Cummings]

v0.34.0 (2016-07-19)
--------------------

New
~~~

- Add list element searching to microdom. [Reuben Cummings]

- Add more operations to filter pipes. [Reuben Cummings]

Changes
~~~~~~~

- Merge async_pmap and async_imap. [Reuben Cummings]

- Change deferToProcess name and arguments. [Reuben Cummings]

- Rename modules/functions, and update docs. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Force getElementsByTagName to return child. [Reuben Cummings]

- Only use FakeReactor when actually needed. [Reuben Cummings]

- Fix async html parsing. [Reuben Cummings]

- Prevent IndexError. [Reuben Cummings]

- Fix async opening of http files. [Reuben Cummings]

- Be lenient with html parsing. [Reuben Cummings]

- Fix empty xpath and start value bugs. [Reuben Cummings]

v0.33.0 (2016-07-01)
--------------------

Changes
~~~~~~~

- Major refactor for py3 support: [Reuben Cummings]

  - fix py3 and open file errors
  - port missing twisted modules
  - refactor RSS parsing
  - and streaming json support
  - rename request function
  - make benchmarks.py a script and add to tests

Bugfixes
~~~~~~~~

- Fix pypy test errors. [Reuben Cummings]

v0.32.0 (2016-06-16)
--------------------

Changes
~~~~~~~

- Refactor to remove Twisted dependency. [Reuben Cummings]

v0.31.0 (2016-06-16)
--------------------

New
~~~

- Add parallel testing. [Reuben Cummings]

v0.30.2 (2016-06-16)
--------------------

Bugfixes
~~~~~~~~

- Add missing optional dependency. [Reuben Cummings]

v0.30.1 (2016-06-16)
--------------------

Bugfixes
~~~~~~~~

- Fix failed test runner. [Reuben Cummings]

- Fix lxml dependency errors. [Reuben Cummings]

v0.30.0 (2016-06-15)
--------------------

New
~~~

- Try loading workflow from curdir first. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fix remaining pypy errors. [Reuben Cummings]

- Fix “newdict instance” error for pypy. [Reuben Cummings]

- Add detagging to `fetchpage` async parser. [Reuben Cummings]

v0.28.0 (2016-03-25)
--------------------

New
~~~

- Add option to specify value if no regex match found. [Reuben Cummings]

Changes
~~~~~~~

- Make default exchange rate field ‘content’ [Reuben Cummings]

- Split now returns tier of feeds. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fix test mode for input pipe. [Reuben Cummings]

- Fix terminal parsing. [Reuben Cummings]

- Fix input pipe if no inputs given. [Reuben Cummings]

- Fix sleep config. [Reuben Cummings]

- Fix json bool parsing. [Reuben Cummings]


