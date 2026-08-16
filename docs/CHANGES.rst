Changelog
=========

v0.76.0 (unreleased)
--------------------

New
~~~

- ``LoopModule.embed`` now uses ``LoopableModuleId``, so embedding a non-loopable module
  in a loop is a static type error.

- Added a **typed module-name discovery surface**. ``riko.Modules`` is a flat
  namespace over every built-in ``pipe`` (reference one without knowing its
  category), and ``riko.Sources`` / ``riko.Transforms`` / ``riko.Sinks`` are
  generated ``StrEnum`` groupings by data-flow role. E.g., ``SyncPipe(Sources.FETCH)``
  behaves like ``SyncPipe("fetch")`` and ``pipe | Modules.FILTER`` like
  ``pipe.filter()``.

- Added ``category`` filtering (``source``, ``transform``, ``sink``) to
  ``riko.list_modules``, plus ``riko.describe_module(name)``.

- Added the ``gen-names`` script (and ``manage codegen``) to regenerate
  ``riko/modules/_names.py`` from the built-in catalog.

- Added a ``write`` sink pipe (``riko/modules/write.py``) that serializes a stream to
  ``conf['url']`` with a ``Targets`` converter (defaults to ``json``). Both the ``pipe``
  and``async_pipe`` interfaces skip the write when ``url`` is unset or ``target`` is
  ``list``/``tuple``.

- Added ``riko.async_write`` and ``riko.get_async_temp_file``: ``async_write`` is the
  anyio-native counterpart of ``meza.io.write``; ``get_async_temp_file`` is the async
  analog of ``get_temp_file``, usable as ``async with get_async_temp_file() as fp``.

- Added a typed ``riko.Targets`` ``StrEnum`` for ``export``/``write`` formats (``csv``,
  ``geojson``, ``json``, ``list``, ``tuple``, plus ``ofx``/``qif`` with the
  ``finance`` extra).

Removed
~~~~~~~

- Removed the ``loop`` operator's dedicated confs (``LoopRawConf``/``LoopConf``), the
  generated ``LoopObjconf``, and the legacy nested ``Embed`` descriptor. ``loop`` has no
  ``conf`` of its own because it uses the embedded submodule's   ``conf``. The submodule
  is now set with the compact top-level ``embed`` kwarg.

v0.75.0 (2026-08-15)
--------------------

New
~~~

- Added chaining to allow adding a ``SyncPipe``/``AsyncPipe`` to a ``pipeline`` by
  module name. This includes dynamic and dotted identifier names, e.g.,
  ``"microsoft.autopilot.ensure"``:

  - ``pipe | "tokenizer"``, ``pipe | ("tokenizer", conf)``,
    ``pipe | SyncPipe("sort", conf=...)``, and ``items | SyncPipe(...)``
  - ``pipe.pipe(name, conf=...)`` / ``pipe.async_pipe(name, ...)``

- Added a **module registry and entry-point plugin seam**. An external package can
  register modules through ``riko.ext.register`` or
  ``[project.entry-points."riko.modules"]``. Registered modules resolve like built-ins
  and appear in ``list_modules()``. See ``examples/riko-example-ext``,
  ``examples/register_module.py``, and ``examples/register_alias.py``.

- ``processor``/``operator``/``splitter`` now infer ``isasync`` so an async pipe won't
  silently build a sync wrapper if the author forgets ``isasync=True``. An explicit
  ``isasync=True`` is now needed only when an async interface uses a sync callable that
  isn't named ``async_pipe`` (e.g. a lambda), or when passing to a typed API such as
  ``ModuleDefinition(async_pipe=...)``. A function named ``pipe`` that resolves
  async (an ``async def`` or ``isasync=True``) raises a ``TypeError``.

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

- Hardened the release/publish GitHub workflows: set explicit workflow
  permissions and skip re-uploading existing PyPI artifacts.
- Added ``pygments`` to the dev dependencies (RST linting).

Bugfixes
~~~~~~~~

