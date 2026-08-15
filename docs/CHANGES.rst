Changelog
=========

v0.75.0 (unreleased)
--------------------

New
~~~

- Add value-taking ``pipe`` chaining to ``SyncPipe``/``AsyncPipe`` — for adding a
  ``pipe`` to a ``pipeline`` by a module name that can't be written as an attribute
  (a runtime variable, a dotted identifier such as
  ``"microsoft.autopilot.ensure"``, or a ``ModuleName`` member). The attribute form
  (``pipe.tokenizer(...)``) is unchanged.

  - ``pipe | "tokenizer"``, ``pipe | ("tokenizer", conf)``,
    ``pipe | SyncPipe("sort", conf=...)``, and ``items | SyncPipe(...)``
  - ``pipe.pipe(name, conf=...)`` / ``pipe.async_pipe(name, ...)``

- Add ``riko.ext.ModuleName``, a deliberately empty ``StrEnum`` base for typed
  module-name discovery, plus ``normalize_module_name`` and the
  ``ModuleNameLike = str | ModuleName`` alias. A ``ModuleName`` subclass member is
  accepted anywhere a module name is (``SyncPipe(MyModules.FETCH)``,
  ``pipe | MyModules.SORT``) and normalizes to its canonical string, so serialized
  pipelines are unchanged.

- Add a **module registry and entry-point plugin seam**. An external package can
  add riko modules with **no edit to core**: expose a ``riko.ext.ModuleDefinition``
  (point it at a module exposing ``pipe``/``async_pipe``, or pass ``sync_pipe`` /
  ``async_pipe`` callables explicitly) and declare it under
  ``[project.entry-points."riko.modules"]``. ``riko.ext.register`` /
  ``ModuleRegistry`` cover in-process registration (precedence: runtime →
  entry point → built-in). Registered and entry-point modules resolve like
  built-ins and appear in ``list_modules()``. See ``examples/riko-example-ext``
  (entry point) and ``examples/register_module.py`` / ``examples/register_alias.py``
  (runtime ``register``).

- Infer ``isasync`` for ``processor``/``operator``/``splitter`` when it isn't
  passed — from an ``async def`` or the conventional ``async_pipe`` name — so an
  async pipe no longer silently builds a sync wrapper when the author forgets
  ``isasync=True``. An explicit ``isasync=True`` is now needed only where the
  name signal can't reach the type checker: a sync callable that is the async
  interface but isn't named ``async_pipe`` (e.g. a lambda), or a sync
  ``def async_pipe`` whose decorated result is passed to a typed API such as
  ``ModuleDefinition(async_pipe=...)``. A function named ``pipe`` that resolves
  async (an ``async def`` or ``isasync=True``) is a contradiction and raises a
  helpful ``TypeError``. The typed decorator overloads track the ``async def``
  case, so ``@operator()`` on a coroutine function is statically async.

Changes
~~~~~~~

- Renamed the ``SyncPipe``/``AsyncPipe`` ``pool_scope`` value from ``"stage"`` to
  ``"pipe"`` (contrasting with ``"pipeline"``): a per-``pipe`` pool is released
  after each pipe's iteration, a ``"pipeline"`` pool is shared across the run.
  The default (``"pipeline"``) is unchanged.

- Pipe resolution now runs through a single compiler-free façade
  (``riko.ext`` registry/resolver); runtime module resolution no longer imports
  the compiler.

- Generated pipeline modules now expose a stable ``pipe`` / ``async_pipe`` entry
  point (instead of a function named after the pipe), so a compiled sub-pipeline
  resolves exactly like a built-in module.

v0.74.2 (2026-08-11)
--------------------

Changes
~~~~~~~

- Harden the release/publish GitHub workflows: set explicit workflow
  permissions and skip re-uploading existing PyPI artifacts.
- Add ``pygments`` to the dev dependencies (RST linting).

Bugfixes
~~~~~~~~