- Verified ``xpath`` strips XML namespaces (#20); move content
  re-encoding into ``riko/_reencode.py`` and simplify the parsers.

v0.74.1 (2026-08-10)
--------------------

New
~~~

- Promoted ``async_return`` and ``async_sleep`` to the stable top-level
  ``riko`` API, so async pipes and doctests import their helpers (and
  ``run``) from ``riko`` rather than ``riko.bado``.

Documentation
~~~~~~~~~~~~~

- Corrected processor module docstrings: import ``run`` from ``riko`` and
  document the accepted ``item`` type as ``dict or Iter[dict]``.
- Converted ``docs/DAG_FORMAT`` to reStructuredText and fold
  ``API_STABILITY`` into the migration guide.
- Relocated internal planning docs (``ROADMAP`` and the gameplans) out of
  the user-facing ``docs/`` tree; streamline a Cookbook example and
  backfill the changelog.

Bugfixes
~~~~~~~~

- ``manage test`` now correctly reads the ``cov`` flag (not ``cover``), so
  ``--cov=riko`` coverage works.

- Added ``riko.ext.ModuleName``, a deliberately empty ``StrEnum`` base for typed
  module-name discovery, plus ``normalize_module_name`` and the
  ``ModuleNameLike = str | ModuleName`` alias. Any user-defined ``ModuleName``
  subclass member (e.g. ``class MyModules(ModuleName)``) is now accepted anywhere a
  module name is (e.g., ``SyncPipe(MyModules.FETCH)``)

v0.74.0 (2026-08-06)
--------------------

New
~~~

- Added ``run-pipe --path`` for executing a ``pipeline`` from an arbitrary file.
- Promoted the async-backend and JSON ``pipeline`` compilation helpers to the
  stable top-level API, and expose ``get_module_metadata``.

Changes
~~~~~~~

- Renamed ``riko.compile.compile`` to ``riko.compile.compile_pipe`` so it no longer
  shadows the builtin ``compile``.
- Added ``manage lint --rst`` to render every RST document and validate its
  internal links; run it under ``tox -e lint`` and in CI.
- ``manage test`` and ``manage lint`` now accept multiple paths.

Documentation
~~~~~~~~~~~~~

- Fixed the Cookbook ``split`` memory note, the README ``tokenizer``/``hash``
  examples, and malformed tables in the FAQ and migration guide.
- Cleaned up feedautodiscovery module description

v0.73.1 (2026-08-06)
--------------------

Documentation
~~~~~~~~~~~~~

- Corrected and reorganize the README, Cookbook, FAQ, installation, migration,
  contribution, and credits documentation.

v0.73.0 (2026-08-05)
--------------------

Legacy removal: the ``legacy`` branch is the ``v0.72.x`` release; these are the
changes on top of it. See the "Upgrading from the ``legacy`` branch" section of
``docs/MIGRATION.rst`` for verified before/after behavior.

Changes
~~~~~~~

- **Removed the legacy nested-loop JSON shape** (a ``loop`` module carrying its
  submodule under ``conf["embed"]["value"]``) and its input converter. The
  canonical forms are the compact loop (top-level ``embed``) and, for processor
  loops, a direct node. The terminal ``output`` node marker is retained; only its
  treatment as a resolvable virtual module was removed.

- **Removed the legacy ``Context`` describe kwargs** (``describe_input=`` /
  ``describe_dependencies=`` and the ``_mode_from_kwargs`` translation). Pass
  ``mode=ExecutionMode.…``; the derived read-only properties are kept.

- **Removed ``Objconf`` entirely** (it was a deprecated factory in ``v0.72.0``).
  Import ``DynamicConf`` from ``riko.ext.config``.

- Promoted ``get_path`` into the stable surface (``riko.__all__``); clean up the
  public API surface.

- Completed async parity: add lazy async streams and structured pool execution;
  split ``helpers.py`` / ``utils.py`` into focused private modules.

Bugfixes
~~~~~~~~

- Unified the HTTP backend regardless of params.

- Preserved falsy non-``None`` typed-sort defaults instead of ``""``; treat falsy
  values as present rather than missing (only ``None`` becomes ``[]`` in
  ``listize``).

- Distinguished ``list`` vs ``tuple`` in the repr cache and bypass it for unhashable
  args; support true union dataclasses.

- Stopped mutating a compiled module's ``__name__``.

v0.72.2 (2026-08-05)
--------------------

Changes
~~~~~~~

- Added a GitHub publishing workflow.

Bugfixes
~~~~~~~~

- Added missing README links and a lint option.

v0.72.1 (2026-08-05)
--------------------

Bugfixes
~~~~~~~~

- Stopped masking legitimate module import errors.

- Failed gracefully on filter parse errors; raise on unsupported filter operations.

- Preserved falsy non-``None`` ``DotDict`` values; use an empty string for the URL
  cast default.

- Cast ``"now"`` as a ``datetime``; pass ``_tzinfo`` for zone-less
  ``struct_time``.

- Gracefully parse missing indexes; use the correct command help text.

v0.72.0 (2026-08-03)
--------------------

New
~~~

- Added sub-module looping (per-parent loop semantics).

- Added async pubsub and async pipe compilation.

- Added split-module compilation support.

Changes
~~~~~~~

- **Replaced Twisted with AnyIO** as the async runtime. Twisted is no longer
  imported or importable; ``riko.bado`` now runs on AnyIO. See the
  "Twisted replaced by AnyIO" note in ``docs/MIGRATION.rst``.

- Made the compact loop form canonical and document loop behavior.

- Emitted lowercase compilation kwargs; use ``int``/``float`` instead of
  ``number``.

- Made ``issync``/``isasync`` public; rename CLIs.

Bugfixes
~~~~~~~~

- Failed ``SyncCollection`` on exception instead of on close.

- Always consume the memoized ``__aiter__``.

v0.71.2 (2026-07-23)
--------------------

Changes
~~~~~~~

- Droped PyPy support and update documentation.

Bugfixes
~~~~~~~~

- Made date parsing deterministic.

- Fixed file resource clean-up.

- Harden feed entry text fallbacks; handle feed entries without
  descriptions.

- Fixed py3.12/py3.13 optional/non-optional CI regressions.

v0.71.1 (2026-07-23)
--------------------

Changes
~~~~~~~

- Bumped pyasn1, soupsieve, and cryptography dependencies.

v0.71.0 (2026-07-21)
--------------------

Changes
~~~~~~~

- **Replaced ``Objconf`` with ``DynamicConf``.** ``Objconf(...)`` becomes a
  compatibility factory (emits ``DeprecationWarning``); it is removed outright in
  a later release. See the "``Objconf`` is removed" note in
  ``docs/MIGRATION.rst``.

- Completed the async lifecycle and source parity; achieve sync/async
  chaining parity.

- Autogenerated ``riko/types/configs.py`` with drift detection.

- Renamed the console script; sort tests into public/internal/functional.

v0.70.0 (2026-07-21)
--------------------

New
~~~

- Dynamically generated modules and metadata (derived module catalog).

- Added bare-bones DAG format with ``convert-dag``/``compile`` CLIs; refactor
  codegen.

Changes
~~~~~~~

- **Established a three-tier public API boundary** (stable ``riko``/``riko.api``,
  extension ``riko.ext``, private ``_*``). See the "Three-tier import surface"
  note in ``docs/MIGRATION.rst``.

- **Added pipe/collection lifecycle** — ``SyncPipe``/``AsyncPipe``/collections
  are now single-execution; re-iteration no longer silently re-runs and
  chaining onto a ``CLOSED``/``FAILED`` pipe raises ``PipelineStateError``.
  See the "Single-execution pipe lifecycle" note in ``docs/MIGRATION.rst``.

- **Converted the ``Context`` describe booleans to an ``ExecutionMode`` enum**
  (``describe_input``/``describe_dependencies`` are now read-only properties).
  See the "ExecutionMode replaces the describe booleans" note in
  ``docs/MIGRATION.rst``.

- Maded ``OperatorReturnKind`` an enum; add inference diagnostics.

- Split ``riko/modules/__init__.py`` into leaf submodules; remove shared
  mutable ``Module`` state.

Security
~~~~~~~~

- Hardened XML parsing against XXE/entity-expansion (disable entity
  resolution, DTD loading, and network access under lxml).

Bugfixes
~~~~~~~~

- Corrected date arithmetic; apply stable sorts in reverse rule order; stop
  equating both-missing values on joins.

- Handled PEP 604 unions in ``fromdict``; clean up worker pools on exit.

- Enforced timeout deadlines on blocking sync reads; treat async ``timeout=0``
  as "no timeout" (consistent with sync).

- Hardened pub/sub ``close``/``send`` against exhausted generators and
  receive-queue overflow; deliver only the kwargs a user ``func`` declares.

- Guarded ``fcntl`` for Windows compatibility.

- Made numerous correctness fixes to casting, iteration, and typing.

v0.69.0 (2026-07-14)
--------------------

Changes
~~~~~~~

- Refactored pipe compilation; centralize caching; intelligently generate
  assignments.

- Replaced ``ItemArg`` with ``Item``.

- Added async timeout parsing.

Performance
~~~~~~~~~~~

- Cached filter rules and ``_from_hashable``; optimize conf, date, and file
  parsing; bypass the cache for dynamic confs.

v0.68.1 (2026-07-13)
--------------------

Bugfixes
~~~~~~~~

- Fixed remaining lint errors; correct the ijson version spec.

v0.68.0 (2026-07-13)
--------------------

New
~~~

- Added pub/sub, ``fetchtable``, the ``aggregate`` pipe, pipe exporting, and
  async URL encoding/decoding.

Changes
~~~~~~~

- Major refactor: enabled pipeline compilation; go all-in on ``uv``; move
  dependencies to ``pyproject.toml``.

- Migrated the test suite to pytest; deprecate Python 2.

Bugfixes
~~~~~~~~

- Returned ``unique_everseen`` elements; improve RSS pub/upd and field/value
  parsing.

v0.67.0 (2026-07-13)
--------------------

Changes
~~~~~~~

- Bumped minimum supported version to Python 3.7; add black and a prettify
  command.

Bugfixes
~~~~~~~~

- Properly added setup requirements; clean up docblocks.

v0.66.0 (2020-08-14)
--------------------

Changes
~~~~~~~

- Made ``skip_if`` searching case insensitive.

Bugfixes
~~~~~~~~

- Removed an unused import.

v0.65.0 (2020-08-14)
--------------------

New
~~~

- Added a user-defined operator.

Bugfixes
~~~~~~~~

- Fixed typos.

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

- Fixed lint errors.

v0.62.1 (2020-07-30)
--------------------

Bugfixes
~~~~~~~~

- Update the language identifier.

Documentation
~~~~~~~~~~~~~

- Corrected the ``kazeeki`` pipe example.

v0.62.0 (2020-07-29)
--------------------

Bugfixes
~~~~~~~~

- Added tests and generalize the cast fix so casting no longer crashes.

- Corrected the ``skip_if`` logic for the text key.

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

- Added a default user agent for ``urlopen`` HTTP requests.

Documentation
~~~~~~~~~~~~~

- Added an XML namespace warning.

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

- Removed Python 2 support; upgrade dependencies.

Bugfixes
~~~~~~~~

- Catch ``StopIteration`` exceptions.

Documentation
~~~~~~~~~~~~~

- Fixed a broken link to ``reverse``.

v0.60.4 (2018-09-13)
--------------------

Bugfixes
~~~~~~~~

- Corrected a syntax error.

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

- Added the URL to ``urllib`` exceptions.

v0.59.1 (2018-05-19)
--------------------

Bugfixes
~~~~~~~~

- Fixed boolean type casting.

v0.59.0 (2018-05-18)
--------------------

New
~~~

- Added a ``name`` attribute to ``async_url_open``.

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

- Added cache metadata to ``memoize`` and ``fetch``.

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

- Removed Python 3.4 support and upgrade PyPy versions; upgrade ``mezmorize``.

v0.52.3 (2017-08-12)
--------------------

Changes
~~~~~~~

- Upgrade ``chardet``.

v0.52.2 (2017-08-11)
--------------------

Bugfixes
~~~~~~~~

- Fixed ``pgrep`` to work on Heroku instances.

v0.52.1 (2017-08-09)
--------------------

Bugfixes
~~~~~~~~

- Fixed a lint error.

v0.52.0 (2017-08-09)
--------------------

New
~~~

- Added more cache types.

Bugfixes
~~~~~~~~

- Fixed a bug when the new month isn't in 1..12; use ``Clock`` to manage
  ``FakeReactor`` timing (closes #37).

Documentation
~~~~~~~~~~~~~

- Update the contribution documentation.

v0.51.0 (2017-05-01)
--------------------

New
~~~

- Added ``takewhile`` functionality to the ``filter`` pipe.

Changes
~~~~~~~

- Set a default memcache server.

v0.50.0 (2017-04-12)
--------------------

New
~~~

- Added the ``timeout`` pipe.

- Added options to specify the cache, namespace, and cache backend.

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

- Fixed spacing.

v0.49.0 (2017-04-09)
--------------------

New
~~~

- Added RSS caching.

Bugfixes
~~~~~~~~

- Fixed caching.

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

- Added currency symbol unicode values.

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

- Fixed a syntax error; cast parts to strings before joining; use the correct
  import; don't convert input to text.

Documentation
~~~~~~~~~~~~~

- Update documentation.

v0.45.0 (2017-04-01)
--------------------

New
~~~

- Added the ``typecast`` pipe.

v0.44.0 (2017-04-01)
--------------------

Changes
~~~~~~~

- Removed the ``lib`` directory and parse timezones.

v0.43.1 (2017-03-24)
--------------------

Bugfixes
~~~~~~~~

- Fixed Python 2 tests; remove a duplicate key.

v0.43.0 (2017-03-24)
--------------------

New
~~~

- Added the ``geolocate`` pipe.

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

- Added new pipes; add a debugging option.

Changes
~~~~~~~

- Renamed ``stringtokenizer`` to ``tokenizer``; rename functions; move
  ``invert_dict`` and move/rename ``entity2text``.

v0.38.0 (2017-03-10)
--------------------

New
~~~

- Added the ``eq`` operator to the ``filter`` pipe; add the ``fetchtext`` pipe.

Changes
~~~~~~~

- Added more logging.

Bugfixes
~~~~~~~~

- Use ``cElementTree`` when available; initialize ``self.entry`` as an iterator.

v0.37.0 (2016-09-29)
--------------------

New
~~~

- Added a lowercase transformation to the ``join`` pipe.

v0.36.0 (2016-09-29)
--------------------

New
~~~

- Added the ``join`` pipe; add the ``sum`` pipe.

Bugfixes
~~~~~~~~

- Correctly parse the XML path.

Documentation
~~~~~~~~~~~~~

- Added more links to the documentation.

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

- Fixed makefile lint command. [Reuben Cummings]

- Update pygogo requirement (fixes #2) [Reuben Cummings]

v0.35.0 (2016-07-19)
--------------------

New
~~~

- Limit the number of unique items tracked. [Reuben Cummings]

- Added grouping ability to count pipe. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fixed processor metadata. [Reuben Cummings]

v0.34.0 (2016-07-19)
--------------------

New
~~~

- Added list element searching to microdom. [Reuben Cummings]

- Added more operations to filter pipes. [Reuben Cummings]

Changes
~~~~~~~

- Merge async_pmap and async_imap. [Reuben Cummings]

- Change deferToProcess name and arguments. [Reuben Cummings]

- Renamed modules/functions, and update docs. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Force getElementsByTagName to return child. [Reuben Cummings]

- Only use FakeReactor when actually needed. [Reuben Cummings]

- Fixed async html parsing. [Reuben Cummings]

- Prevent IndexError. [Reuben Cummings]

- Fixed async opening of http files. [Reuben Cummings]

- Be lenient with html parsing. [Reuben Cummings]

- Fixed empty xpath and start value bugs. [Reuben Cummings]

v0.33.0 (2016-07-01)
--------------------

Changes
~~~~~~~

- Major refactor for py3 support: [Reuben Cummings]

  - Fixed py3 and open file errors
  - port missing twisted modules
  - refactor RSS parsing
  - and streaming json support
  - Renamed request function
  - Made benchmarks.py a script and add to tests

Bugfixes
~~~~~~~~

- Fixed pypy test errors. [Reuben Cummings]

v0.32.0 (2016-06-16)
--------------------

Changes
~~~~~~~

- Refactored to remove Twisted dependency. [Reuben Cummings]

v0.31.0 (2016-06-16)
--------------------

New
~~~

- Added parallel testing. [Reuben Cummings]

v0.30.2 (2016-06-16)
--------------------

Bugfixes
~~~~~~~~

- Added missing optional dependency. [Reuben Cummings]

v0.30.1 (2016-06-16)
--------------------

Bugfixes
~~~~~~~~

- Fixed failed test runner. [Reuben Cummings]

- Fixed lxml dependency errors. [Reuben Cummings]

v0.30.0 (2016-06-15)
--------------------

New
~~~

- Try loading workflow from curdir first. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fixed remaining pypy errors. [Reuben Cummings]

- Fixed “newdict instance” error for pypy. [Reuben Cummings]

- Added detagging to `fetchpage` async parser. [Reuben Cummings]

v0.28.0 (2016-03-25)
--------------------

New
~~~

- Added option to specify value if no regex match found. [Reuben Cummings]

Changes
~~~~~~~

- Made default exchange rate field ‘content’ [Reuben Cummings]

- Split now returns tier of feeds. [Reuben Cummings]

Bugfixes
~~~~~~~~

- Fixed test mode for input pipe. [Reuben Cummings]

- Fixed terminal parsing. [Reuben Cummings]

- Fixed input pipe if no inputs given. [Reuben Cummings]

- Fixed sleep config. [Reuben Cummings]

- Fixed json bool parsing. [Reuben Cummings]