- Verify ``xpath`` strips XML namespaces (#20); move content
  re-encoding into ``riko/_reencode.py`` and simplify the parsers.

v0.74.1 (2026-08-10)
--------------------

New
~~~

- Promote ``async_return`` and ``async_sleep`` to the stable top-level
  ``riko`` API, so async pipes and doctests import their helpers (and
  ``run``) from ``riko`` rather than ``riko.bado``.

Documentation
~~~~~~~~~~~~~

- Correct processor module docstrings: import ``run`` from ``riko`` and
  document the accepted ``item`` type as ``dict or Iter[dict]``.
- Convert ``docs/DAG_FORMAT`` to reStructuredText and fold
  ``API_STABILITY`` into the migration guide.
- Relocate internal planning docs (``ROADMAP`` and the gameplans) out of
  the user-facing ``docs/`` tree; streamline a Cookbook example and
  backfill the changelog.

Bugfixes
~~~~~~~~

- ``manage test`` correctly reads the ``cov`` flag (not ``cover``), so
  ``--cov=riko`` coverage works.

- Add ``riko.ext.ModuleName``, a deliberately empty ``StrEnum`` base for typed
  module-name discovery, plus ``normalize_module_name`` and the
  ``ModuleNameLike = str | ModuleName`` alias. Any ``ModuleName`` subclass member
  is now accepted anywhere a module name is (``SyncPipe(MyModules.FETCH)``,
  ``pipe | MyModules.SORT``); it is normalized to its canonical string at the
  boundary, so serialized pipelines are unchanged.

v0.74.0 (2026-08-06)
--------------------

New
~~~

- Add ``run-pipe --path`` for executing a ``pipeline`` from an arbitrary file.
- Promote the async-backend and JSON ``pipeline`` compilation helpers to the
  stable top-level API, and expose ``get_module_metadata``.

Changes
~~~~~~~

- Rename ``riko.compile.compile`` to ``riko.compile.compile_pipe`` so it no longer
  shadows the builtin ``compile``.
- Add ``manage lint --rst`` to render every RST document and validate its
  internal links; run it under ``tox -e lint`` and in CI.
- ``manage test`` and ``manage lint`` now accept multiple paths.

Documentation
~~~~~~~~~~~~~

- Fix the Cookbook ``split`` memory note, the README ``tokenizer``/``hash``
  examples, and malformed tables in the FAQ and migration guide.
- Clean up feedautodiscovery module description

v0.73.1 (2026-08-06)
--------------------

Documentation
~~~~~~~~~~~~~

- Correct and reorganize the README, Cookbook, FAQ, installation, migration,
  contribution, and credits documentation.

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

v0.66.0 (2020-08-14)
--------------------

Changes
~~~~~~~

- Make ``skip_if`` searching case insensitive.

Bugfixes
~~~~~~~~

- Remove an unused import.

v0.65.0 (2020-08-14)
--------------------

New
~~~

- Add a user-defined operator.

Bugfixes
~~~~~~~~

- Fix typos.

v0.64.3 (2020-08-13)
--------------------

Bugfixes
~~~~~~~~

- Actually pass request params through to the fetcher.

v0.64.2 (2020-08-13)
--------------------

Bugfixes
~~~~~~~~

- Properly resolve keyword arguments.

v0.64.1 (2020-08-13)
--------------------

Changes
~~~~~~~

- Loosen the ``pytz`` requirement.

Bugfixes
~~~~~~~~

- Properly pass request params.

v0.64.0 (2020-08-11)
--------------------

Changes
~~~~~~~

- Use a ``LocalProxy`` to return the URL opener, return the content type with
  the response, remove the ``r`` attribute, and make ``ext`` a property.

Bugfixes
~~~~~~~~

- Get ``fetch`` memoization working.

v0.63.0 (2020-08-11)
--------------------

Changes
~~~~~~~

- Allow skips to contain a callable.

Bugfixes
~~~~~~~~

- Properly compare integers; use the correct pipe names.

v0.62.2 (2020-07-30)
--------------------

Changes
~~~~~~~

- Fix lint errors.

v0.62.1 (2020-07-30)
--------------------

Bugfixes
~~~~~~~~

- Update the language identifier.

Documentation
~~~~~~~~~~~~~

- Correct the ``kazeeki`` pipe example.

v0.62.0 (2020-07-29)
--------------------

Bugfixes
~~~~~~~~

- Add tests and generalize the cast fix so casting no longer crashes.

- Correct the ``skip_if`` logic for the text key.

- Account for ``Deferred`` having no ``close`` method, and for ``MemoryReactor``
  (thus ``MemoryReactorClock``) now implementing ``IReactorCore``.

v0.61.4 (2020-07-29)
--------------------

Bugfixes
~~~~~~~~

- Correctly set the license.

v0.61.3 (2020-07-29)
--------------------

Bugfixes
~~~~~~~~

- Update requirements; correct lint errors.

v0.61.2 (2020-07-06)
--------------------

Changes
~~~~~~~

- Set the flake8 max line length equal to black; upgrade ``meza`` and twine.

Bugfixes
~~~~~~~~

- Add a default user agent for ``urlopen`` HTTP requests.

Documentation
~~~~~~~~~~~~~

- Add an XML namespace warning.

v0.61.1 (2020-02-02)
--------------------

Changes
~~~~~~~

- Upgrade ``mezmorize``.

Bugfixes
~~~~~~~~

- Get the twine upload working.

v0.61.0 (2020-02-01)
--------------------

Changes
~~~~~~~

- Remove Python 2 support; upgrade dependencies.

Bugfixes
~~~~~~~~

- Catch ``StopIteration`` exceptions.

Documentation
~~~~~~~~~~~~~

- Fix a broken link to ``reverse``.

v0.60.4 (2018-09-13)
--------------------

Bugfixes
~~~~~~~~

- Correct a syntax error.

v0.60.3 (2018-09-12)
--------------------

Bugfixes
~~~~~~~~

- Use the correct URL params.

v0.60.2 (2018-08-18)
--------------------

Bugfixes
~~~~~~~~

- Use a new exchange rate data source.

v0.60.1 (2018-08-18)
--------------------

Bugfixes
~~~~~~~~

- Don't crash on JSON parse errors; fix Python 2 import errors.

v0.60.0 (2018-05-23)
--------------------

New
~~~

- Add the URL to ``urllib`` exceptions.

v0.59.1 (2018-05-19)
--------------------

Bugfixes
~~~~~~~~

- Fix boolean type casting.

v0.59.0 (2018-05-18)
--------------------

New
~~~

- Add a ``name`` attribute to ``async_url_open``.

Bugfixes
~~~~~~~~

- Upgrade conflicting requirements.

v0.58.0 (2018-05-18)
--------------------

Bugfixes
~~~~~~~~

- Ignore currency pairs with no price; convert requirements to lists.

v0.57.0 (2017-08-31)
--------------------

Changes
~~~~~~~

- Upgrade ``mezmorize`` to move the memoize logic into it.

Bugfixes
~~~~~~~~

- Upgrade ``mezmorize`` to fix Heroku detection; fix the manager's test command.

v0.56.3 (2017-08-18)
--------------------

Bugfixes
~~~~~~~~

- Initialize the ``ext`` property.

v0.56.2 (2017-08-18)
--------------------

Bugfixes
~~~~~~~~

- Upgrade ``mezmorize``.

v0.56.1 (2017-08-18)
--------------------

Bugfixes
~~~~~~~~

- Parse URLs without file extensions.

v0.56.0 (2017-08-17)
--------------------

Changes
~~~~~~~

- Update ``mezmorize`` and rename a keyword argument; add a source option to the
  lint command.

v0.55.0 (2017-08-17)
--------------------

New
~~~

- Add cache metadata to ``memoize`` and ``fetch``.

Changes
~~~~~~~

- Simplify ``cache_type`` parsing.

v0.54.1 (2017-08-17)
--------------------

Bugfixes
~~~~~~~~

- Upgrade ``mezmorize`` and correctly set keyword arguments.

v0.54.0 (2017-08-16)
--------------------

New
~~~

- Pass ``cache_options`` and ``preferred_memcache``.

v0.53.0 (2017-08-16)
--------------------

Changes
~~~~~~~

- Remove Python 3.4 support and upgrade PyPy versions; upgrade ``mezmorize``.

v0.52.3 (2017-08-12)
--------------------

Changes
~~~~~~~

- Upgrade ``chardet``.

v0.52.2 (2017-08-11)
--------------------

Bugfixes
~~~~~~~~

- Fix ``pgrep`` to work on Heroku instances.

v0.52.1 (2017-08-09)
--------------------

Bugfixes
~~~~~~~~

- Fix a lint error.

v0.52.0 (2017-08-09)
--------------------

New
~~~

- Add more cache types.

Bugfixes
~~~~~~~~

- Fix a bug when the new month isn't in 1..12; use ``Clock`` to manage
  ``FakeReactor`` timing (closes #37).

Documentation
~~~~~~~~~~~~~

- Update the contribution documentation.

v0.51.0 (2017-05-01)
--------------------

New
~~~

- Add ``takewhile`` functionality to the ``filter`` pipe.

Changes
~~~~~~~

- Set a default memcache server.

v0.50.0 (2017-04-12)
--------------------

New
~~~

- Add the ``timeout`` pipe.

- Add options to specify the cache, namespace, and cache backend.

Changes
~~~~~~~

- Default to spread memcache; remove ``DotDict``'s ``feedparser`` dependency.

v0.49.2 (2017-04-12)
--------------------

Bugfixes
~~~~~~~~

- Don't consume the stream in ``PipeCollections``; prevent a
  ``UnicodeEncodeError``; fix the URL fetcher.

- Persist memoized responses; fix exchange rate memoization and encoding.

v0.49.1 (2017-04-09)
--------------------

Bugfixes
~~~~~~~~

- Fix spacing.

v0.49.0 (2017-04-09)
--------------------

New
~~~

- Add RSS caching.

Bugfixes
~~~~~~~~

- Fix caching.

v0.48.0 (2017-04-06)
--------------------

Changes
~~~~~~~

- Populate pipe collections with ``conf``; add caching and rename the ``sleep``
  config; add a URL fetcher and move the cast functions.

Bugfixes
~~~~~~~~

- Account for empty dates.

v0.47.0 (2017-04-04)
--------------------

New
~~~

- Add currency symbol unicode values.

Bugfixes
~~~~~~~~

- Catch ``TypeError`` exceptions.

v0.46.1 (2017-04-04)
--------------------

Bugfixes
~~~~~~~~

- Correctly parse dates.

v0.46.0 (2017-04-04)
--------------------

Changes
~~~~~~~

- Use case-insensitive comparison.

v0.45.1 (2017-04-04)
--------------------

Bugfixes
~~~~~~~~

- Fix a syntax error; cast parts to strings before joining; use the correct
  import; don't convert input to text.

Documentation
~~~~~~~~~~~~~

- Update documentation.

v0.45.0 (2017-04-01)
--------------------

New
~~~

- Add the ``typecast`` pipe.

v0.44.0 (2017-04-01)
--------------------

Changes
~~~~~~~

- Remove the ``lib`` directory and parse timezones.

v0.43.1 (2017-03-24)
--------------------

Bugfixes
~~~~~~~~

- Fix Python 2 tests; remove a duplicate key.

v0.43.0 (2017-03-24)
--------------------

New
~~~

- Add the ``geolocate`` pipe.

Changes
~~~~~~~

- Return ``inf`` when dividing by zero; refactor so parsers don't need to return
  ``skip``.

v0.42.0 (2017-03-23)
--------------------

New
~~~

- Allow items to be type-cast when sorting; add a ``get_skip`` dict ``re.search``
  option; add an option to always return multiple items.

Bugfixes
~~~~~~~~

- Handle the changed Yahoo API format; catch ``IndexError`` when casting to a
  date; decode the raw stream response.

v0.41.0 (2017-03-18)
--------------------

New
~~~

- Allow ``get_skip`` to take a dict; only check the conversion rate when
  necessary; find text "at" a location.

Changes
~~~~~~~

- Move the ``kazeeki`` data and refactor the pipe; cast null numbers to ``NaN``;
  compress the collection module to a single file; use the microdom parser to
  find RSS links.

Bugfixes
~~~~~~~~

- Don't block stderr during nosetests; convert decoded values to strings; strip
  whitespace from tokens; don't try to convert args when skipping.

v0.40.1 (2017-03-16)
--------------------

Bugfixes
~~~~~~~~

- Reduce function complexities; downgrade ``pygogo`` to match ``meza``'s; close
  ``meza`` files when done with CSV; fix xpath in the PyPy environment (no lxml).

v0.40.0 (2017-03-16)
--------------------

Changes
~~~~~~~

- Upgrade ``html5lib``; add a pyup.io config file.

v0.39.0 (2017-03-10)
--------------------

New
~~~

- Add new pipes; add a debugging option.

Changes
~~~~~~~

- Rename ``stringtokenizer`` to ``tokenizer``; rename functions; move
  ``invert_dict`` and move/rename ``entity2text``.

v0.38.0 (2017-03-10)
--------------------

New
~~~

- Add the ``eq`` operator to the ``filter`` pipe; add the ``fetchtext`` pipe.

Changes
~~~~~~~

- Add more logging.

Bugfixes
~~~~~~~~

- Use ``cElementTree`` when available; initialize ``self.entry`` as an iterator.

v0.37.0 (2016-09-29)
--------------------

New
~~~

- Add a lowercase transformation to the ``join`` pipe.

v0.36.0 (2016-09-29)
--------------------

New
~~~

- Add the ``join`` pipe; add the ``sum`` pipe.

Bugfixes
~~~~~~~~

- Correctly parse the XML path.

Documentation
~~~~~~~~~~~~~

- Add more links to the documentation.

v0.35.3 (2016-07-26)
--------------------

Bugfixes
~~~~~~~~

- Install Python 2 requirements under Python 2 (fixes #3).

v0.35.2 (2016-07-25)
--------------------

Bugfixes
~~~~~~~~

- Update ``meza`` to fix a ``pygogo`` version conflict; store downloaded packages
  in the wheel dir; fix prefix generation.

Documentation
~~~~~~~~~~~~~

- Update the contribution docs.

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


