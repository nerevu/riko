Changelog
=========

v0.78.0 (Unreleased)
--------------------

New
~~~

- Added ``riko.Pipeline``, an immutable, runnable workflow. Start one with
  ``Pipeline.from_module`` or ``Pipeline``. Run it with ``pipeline(items)``.
  ``pipeline.first(items)``/``.afirst(items)`` read one item. Iterate a run with ``for``
  or ``async for``. A pipeline starting from a source module runs with no items
  (``list(pipeline)``). ``pipeline.open(items)`` returns a context manager you can
  iterate via (``with``/``async with``). Leaving the ``with`` block closes the run.

  Chain a module by attribute (``pipeline.sort``), or name via ``pipeline.pipe(name)``/
  ``pipeline | name``. ``pipeline.map(fn)`` appends a ``riko.ext.CallableNode`` that
  applies a callable to each item. ``pipeline.with_context`` sets the ``Context``,
  ``.with_resource`` provides a resource, and ``.replace(…)`` swaps the workflow. For
  parallel runs, set ``pipeline.with_execution(concurrency=…`` to ``"auto"`` or > 1.

- Added ``riko.Resource`` for use with ``pipeline.with_resource``. ``Resource(…)`` owns
  an existing value and closes it with ``cleanup`` or the value's own ``close``.
  ``Resource.from_external`` shares a value you manage, ``Resource.from_factory`` calls
  either a generator/context-manager factory, or a factory with an explicit ``cleanup``,
  and ``Resource.from_lifecycle`` enters a generator/context manager. ``from_external``
  and ``from_factory`` return a ``ReusableResource``, which a ``Context`` can hold.
  ``Resource(…)`` and ``from_lifecycle`` return a ``OneShotResource``, which a
  ``Context`` rejects. ``resource.strategy`` names how riko acquires a resource.

- Added the ``Workflow`` graph (``Node``, ``Edge``, ``Endpoint``) that a ``Pipeline``
  runs. ``Workflow.parse`` reads a workflow document (``riko.WorkflowDocument``: its
  JSON form), a bare-bones DAG (``riko.types.PipeDag``), or a pipe definition
  (``riko.types.PipeDef``). ``Workflow.load`` reads any ``riko.DocumentShape`` from a
  file, and ``flow.serialize`` writes a ``WorkflowDocument``. ``flow.with_node(node)``
  appends a node, and ``flow.with_workflow(other)`` appends a workflow.

- Added ``riko.WorkflowLike`` to annotate what ``riko.compile_workflow`` accepts, and
  ``riko.WorkflowModule`` to annotate the workflow module (Python module source ``str``)
  it returns. Added to ``riko.types``: ``RawWorkflow``/``RawEndpoint``/``RawNode``/
  ``RawEdge`` to annotate workflows; ``PipeDefLike`` for a ``PipeDef`` or similar
  mapping; ``InputLike`` for what a pipeline runs on; ``PipelineStream``/``PipelineRun``
  for what ``pipeline(items)``/``pipeline.open(items)`` returns; and ``RawCallOptions``/
  ``CallOptions``/``CallOptionsLike`` for a module's call options (``options=``).

- ``run-pipe`` can now run a ``WorkflowDocument`` (``run-pipe -p flow.json``, or an
  example id) or a ``WorkflowModule`` file directly, alongside the pipe scripts (Python
  files defining ``pipe(test=False)``) it already ran. ``-t`` reaches a
  ``WorkflowDocument`` and a ``WorkflowModule`` with a ``workflow``-decorated ``pipe``
  (e.g., ``compile-workflow`` output).

- A ``PipeDag`` wire can now name an entry port as the third list item, e.g.,
  ``["b", "u", "in:1"]``, which removes the need for hand-written ``Workflow``\s for
  fan-in operators such as ``union`` and ``join``, and a ``PipeDag`` ``modules`` entry
  can name its module with ``name`` (e.g., ``{"name": "fetch"}``), like a workflow node.
  If providing both ``type`` and ``name``, they must agree.

- Every riko logger is now a child of the ``"riko"`` logger, so
  ``logging.getLogger("riko").setLevel(...)`` sets the level for all of them.

- Added ``riko.PipelineError``, ``riko.InvalidPipelineError``, and
  ``riko.EmptyPipelineError``.

- Added ``normalize_workflow`` (``WorkflowLike`` -> ``Workflow``), ``migrate_v1_to_v2``
  (``PipeDef`` -> ``Workflow``), the node and edge classes (e.g., ``ModuleNode``), and
  the write-target classes (e.g., ``FileTarget``) to ``riko.ext``.

- Extension authors can register a workflow store, a package of ``pipe_<id>.py`` files
  (saved ``WorkflowModule``\s) or a directory of ``pipe_<id>.json``
  ``WorkflowDocument``\s, via ``register_workflow_store``. ``Target``\s, keyed by a
  ``riko.Backends`` member, register via ``register_target``, which also works as a
  class decorator. ``reset_target_registry`` and ``reset_workflow_resolver`` undo those
  registrations. ``riko.ext.Dispatcher`` is the protocol that finds a module's or stored
  workflow's pipe by name.

- Module pipe callables gained ``prepare``. It applies a call's configuration and call
  options for reuse over items. ``riko.ext.PreparedCall`` annotates its return value.

- Added ``ModuleMetadata.provider`` and ``list_modules(provider=…)``. A module's provider
  is the first dotted segment of its name (``"riko"`` for the built-ins). Each provider
  gets its own discovery class, with the prefix left off its members: ``example.lookup``
  is ``Example.LOOKUP``, and ``Modules.EXAMPLE_LOOKUP`` keeps the full name.

- Added to ``riko``: ``async_chain`` to chain async iterables, ``alist`` to collect an
  (a)sync iterable into a list, ``materialize`` to collect one into an iterator, and a
  ``cooperative`` option to ``as_async`` to yield control between item iterations.

- Added ``jsonl`` (newline-delimited JSON) to ``riko.Formats``.

- Added environment variables to override runtime defaults: ``RIKO_CONCURRENCY_LIMIT``,
  ``RIKO_STREAMING_THRESHOLD``, ``RIKO_ENCODING``, ``RIKO_DISCOVERY_TIMEOUT``,
  ``RIKO_EXCHANGE_API``, ``RIKO_NODE_THREADS``, ``RIKO_PARSED_DATE_CACHE_SIZE``, and
  ``RIKO_SHIPPED_CALL_CACHE_SIZE``.

Changes
~~~~~~~

- ``Context`` is now a fully immutable snapshot, including nested ``inputs`` values.
  Derive a changed context with ``replace`` instead of direct assignment. A frozen
  mapping, such as ``Context(inputs=…).inputs``, is hashable when its values are, and
  merges with ``|`` into a new frozen mapping.

- The fetch modules (``fetch``/``fetchdata``/``fetchpage``/``fetchtable``/``fetchtext``/
  ``fetchsitefeed``) now raise when a URL can't be opened, e.g., a ``URLError`` for a
  missing file, instead of logging an error and yielding empty content.

- ``Context().inputs`` is now ``None`` when no input values are given, rather than an
  empty mapping. An ``input`` module still prompts when no input values are given, but
  an explicit ``inputs={}`` now uses each input's default instead of prompting.

- ``riko.PipelineStateError`` names the errant object (e.g., a write session) instead of
  calling it a pipe, and its constructor requires the ``subject`` keyword argument.

- Renamed ``convert-dag`` to ``build-workflow``, which now emits a ``WorkflowDocument``
  instead of a serialized ``PipeDef``. It reads a path to a ``WorkflowDocument``, or a
  serialized ``PipeDag`` or ``PipeDef`` with auto detection. Use ``--format
  {dag,v1,v2}`` to pin a format, and ``--compact`` to write a minified output.

- Renamed ``compile-pipe`` to ``compile-workflow`` and ``riko.compile_pipe`` to
  ``compile_workflow``. ``compile-workflow``, ``run-pipe``, and workflow stores take a
  ``WorkflowDocument``, not a serialized ``PipeDef``. Convert one with
  ``build-workflow`` (or a ``PipeDef`` with ``migrate_v1_to_v2``) first.

- A workflow module's ``pipe`` now returns ``{"inputs": ..., "dependencies": [...]}``
  under ``Context(mode=ExecutionMode.DESCRIBE)`` instead of the input declarations
  alone, and its ``async_pipe`` yields that mapping as its single item.
  ``DESCRIBE_INPUTS`` now returns the workflow's input declarations as a
  ``{name: schema}`` mapping instead of a list of tuples scanned from ``input``
  modules, so a migrated ``PipeDef`` reports none until it declares them.

- Moved ``examples/pipelines`` to ``examples/workflows`` and ``examples/pypipelines`` to
  ``examples/pyworkflows``. The JSON files are now ``WorkflowDocument``\s instead of
  serialized ``PipeDef``\s.

- Renamed ``riko.UnsupportedPipelineError`` to ``riko.UnsupportedWorkflowError``, and
  added a ``reason`` attribute to it and ``UnsupportedModuleError``. Its ``pipe_id`` now
  holds the ``pipe_<id>`` form, even when the name was given as ``pipe:<id>``.

- ``run-pipe`` reports any riko error, such as an unknown module, as a one-line message
  and exits with status 1 instead of printing a traceback.

- Calling a workflow module's ``pipe()`` without items, when the workflow doesn't start
  with a source module, now raises ``riko.InvalidPipelineError`` instead of feeding its
  first module ``None`` and yielding nothing. Pass items instead, e.g., ``pipe(items)``.

- ``ModuleDefinition`` is no longer a dataclass. Change one with ``attrs.evolve``
  instead of ``dataclasses.replace``. Its constructor is now keyword-only. ``name``
  returns the module's effective name: the ``name`` passed, or else the pipe callable's
  name. The exact name as given is now ``declared_name``. ``get_pipe(interface)`` is now
  ``get_pipe(is_async=False)``, and the new ``interfaces`` names the callables it
  provides (``"pipe"``/``"async_pipe"``).

- ``ModuleDefinition.from_module(module, name=…, description=…)`` replaces
  ``ModuleDefinition(module=…)``. It reads the Python module's ``pipe``, ``async_pipe``,
  name, and docstring summary. Changing the Python module afterwards no longer changes
  the definition. Removed ``ModuleDefinition.module``, and used the Python module's name
  for ``ModuleDefinition.declared_name``. A ``from_module`` definition named by an entry
  point must pass ``name=`` matching the entry-point key.

- Registering a module under the name of a built-in or entry-point module raises
  ``ValueError`` unless you pass ``replace=True``.

- Made ``ModuleRegistry.registered_names()`` a property (drop the parentheses). Moved
  ``catalog_names()`` to ``discovered_names`` (also a property).

- Declaring the same ``riko.modules`` entry-point name in two plugins now raises
  ``ValueError`` on module resolution instead of picking the last-discovered module.

- ``get_module_metadata(name)`` returns ``None`` for an unknown module instead of
  raising ``ModuleNotFoundError``. With ``strict=True`` it raises ``ValueError``.

- ``ModuleRegistry.resolve(name, interface)`` is now ``require(name, is_async=False)``.
  It returns the module's pipe callable. ``definition`` is now ``load_definition``.
  ``require_interfaces`` reports which of a module's ``pipe`` and ``async_pipe`` exist.

- An unknown module name now raises ``UnsupportedModuleError`` with a did-you-mean hint
  naming candidate modules. The error's ``matches`` attribute carries the hints.

- ``ModuleMetadata.subtypes`` and the ``subtypes`` stamped on a pipe callable are now a
  ``frozenset``. Mutating a metadata record's subtypes used to change the module's
  discovery metadata.

- ``@processor``, ``@operator``, and ``@splitter`` now work without parentheses. They
  also raise ``TypeError`` at decoration time for an invalid option (e.g., a typo or a
  call option like ``count``) or for a function passed together with options.

- Renamed the ``processor``, ``operator``, and ``splitter`` decorators ``parse`` method
  to ``normalize_input``; and ``operator.aparse`` to ``operator.anormalize_input``.

- An async operator's ``async_pipe`` now returns an async iterator directly. Consume it
  with ``async for``/``anext`` without awaiting the call first. Async processors and
  splitters are unchanged.

- A module's pipe callable now parses ``conf`` on every call. To parse ``conf`` once,
  prepare the configuration with ``pipe.prepare(conf=…)`` and call that result per item.

- Renamed ``derive_category`` to ``get_module_category``, which no longer takes
  ``provider`` or ``override``, and ``riko.ext.register`` to
  ``riko.ext.register_module``.

- ``riko.types.Feed`` now represents either synchronous or asynchronous item input
  (``Items | AsyncItems``). ``PipeTuples`` is now either the new ``SyncPipeTuples``
  or ``AsyncPipeTuples``. ``Item`` now also covers items with nested list or mapping
  values, so annotating one no longer fails type checking.

- Renamed ``get_async_temp_file`` to ``async_get_temp_file``.

- Renamed ``riko.Targets`` to ``Formats`` (its members name serialization formats) and
  ``riko.list_targets`` to ``riko.list_formats``. ``Formats`` drops the ``LIST`` and
  ``TUPLE`` members (they aren't serialization formats); ``riko.export`` still takes the
  bare ``"list"`` and ``"tuple"`` strings.

- An invalid ``Formats`` or ``ExecutionMode`` choice is rejected with an error that
  lists the accepted values, e.g., ``Invalid ExecutionMode: 'bogus'. Expected one of
  run, describe_inputs, describe_dependencies, describe``.

- Renamed ``riko.async_map``'s ``connections`` parameter to ``limit``.

- Renamed the ``urlparse`` module's ``parse_key`` configuration to ``normalize_key``.
  ``parse_key`` is ignored and results will land under ``content``.

- The ``write`` module's ``url`` and ``target`` configuration keys are now ``dest`` and
  ``fmt``. A configuration that still uses ``url`` logs a warning and writes nothing.

- The ``sort`` module now places items lacking the sort field together. Previously a
  missing field sorted using the type's default (e.g., ``0`` for ``int``, ``-inf`` for
  ``float`` and dates). A rule's new ``default`` sets the value such an item sorts by,
  cast like any other value (``{"field": "n", "type": "int", "default": 0}``). A rule
  without a ``type`` no longer raises ``TypeError`` when some items lack the field and
  the rest hold dates or numbers.

Removed
~~~~~~~

- Removed ``SyncPipe``, ``AsyncPipe``, ``SyncCollection``, ``AsyncCollection``, and
  ``PipeState``. ``Pipeline`` replaces them: ``list(pipeline)`` replaces ``.list``,
  ``export(pipeline, …)`` replaces ``.export``, and multi-source fetching is now a
  ``union`` fan-in in a ``Workflow``. ``pipeline.map(func)`` replaces
  ``SyncPipe(Transforms.UDF, func=…)``, and ``pipeline.sort(conf=conf)`` replaces
  ``pipe | ("sort", conf)``. ``subscribe``/``publish``/``split`` have no replacement.

- Removed call-time decoration options. Passing ``skip_if``, ``ftype``, ``ptype``,
  ``extract``, ``listize``, ``objectify``, ``parse``, or ``pollable`` to a module call
  now raises ``TypeError``. Set them in the decorator, e.g., ``@processor(skip_if=…)``.

- Removed ``parallel``/``workers``/``threads``/``pool`` arguments. Run items in
  parallel with ``pipeline.with_execution`` instead.

- Removed ``build_pipeline``, ``parse_pipe_def``, and ``extract_dependencies``. Convert
  a ``PipeDef`` with ``migrate_v1_to_v2`` to create a ``Workflow``, then run it with
  ``Pipeline`` or read its modules from ``nodes``.

- Removed ``convert_dag``. ``Workflow.parse`` reads the same ``PipeDag`` into a
  ``Workflow`` rather than a ``PipeDef``.

- Removed the ``submodule`` and ``verbose`` attributes and keyword arguments from
  ``Context``. Set the level on the ``"riko"`` logger instead.

- Removed ``autorss``, ``cast``, ``collections``, ``compile``, ``context``,
  ``currencies``, ``dates``, ``dotdict``, ``exceptions``, ``locations``, ``parsers``,
  ``paths``, ``pprint2``, ``topsort``, ``bado.io``, ``ext.names``, and ``types.compile``
  from ``riko``. ``CastType`` is now on ``riko`` and ``normalize_module_name`` on
  ``riko.ext``. Everything else they held is private, with no public replacement.

- Removed the ``config``, ``decorators``, ``protocols``, and ``registry`` Python modules
  from ``riko.ext``. Every name they held is already on ``riko.ext`` (``reset_registry``
  as ``reset_module_registry``), except ``Feed``, ``Stream``, ``AsyncStream``, and
  ``AsyncItems``, which are on ``riko.types``.

- Secondary namespaces no longer re-export names another package owns: import
  ``processor``, ``operator``, ``splitter``, and ``DynamicConf`` from ``riko.ext`` (not
  ``riko.modules`` or ``riko.types``), and ``async_url_open``, ``async_write``, and
  ``async_get_temp_file`` from ``riko`` or ``riko.io`` (not ``riko.bado``).

Fixes
~~~~~

- riko's errors now survive pickling and copying, so one raised in a worker process
  reaches the caller intact. Errors also no longer repeat their message.

- Concurrent async fetches no longer drop legitimate ``None`` results.

- Fetching (e.g., with ``fetchpage``) text with no newline or only carriage-return line
  endings in a sync run no longer inserts a newline between every character or drops
  blank lines. The ``fetchdata`` module now parses such XML instead of raising
  ``XMLSyntaxError``; ``fetchdata``, ``fetchpage``, ``xpathfetchpage``, and ``csv``
  yield content instead of nothing; and the ``fetchtext`` module preserves blank lines.

- Fetching multi-line UTF-16 text in a sync run no longer drops everything after the
  first line, and fetching empty text yield nothing instead of raising ``RuntimeError``.

- A decode failure while fetching in a sync run no longer leaves the response open.

- Fetching in a sync run and ``riko.get_path`` now treat a ``url`` with any scheme
  (e.g., ``ftp://``) as given instead of as a file name.

- The ``fetchdata`` module now yields a dict instead of text for XML whose root holds
  only text. And in an async run it no longer raises ``TypeError`` when ``path`` isn't
  set. It yields the whole document, like a sync run.

- An async run or ``riko.async_map`` call whose single task fails now raises that error
  instead of wrapping it in an ``ExceptionGroup``.

- A workflow's modules now run in the same order on every run.

- Assignment to a dotted field (e.g., ``assign="author.uri"``) no longer changes nested
  dicts of a module's input items, and each assignment now takes constant time no matter
  the item's number of fields.

- ``@operator`` now gives the reason it can't classify a parser's return type. E.g.,
  return annotation of ``Any`` is too broad.

- The result of an async processor or splitter is now typed as both awaitable and async-
  iterable. ``async for item in async_pipe(...)`` no longer fails type checking.

- ``key in conf`` on a parsed module configuration now reports False for missing keys.

- A dotted ``item["a.b.c"]`` on a ``DotDict`` now walks nested mappings
  case-insensitively and fully resolves, like ``item.get("a.b.c")`` already does.

- ``key in item`` on a ``DotDict`` returns False for non-string keys instead of raising.

- The ``extract`` decoration option now finds its conf key case-insensitively.

- A conf ``type`` or an ``ftype``/``ptype`` decoration option that is not a ``CastType``
  now logs one warning and passes the value through unchanged, wherever it appears.

- ``aclose``ing an ``async_map_stream`` after a partial read now stops its workers and
  closes its input stream instead of raising a cancel-scope error or leaving it open.

- Modules now yield items for an async secondary input stream (e.g., a ``union``'s
  ``others``) in an async run instead of raising a not-iterable error.

- The ``write`` and ``aggregate`` modules now accept an async input stream in an async
  run instead of raising a not-iterable error. A sync ``aggregate`` ``func`` receives
  the collected items. An async one receives the async stream.

- The ``write`` module can now write nested objects using the ``json`` export format
  instead of raising "Object of type DotDict is not JSON serializable".

- In an async run, the ``write`` module now writes ``ofx`` and ``qif`` output instead of
  raising ``TypeError``. Sync/async runs no longer warn "produced unwritable content".

- ``async_write`` accepts a list or iterator of ``str`` or ``bytes`` chunks, as
  documented, instead of raising ``AttributeError``.

- ``export`` now takes writer options as keyword-only arguments and passes the rest to
  the format's converter. Before, keywords went to both and could raise ``TypeError``.
  A writer option given without ``f`` now raises ``TypeError`` instead of being ignored.

- Writing or exporting an empty stream as ``geojson`` produces a ``FeatureCollection``
  with no features instead of raising ``ValueError``.

- ``json`` output writes sets as deterministic sorted arrays.

- ``skip_if`` now treats a missing ``text`` as a presence check on ``field`` instead of
  matching against the string ``"None"``. An absent field skips and a ``text`` of
  ``None`` or ``0`` no longer misfires.

- ``listize`` now wraps falsy extracted values, e.g., ``0`` or ``""``, instead of
  passing them through unwrapped.

- The ``loop`` module now prepares its embedded module per stream instead of per item.

- A ``filter`` rule with a relative date (e.g., ``"today"`` or ``"now"``) now resolves
  the date on every evaluation instead of reusing the value from its first evaluation.

- The ``sort`` module now sorts numeric strings in numerical instead of lexicographical
  order.

- Pure-Python ``feedparser``-based feeds now correctly populate ``description``.

- Unparsable ``feedparser`` feed entry dates (e.g., ``May 11, 2012 10:01:00 EST``) are
  now parsed internally. Sorting on ``pubDate``/``y:published``/``updated_parsed`` no
  longer raises ``TypeError``. If the internal parsers fail to parse, the value is
  skipped with a warning.

- Casting, sorting by, or reading RSS dates from a timezone-aware datetime whose
  ``tzinfo.tzname()`` returns ``None`` now keeps its zone instead of treating the
  datetime as naive.

- Date fields built from a timezone-aware time now report the correct Unix timestamp
  (``utime``); the zone offset was previously ignored.

- Time-zone lookup now captures both the standard and daylight names regardless of the
  current date and resolves ambiguous abbreviations (e.g., ``CST``) toward US zones.

- Parsing a stream of date strings now caches at most ``RIKO_PARSED_DATE_CACHE_SIZE``
  most recent strings instead of every distinct one.

- ``compile-workflow --help`` and its usage errors now show the command's installed name
  instead of ``compile``.

- ``riko.async_url_open``, ``riko.get_path``, and the ``exchangerate`` module's
  ``url`` now treat a file name starting with ``http`` (e.g., ``http_data.csv``) as a
  file instead of a web address.

- Entering one ``async_url_open`` handle with ``async with`` while it is already
  open now raises ``RuntimeError`` instead of leaving the first buffer open.

Dev
~~~

- Added ``--docstrings``, ``--docs``, ``--terms``, ``--deps``, ``--literals``,
  ``--bindings``, ``--tests``, ``--basenames``, ``--escapes``, and ``--all`` to
  ``manage lint``; and ``manage lint imports`` to check the internal import contracts.
  ``manage lint`` no longer takes paths to check.

- Added ``manage test --ratchet``, which fails a full-suite run that leaves more
  statements uncovered than the ceiling recorded in ``pyproject.toml`` and lowers the
  ceiling when it leaves fewer. It and ``manage lint --escapes`` warn, without failing,
  when a ceiling has held longer than ``[tool.riko.ratchet] stale-days``.

- ``manage -v``/``-vv``/``-q`` now set the log level (they previously had no effect).

- ``manage prettify --yaml`` now formats only tracked YAML files (like ``manage lint
  --yaml``) instead of everything under the repository root.

- Added ``manage upgrade`` to upgrade ``uv.lock``, sync the environment, and rewrite
  the pre-commit Ruff pin to the locked version.

- Replaced ``manage codegen --mode`` with the additive ``--config``, ``--names``,
  ``--api``, ``--tests``, and ``--all`` selectors, and removed the ``pipes`` generator
  along with the ``gen-pipelines`` console script. ``--api`` (also the new
  ``gen-api-surface`` script) generates the API-surface document, with a drift guard,
  and ``--tests`` regenerates the test tier indexes.

- ``manage release-notes`` takes an optional version to convert instead of always using
  the latest changelog section.

- Added ``manage backfill`` to dispatch the release or publish workflow for an existing
  tag, with ``--dry-run`` and a ``--notes-only`` mode that replaces a release's
  changelog section while keeping its GitHub-generated notes.

- Added ``manage missing`` to list release tags absent from GitHub or PyPI.

- ``manage publish``/``release --dry-run`` now run a real ``uv publish --dry-run``
  upload rehearsal instead of an import smoke test.

- Pinned GitHub Actions steps to commit SHAs.

- The ``benchmark`` script now times building a ``Pipeline`` and running it instead of
  the ``SyncPipe``/``AsyncPipe`` and ``SyncCollection``/``AsyncCollection`` classes.

- Cleared the outstanding type-checker errors in the I/O and re-encoding paths, and
  dropped the ``cast`` calls that masked them.

- Consolidated and parametrized the test suite, converted the async tests to
  ``async def``, added memory-leak regression tests for ``csv`` and ``fetch``, and
  collected the fixed bugs into a dedicated regression suite.


v0.77.3 (2026-08-31)
--------------------

Dev
~~~

- Added ``manage lint --yaml``/``--actions`` and ``manage prettify --yaml`` to
  lint and format YAML with ``yamlfmt``, ``actionlint``, and ``shellcheck``;
  wired into CI and tox.

- Reformatted workflow and config YAML with ``yamlfmt`` and added a
  ``riko/cli/.yamlfmt`` config.


v0.77.2 (2026-08-31)
--------------------

Dev
~~~

- Set CI ``PYTHONHASHSEED`` and ``pytest-timeout`` to match the tox environment.

v0.77.1 (2026-08-31)
--------------------

Dev
~~~

- Fixed the ``manage release-notes`` CI installation.

v0.77.0 (2026-08-31)
--------------------

New
~~~

- Riko's exceptions now share a ``RikoError`` base, grouped under ``ModuleError``,
  ``PipelineError``, and ``PubSubError``.

- Promoted ``RikoError``, ``as_async``, ``async_map``, and ``async_map_stream`` to the
  top-level ``riko`` surface.

- Added the supported ``riko.types`` surface for annotating code that uses riko:
  ``AsyncStream``, ``Conf``, ``DynamicConf``, ``Feed``, ``Item``, ``Items``,
  ``PipeTuples``, and ``Stream``.

- Promoted ``async_url_open`` onto the top-level ``riko`` surface; it works both as an
  awaitable and as an async context manager (``async with``).

- Added ``url`` as a supported cast target so the ``ftype``/``ptype`` decoration options
  can cast a field to a URL.

- The ``processor``, ``operator``, and ``splitter`` decorators now reject decoration
  options owned by a different decorator (e.g., ``embed`` on ``@processor``, ``skip_if``
  on ``@operator``) with a ``TypeError``.

- A ``riko.modules`` entry point may now name a Python module directly. The registry
  reads its ``pipe``/``async_pipe`` and uses the module docstring summary as the
  description.

- Entry point extensions can now directly name a Python module in place of a
  ``ModuleDefinition``.

Fixes
~~~~~

- The async pub/sub and spool examples no longer leak memory.

- The ``csv`` and ``fetchtable`` modules no longer leak the fetched file when
  ``has_header`` is false and the file is buffered for a second read.

Dev
~~~

- Centralized the various ``skipif(issync)`` test marks into a single ``skipif_issync``.

- Added pub/sub sync/async streaming coverage and strict-xfail tripwire.

- Included the ``examples`` directory in the test suite (doctests and the compiled
  ``pypipelines`` examples).

- Added the ``gen-pipelines`` script (and ``manage codegen --mode pipes``) to recompile
  each ``pipelines/pipe_*.json`` into its ``pypipelines/pipe_*.py`` Python module, in
  both ``examples`` and ``tests``.

- Added CI smoke tests, ``perf``/``finance``/``slow`` test markers, and standardized
  the async test helpers.

- ``manage codegen`` now reports the generated files it writes.

- Made pytest warnings fail so future memory leaks no longer slip through.

- Added the ``manage release-notes`` command to draft release-notes from the changelog.

v0.76.1 (2026-08-28)
--------------------

Dev
~~~

- Upgraded and pinned ``ruff`` (with the accompanying lint/format fixups).

- Fixed a false positive in the docs-consistency test's status-banner matching.

v0.76.0 (2026-08-27)
--------------------

New
~~~

- ``LoopModule.embed`` now uses ``LoopableModuleId``, so embedding a non-loopable module
  in a loop is a static type error.

- Added a **typed module-name discovery surface**. ``riko.Modules`` is a flat namespace
  over every built-in module, and ``riko.Sources``/``riko.Transforms``/``riko.Sinks``
  are ``StrEnum`` groupings by data-flow role. E.g., ``SyncPipe(Sources.FETCH)`` behaves
  like ``SyncPipe("fetch")`` and ``pipe | Modules.FILTER`` like ``pipe.filter()``.

- Added ``category`` filtering (``source``, ``transform``, ``sink``) to
  ``riko.list_modules``.

- Added ``describe_module`` to view built-in's fully populated ``ModuleDefinition``.

- Added ``riko.ext.derive_category`` to get a module's discovery category (``source``,
  ``transform``, or ``sink``).

- Added the ``gen-names`` script (and ``manage codegen --mode names``) to regenerate
  ``riko/modules/_names.py`` from the built-in catalog.

- Added the ``write`` module, a sink that serializes a stream to ``conf['url']`` (a
  ``str`` or ``Path``) with a ``Targets`` converter. ``target`` defaults to the url's
  extension when it names a known converter, else ``json``.

- Added ``riko.async_write`` (anyio-native counterpart of ``meza.io.write``) and
  ``riko.get_async_temp_file`` (async analog of ``get_temp_file``).

- Added ``BasicCastType.DATETIME``, so the ``ftype``/``ptype`` decoration options
  preserve the time of day rather than truncate to a date.

- Added a typed ``riko.Targets`` ``StrEnum`` for ``export``/``write`` formats (``csv``,
  ``geojson``, ``json``, ``list``, ``tuple``, plus ``ofx``/``qif`` with the
  ``finance`` extra).

- ``cast_datetime`` exposes its keyword-only ``try_local_tz``, so a relative date can
  resolve in the local timezone instead of UTC.

- ``compile-pipe`` now reads the ``PipeDef`` (pipe definition) from stdin when the path
  is ``-`` or omitted. It also composes with ``convert-dag`` in a shell pipeline. An
  unreadable or malformed ``PipeDef`` now logs a warning and exits non-zero.

- Added ``-v``/``--verbose`` to ``compile-pipe`` to report the modules used and bytes
  written to stderr.

- Added ``SyncPipe.subscribe`` and ``SyncPipe.publish`` for in-process fan-out.
  ``publish`` both seeds a sender (``SyncPipe.publish(items, "alerts")``) and chains one
  (``pipe.publish("alerts")``).

- The ``udf`` and ``aggregate`` modules now await an async ``func`` in an async run.

- Added ``currencyformat`` conf keys ``locale`` (override the currency's own locale) and
  ``clean`` (render the result's non-breaking space as a plain space).

- ``encoding`` is now a declared conf key for ``fetch``, ``exchangerate``,
  ``fetchdata``, ``fetchpage``, and ``xpathfetchpage``.

Changes
~~~~~~~

- A single-key ``{"value": X}`` mapping is no longer treated as a type/value sentinel,
  so ``DotDict`` leaves it nested instead of unwrapping it to ``X``. Only a mapping
  carrying both ``type`` and ``value`` is unwrapped now.

- The ``currencyformat`` module formats each currency in its own locale rather than
  ``en_US``. E.g., ``EUR`` now renders ``1.000,33 €``. ``CURRENCY_CODES`` entries gained
  ``locale`` and dropped ``decimal_digits``/``rounding``.

- The ``rssitembuilder`` module is now categorized as a ``source`` rather than a
  ``transformer``. It is available as ``Sources.RSSITEMBUILDER``, and its ``assign``
  default is now `"content"`` instead of ``"rssitembuilder"`` (observable with
  ``emit=False``).

- Processors now map over **all** non-mapping iterables (e.g., ``list``/``tuple``), not
  just iterators. Previously, processors treated ``list``/``tuple``/etc. as a single
  value. See the "How does a processor map over items?" FAQ.

- The ``urlbuilder`` module is now categorized as a ``source`` rather than a
  ``transformer``, so it moves to ``Sources`` in the discovery tree and its ``assign``
  default changes from ``"urlbuilder"`` to ``"content"`` (observable only with
  ``emit=False``).

- ``riko.ext.resolver`` and ``riko.ext.pipelines`` are now explicitly private under
  ``riko.ext._resolver`` and ``riko.ext._pipelines``.

Fixes
~~~~~

- In an async run, operators now accept an async input stream (a ``Feed``) instead of
  raising ``TypeError: 'async_generator' object is not iterable``. The ``send`` module
  also completes its receivers when one of them fails.

- A module called without a required operand (e.g., ``udf`` without ``func``, ``send``
  without ``others``) now raises instead of failing later.

- A module whose ``conf`` lacks a required key now raises instead of degrading:
  ``filter``/``refind``/``regex``/``rename``/``strfind``/``strreplace``/``strtransform``
  need a ``rule``, ``itembuilder`` its ``attrs``, and ``strconcat`` its ``part``.

- A source module called without a ``url`` now raises instead of returning an empty
  stream. The ``simplemath`` module requires both ``op`` and ``other`` (and reports an
  unsupported ``op`` clearly rather than raising ``KeyError``), and the ``subelement``
  module requires ``path``.

- The ``csv`` and ``fetchtable`` modules no longer crash with ``has_header=False``,
  which buffers to memory or disk; the default ``has_header=True`` still streams.

- The ``hash`` module now hashes the text form of non-string fields.

- The ``strconcat`` module drops only ``None`` parts, so a falsy part (``0``, ``False``,
  ``""``) is concatenated rather than silently skipped.

- The ``refind`` and ``strfind`` modules now slice the source text at the match position
  instead of splitting and re-joining on the pattern. This fixes ``location="at"`` for
  ``strfind`` (returned ``""``), ``location="before"``/``param="last"`` for  ``refind``
  (re-joined on the regex source), and ``location="at"``/``param="last"`` for ``refind``
  (returned a capture group, not the full match).

- The ``strtransform`` module accepts a list of rule ``args`` instead of raising
  ``AttributeError``, and its ``count``/``find`` transforms may return an ``int``.

- In an async run, the ``fetch`` module now honors ``conf['encoding']``.

- In an async run, the ``fetchdata`` module infers the parse format from the response
  ``Content-Type`` when the url has no extension.

- ``describe_module`` re-raises a nested ``ModuleNotFoundError`` naming the missing
  dependency, instead of returning ``None`` as if the module did not exist.

- Optional conf keys are no longer required by the typed conf contracts. So omitting one
  (e.g., ``sort``'s ``rule``, ``csv``'s ``encoding``) is no longer a pyright error.

- The ``join`` module no longer materializes its primary stream. It only retains and
  replays ``other`` now. It consumes primary streams lazily. Output order is unchanged.

- Modules that read a ``url`` (e.g., ``fetchdata``) now stream the response instead
  of downloading it first, unless ``memoize`` is set. Reading a text resource without
  ``memoize`` no longer fails with ``StopIteration``.

- The ``rename`` and ``regex`` modules no longer create a field the item lacks. They
  skip rules naming absent fields. A field holding ``None`` is still renamed/rewritten.

- ``rssitembuilder``'s ``pubDate`` default is the time the item is built, not the time
  ``riko`` was imported.

- The ``slugify`` module treats a ``None`` ``separator`` as unset and falls back to
  ``"-"`` instead of raising from ``python-slugify``.

- The ``datebuilder`` module now resolves shorthands at call time rather than at import,
  accepts every offset unit (``"2 weeks"``, ``"-1 month"``, ``"30 minutes"``) plus the
  ``"next week"``/``"last month"`` word forms, and raises one clear ``ValueError`` for
  anything it cannot convert. Sub-day offsets such as ``"1 hour"`` were previously read
  as times of day (``01:00`` today).

- ``cast_datetime`` accepts unsigned counts (``"3 days"``, not just ``"+3 days"``) and
  singular units (``"1 week"``), and no longer misreads a three-word string such as
  ``"3 days ago"`` as a future date.

- ``urlbuilder``'s ``param`` is now genuinely optional, and skips ``param`` without a
  ``key``.

- The ``currencyformat`` module yields ``""`` (instead of ``"$NaN.00"``) when the field
  is missing or not numeric to match the other text-producing modules.

- ``tokenizer``'s ``dedupe`` keeps the first occurrence of each token, so the input
  order survives. It is now ``PYTHONHASHSEED`` independent.

- ``tokenizer``'s ``token_key`` now falls back to ``"content"`` instead of raising
  ``TypeError: argument of type 'NoneType' is not iterable``.

- The ``urlbuilder`` module now raises when ``conf`` has no ``base`` instead of putting
  ``"None"`` in the url.

- The ``sort`` module now orders ``float``/``decimal`` fields when some items are
  missing it or hold an unparseable value. The invalid values are sorted as ``-inf``, so
  they appear first when sorting ``asc``.

- The ``dateformat`` module no longer discards the time of day. Its ``ftype`` was
  ``date``, which truncated the field before formatting. A ``datetime`` of ``20:45``
  rendered as ``00:00:00`` under the default ``"%m/%d/%Y %H:%M:%S"`` format and the
  ``%R``/``%I:%M`` specifiers its own docs advertised could never work.

- The ``regex`` module ignores unrecognized rule keys instead of raising.

- Superseded the long-broken ``bin/compile`` script with ``compile-pipe``.

Removed
~~~~~~~

- Removed the ``delay`` conf key from ``fetch`` and ``exchangerate``, along with the
  ``delay`` parameter on ``riko.bado.io.async_url_read``.

- Removed ``send``'s unused ``name`` conf key.

- Removed ``regex``'s ``convert`` and ``singlematch`` conf keys. Neither was read in any
  release.

- Removed the ``loop`` module's dedicated confs (``LoopRawConf``/``LoopConf``), the
  generated ``LoopObjconf``, and the legacy nested ``Embed`` descriptor. The ``loop``
  module has no ``conf`` of its own because it uses the embedded module's ``conf``. The
  embedded module is now set with the compact top-level ``embed`` keyword argument.

Dev
~~~

- ``manage test`` now correctly parses ``stop`` and ``verbose`` options.

- Threaded ``--where`` through ``manage lint --rst`` and ``manage lint``.

- Ported the ``bin/clean`` and ``bin/check-stage`` shell scripts to the ``manage clean``
  and ``manage check`` subcommands.

v0.75.0 (2026-08-15)
--------------------

New
~~~

- Added chaining to allow adding a ``SyncPipe``/``AsyncPipe`` to a pipeline by
  module name. This includes dynamic and dotted identifier names, e.g.,
  ``"microsoft.autopilot.ensure"``:

  - ``pipe | "tokenizer"``, ``pipe | ("tokenizer", conf)``,
    ``pipe | SyncPipe("sort", conf=…)``, and ``items | SyncPipe(...)``
  - ``pipe.pipe(name, conf=…)`` / ``pipe.async_pipe(name, ...)``

- Added a **module registry and entry-point extension seam**. Extension authors can
  register modules with ``riko.ext.register`` or
  ``[project.entry-points."riko.modules"]``. Registered modules resolve like built-ins
  and appear in ``list_modules()``. Registering an existing name raises ``ValueError``
  unless you pass ``replace=True``.

- The ``processor``, ``operator``, and ``splitter`` decorators now infer ``isasync``.
  An async function won't silently become a sync pipe callable if the author forgets
  ``isasync=True``. An explicit ``isasync=True`` is only needed when an ``async_pipe``
  is defined by a sync callable that isn't named ``async_pipe`` (e.g., a lambda), or for
  a typed API such as ``ModuleDefinition(async_pipe=…)``. A function named ``pipe`` that
  resolves async (an ``async def`` or ``isasync=True``) raises a ``TypeError``.

Changes
~~~~~~~

- Renamed the ``SyncPipe``/``AsyncPipe`` ``pool_scope`` value from ``"stage"`` to
  ``"pipe"`` (contrasting with ``"pipeline"``). A per-``pipe`` pool is released after
  each ``SyncPipe``/``AsyncPipe`` iteration and a ``"pipeline"`` pool is shared across
  the run. The default (``"pipeline"``) is unchanged.

- Module resolution now runs through a single compiler-free façade (``riko.ext``
  registry/resolver); runtime module resolution no longer imports the compiler.

- Python modules generated by ``compile-pipe`` now expose stable ``pipe``/``async_pipe``
  callables (instead of a function named after the ``pipe_<id>``), so a ``pipe_<id>``
  name resolves exactly like a built-in module.

v0.74.2 (2026-08-11)
--------------------

Changes
~~~~~~~

- Hardened the release/publish GitHub workflows: set explicit workflow permissions and
  skip re-uploading existing PyPI artifacts.

- Added ``pygments`` to the dev dependencies (RST linting).

Fixes
~~~~~

- Verified ``xpath`` strips XML namespaces (#20); moved content re-encoding into
  ``riko/_reencode.py`` and simplified the parsers.

v0.74.1 (2026-08-10)
--------------------

New
~~~

- Promoted ``async_return`` and ``async_sleep`` to the stable top-level ``riko`` API, so
  async module code and doctests import their helpers (and ``run``) from ``riko`` rather
  than ``riko.bado``.

Fixes
~~~~~

- ``manage test`` now correctly reads the ``cov`` flag (not ``cover``), so
  ``--cov=riko`` coverage works.

- Added ``riko.ext.ModuleName``, a deliberately empty ``StrEnum`` base for typed
  module-name discovery, plus ``normalize_module_name`` and the ``ModuleNameLike``
  alias. A user-defined ``ModuleName`` subclass (e.g.,``class MyModules(ModuleName)``)
  is now accepted anywhere a module name is (e.g., ``SyncPipe(MyModules.FETCH)``).

Documentation
~~~~~~~~~~~~~

- Corrected processor module docstrings: import ``run`` from ``riko`` and document the
  accepted ``item`` type as ``dict or Iter[dict]``.

- Converted ``docs/DAG_FORMAT`` to reStructuredText and folded ``API_STABILITY`` into
  the migration guide.

- Relocated internal planning docs (``ROADMAP`` and the gameplans) out of the user-
  facing ``docs/`` tree; streamlined a Cookbook example and backfill the changelog.

v0.74.0 (2026-08-06)
--------------------

New
~~~

- Added ``run-pipe --path`` for executing a pipe script from an arbitrary file.

- Added pipe definition compilation helpers: ``parse_pipe_def``, ``build_pipeline``,
  ``extract_dependencies``, ``compile_pipe``, and ``get_module_metadata``.

Changes
~~~~~~~

- Renamed ``riko.compile.compile`` to ``riko.compile.compile_pipe`` so it no longer
  shadows the builtin ``compile``.

- Added ``manage lint --rst`` to render every RST document and validate its internal
  links; run it under ``tox -e lint`` and in CI.

- ``manage test`` and ``manage lint`` now accept multiple paths.

Documentation
~~~~~~~~~~~~~

- Fixed the Cookbook ``split`` memory note, the README ``tokenizer``/``hash`` examples,
  and malformed tables in the FAQ and migration guide.

- Cleaned up the ``feedautodiscovery`` module description.

v0.73.1 (2026-08-06)
--------------------

Documentation
~~~~~~~~~~~~~

- Corrected and reorganized the README, Cookbook, FAQ, installation, migration,
  contribution, and credits documentation.

v0.73.0 (2026-08-05)
--------------------

Legacy removal: the ``legacy`` branch is the ``v0.72.x`` release; these are the
changes on top of it.

Changes
~~~~~~~

- **Removed the legacy nested-loop JSON shape** (a ``loop`` module carrying its
  submodule under ``conf["embed"]["value"]``) and its input converter. The
  canonical forms are the compact loop (top-level ``embed``) and, for processor
  loops, a direct node. The terminal ``output`` node marker is retained; only its
  treatment as a resolvable virtual module was removed.

- **Removed the legacy ``Context`` describe keyword arguments** (``describe_input=`` /
  ``describe_dependencies=`` and the ``_mode_from_kwargs`` translation). The old keyword
  arguments now fall through ``**kwargs`` and are silently ignored, leaving
  ``mode=ExecutionMode.RUN``. Pass ``mode=ExecutionMode.DESCRIBE_INPUTS`` /
  ``DESCRIBE_DEPENDENCIES`` / ``DESCRIBE`` instead; the derived read-only properties are
  kept.

- **Removed ``Objconf`` entirely** (it was a deprecated factory in ``v0.72.0``).
  Import ``DynamicConf`` from the supported ``riko.ext`` surface.

- Promoted ``get_path`` into the stable surface (``riko.__all__``); cleaned up the
  public API surface.

- Completed async parity: added lazy async streams and structured pool execution;
  split ``helpers.py`` / ``utils.py`` into focused private Python modules.

Removed
~~~~~~~

- Removed legacy top-level compatibility imports that were outside ``riko.__all__``:
  ``Objectify`` / ``objectify`` moved to ``riko._objectify``, ``listize`` moved to
  ``riko._iterutils``, ``get_abspath`` moved to ``riko.paths``, and ``replacer`` moved
  to ``riko._strutils``. These homes are private/non-stable; callers should avoid
  depending on them or keep their own compatibility copy.

Fixes
~~~~~

- Unified the HTTP backend regardless of params.

- Preserved falsy non-``None`` typed-sort defaults instead of ``""``; treated falsy
  values as present rather than missing (only ``None`` becomes ``[]`` in ``listize``).

- Distinguished ``list`` vs ``tuple`` in the repr cache and bypassed it for unhashable
  args; supported true union dataclasses.

- Stopped mutating a compiled Python module's ``__name__``.

v0.72.2 (2026-08-05)
--------------------

Changes
~~~~~~~

- Added a GitHub publishing workflow.

Fixes
~~~~~

- Added missing README links and a lint option.

v0.72.1 (2026-08-05)
--------------------

Fixes
~~~~~

- Stopped masking legitimate module import errors.

- Failed gracefully on filter parse errors; raised on unsupported filter operations.

- Preserved falsy non-``None`` ``DotDict`` values; used an empty string for the URL
  cast default.

- Cast ``"now"`` as a ``datetime``; passed ``_tzinfo`` for zone-less ``struct_time``.

- Gracefully parsed missing indexes; used the correct command help text.

v0.72.0 (2026-08-03)
--------------------

New
~~~

- Added sub-module looping (per-parent loop semantics).

- Added async pub/sub, and ``compile-pipe --async`` to generate an async Python module
  from a pipe definition (``PipeDef``).

- Added split-module compilation support.

Changes
~~~~~~~

- **Replaced Twisted with AnyIO** as the async runtime. Twisted is no longer
  imported or importable; ``riko.bado`` now runs on AnyIO. Install the ``async`` extra
  (AnyIO + httpx) to enable async processing; ``backend`` is ``"anyio"`` when it is
  available and ``"empty"`` in a sync-only install. There is no
  ``RIKO_ASYNC_BACKEND`` selector. Code using the old Twisted/``deferred`` API must move
  to native ``async`` / ``await``.

- Application-facing async runtime helpers are re-exported through top-level ``riko``;
  prefer forms such as ``riko.run``, ``riko.backend``, and ``riko.isasync`` over
  backend-specific imports.

- Made the compact loop form canonical and documented loop behavior.

- Emitted lowercase compilation keyword arguments; used ``int``/``float`` instead of
  ``number``.

- Made ``issync``/``isasync`` public; renamed CLIs.

Fixes
~~~~~

- A ``SyncCollection`` whose iteration raises now ends in a ``FAILED`` state instead of
  ``CLOSED``.

- Awaiting an ``AsyncPipe`` or ``AsyncCollection`` after a partial read (or calling
  ``async_pipe`` on a partly read ``AsyncCollection``) now yields the remaining items
  instead of restarting it. Awaiting it again after exhaustion yields nothing.

v0.71.2 (2026-07-23)
--------------------

Changes
~~~~~~~

- Dropped PyPy support and updated documentation.

Fixes
~~~~~

- Made date parsing deterministic.

- Fixed file resource cleanup.

- Hardened feed entry text fallbacks; handled feed entries without descriptions.

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
  a later release. Extension authors should import ``DynamicConf`` from ``riko.ext``.

- Completed the async lifecycle and source parity; achieved sync/async chaining parity.

- Autogenerated ``riko/types/configs.py`` with drift detection.

- Renamed the console script; sorted tests into public/internal/functional.

v0.70.0 (2026-07-21)
--------------------

New
~~~

- Added dynamically generated modules and metadata (derived module catalog).

- Added ``PipeDag`` (bare-bones DAG) format with ``convert-dag``/``compile`` CLIs, and
  refactored codegen.

- Added ``riko.convert_dag`` as the programmatic API for expanding ``PipeDag``
  into a full pipe definition (``PipeDef``).

- Added ``riko.list_targets`` to list the available ``export`` formats.

- Added ``riko.UnsupportedModuleError`` (unknown module name, kept in ``module_name``)
  and ``riko.UnsupportedPipelineError`` (unknown ``pipe_<id>`` name, kept in
  ``pipe_id``).

Changes
~~~~~~~

- **Established a three-tier public API boundary** (stable ``riko``/``riko.api``,
  extension ``riko.ext``, private ``_*``).

- **Added pipe/collection lifecycle** — ``SyncPipe``/``AsyncPipe``/collections are now
  single-execution. Re-iterating an exhausted, closed, or failed pipe yields an empty
  stream rather than re-running it. Chaining is allowed while ``NEW`` / ``RUNNING`` /
  ``EXHAUSTED`` but raises ``PipelineStateError`` on ``CLOSED`` / ``FAILED``. Added the
  ``PipeState`` enum, read-only ``state`` / ``closed`` / ``exhausted`` / ``failed``
  state, sync ``close`` / ``terminate``, async ``aclose``, and context-manager cleanup.

- **Converted the ``Context`` describe booleans to an ``ExecutionMode`` enum**
  (``RUN`` / ``DESCRIBE_INPUTS`` / ``DESCRIBE_DEPENDENCIES`` / ``DESCRIBE``);
  ``describe_input`` / ``describe_dependencies`` are now read-only properties derived
  from ``mode``.

- Made ``OperatorReturnKind`` an enum; added inference diagnostics.

- Split ``riko/modules/__init__.py`` into leaf submodules; removed shared mutable
  ``Module`` state.

Removed
~~~~~~~

- Removed ``riko.bado.return_value`` entirely; use an ordinary ``return`` from async
  functions. ``coroutine`` is not its replacement: it marks pub/sub generator pipelines
  using ``send`` / ``receive`` and is not an async marker.

Security
~~~~~~~~

- Hardened XML parsing against XXE/entity-expansion (disabled entity resolution, DTD
  loading, and network access under lxml).

Fixes
~~~~~

- Corrected date arithmetic; applied stable sorts in reverse rule order; stopped
  equating both-missing values on joins.

- Handled PEP 604 unions in ``fromdict``; cleaned up worker pools on exit.

- Enforced timeout deadlines on blocking sync reads; treated async ``timeout=0``
  as "no timeout" (consistent with sync).

- Hardened pub/sub ``close``/``send`` against exhausted generators and receive-queue
  overflow; delivered only the keyword arguments a user ``func`` declares.

- Guarded ``fcntl`` for Windows compatibility.

- Made numerous correctness fixes to casting, iteration, and typing.

v0.69.0 (2026-07-14)
--------------------

Changes
~~~~~~~

- Refactored pipe compilation; centralized caching; intelligently generated assignments.

- Replaced ``ItemArg`` with ``Item``.

- Added async timeout parsing.

Performance
~~~~~~~~~~~

- Cached filter rules and ``_from_hashable``; optimized conf, date, and file parsing;
  bypassed the cache for dynamic confs.

v0.68.1 (2026-07-13)
--------------------

Fixes
~~~~~

- Fixed remaining lint errors; corrected the ijson version spec.

v0.68.0 (2026-07-13)
--------------------

New
~~~

- Added pub/sub, the ``fetchtable`` and ``aggregate`` modules, stream exporting, and
  async URL encoding/decoding.

- Added ``riko.Context`` to configure a pipeline run.  It specifies ``inputs``,
  ``test``, ``describe_input``, ``describe_dependencies``, ``verbose``, and
  ``submodule`` keyword arguments.

- Added ``riko.compile.parse_pipe_def``, ``build_pipeline``, and
  ``extract_dependencies`` to parse a pipe definition (``PipeDef``), build a runnable
  pipeline from it, and list its dependencies.

Changes
~~~~~~~

- Major refactor: enabled pipeline compilation; went all-in on ``uv``; moved
  dependencies to ``pyproject.toml``.

- Migrated the test suite to pytest; deprecated Python 2.

Fixes
~~~~~

- Returned ``unique_everseen`` elements; improved RSS pub/upd and field/value parsing.

Dev
~~~

- Added ``--dry-run`` to ``manage publish`` and ``manage release`` to check that the
  package installs and imports without uploading it.

v0.67.0 (2026-07-13)
--------------------

Changes
~~~~~~~

- Bumped minimum supported version to Python 3.7; added black and a prettify command.

Fixes
~~~~~

- Properly added setup requirements; cleaned up docblocks.

v0.66.0 (2020-08-14)
--------------------

Changes
~~~~~~~

- Made ``skip_if`` searching case insensitive.

Fixes
~~~~~

- Removed an unused import.

v0.65.0 (2020-08-14)
--------------------

New
~~~

- Added a user-defined operator.

Fixes
~~~~~

- Fixed typos.

v0.64.3 (2020-08-13)
--------------------

Fixes
~~~~~

- Actually pass request params through to the fetcher.

v0.64.2 (2020-08-13)
--------------------

Fixes
~~~~~

- Properly resolve keyword arguments.

v0.64.1 (2020-08-13)
--------------------

Changes
~~~~~~~

- Loosen the ``pytz`` requirement.

Fixes
~~~~~

- Properly pass request params.

v0.64.0 (2020-08-11)
--------------------

Changes
~~~~~~~

- Use a ``LocalProxy`` to return the URL opener, return the content type with the
  response, remove the ``r`` attribute, and make ``ext`` a property.

Fixes
~~~~~

- Get ``fetch`` memoization working.

v0.63.0 (2020-08-11)
--------------------

Changes
~~~~~~~

- Allow skips to contain a callable.

Fixes
~~~~~

- Properly compare integers; use the correct pipe names.

v0.62.2 (2020-07-30)
--------------------

Changes
~~~~~~~

- Fixed lint errors.

v0.62.1 (2020-07-30)
--------------------

Fixes
~~~~~

- Update the language identifier.

Documentation
~~~~~~~~~~~~~

- Corrected the ``kazeeki`` pipe example.

v0.62.0 (2020-07-29)
--------------------

Fixes
~~~~~

- Added tests and generalize the cast fix so casting no longer crashes.

- Corrected the ``skip_if`` logic for the text key.

- Account for ``Deferred`` having no ``close`` method, and for ``MemoryReactor``
  (thus ``MemoryReactorClock``) now implementing ``IReactorCore``.

v0.61.4 (2020-07-29)
--------------------

Fixes
~~~~~

- Correctly set the license.

v0.61.3 (2020-07-29)
--------------------

Fixes
~~~~~

- Update requirements; correct lint errors.

v0.61.2 (2020-07-06)
--------------------

Changes
~~~~~~~

- Set the flake8 max line length equal to black; upgrade ``meza`` and twine.

Fixes
~~~~~

- Added a default user agent for ``urlopen`` HTTP requests.

Documentation
~~~~~~~~~~~~~

- Added an XML namespace warning.

v0.61.1 (2020-02-02)
--------------------

Changes
~~~~~~~

- Upgrade ``mezmorize``.

Fixes
~~~~~

- Get the twine upload working.

v0.61.0 (2020-02-01)
--------------------

Changes
~~~~~~~

- Removed Python 2 support and upgrade dependencies.

Fixes
~~~~~

- Catch ``StopIteration`` exceptions.

Documentation
~~~~~~~~~~~~~

- Fixed a broken link to ``reverse``.

v0.60.4 (2018-09-13)
--------------------

Fixes
~~~~~

- Corrected a syntax error.

v0.60.3 (2018-09-12)
--------------------

Fixes
~~~~~

- Use the correct URL params.

v0.60.2 (2018-08-18)
--------------------

Fixes
~~~~~

- Use a new exchange rate data source.

v0.60.1 (2018-08-18)
--------------------

Fixes
~~~~~

- Don't crash on JSON parse errors; fix Python 2 import errors.

v0.60.0 (2018-05-23)
--------------------

New
~~~

- Added the URL to ``urllib`` exceptions.

v0.59.1 (2018-05-19)
--------------------

Fixes
~~~~~

- Fixed boolean type casting.

v0.59.0 (2018-05-18)
--------------------

New
~~~

- Added a ``name`` attribute to ``async_url_open``.

Fixes
~~~~~

- Upgrade conflicting requirements.

v0.58.0 (2018-05-18)
--------------------

Fixes
~~~~~

- Ignore currency pairs with no price; convert requirements to lists.

v0.57.0 (2017-08-31)
--------------------

Changes
~~~~~~~

- Upgrade ``mezmorize`` to move the memoize logic into it.

Fixes
~~~~~

- Upgrade ``mezmorize`` to fix Heroku detection; fix the manager's test command.

v0.56.3 (2017-08-18)
--------------------

Fixes
~~~~~

- Initialize the ``ext`` property.

v0.56.2 (2017-08-18)
--------------------

Fixes
~~~~~

- Upgrade ``mezmorize``.

v0.56.1 (2017-08-18)
--------------------

Fixes
~~~~~

- Parse URLs without file extensions.

v0.56.0 (2017-08-17)
--------------------

Changes
~~~~~~~

- Update ``mezmorize`` and rename a keyword argument; add a source option to the lint
  command.

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

Fixes
~~~~~

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

- Upgraded ``chardet``.

v0.52.2 (2017-08-11)
--------------------

Fixes
~~~~~

- Fixed ``pgrep`` to work on Heroku instances.

v0.52.1 (2017-08-09)
--------------------

Fixes
~~~~~

- Fixed a lint error.

v0.52.0 (2017-08-09)
--------------------

New
~~~

- Added more cache types.

Fixes
~~~~~

- Fixed a bug when the new month isn't in 1..12; use ``Clock`` to manage ``FakeReactor``
  timing (closes #37).

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

Fixes
~~~~~

- Don't consume the stream in ``PipeCollections``; prevent a ``UnicodeEncodeError``; fix
  the URL fetcher.

- Persist memoized responses; fix exchange rate memoization and encoding.

v0.49.1 (2017-04-09)
--------------------

Fixes
~~~~~

- Fixed spacing.

v0.49.0 (2017-04-09)
--------------------

New
~~~

- Added RSS caching.

Fixes
~~~~~

- Fixed caching.

v0.48.0 (2017-04-06)
--------------------

Changes
~~~~~~~

- Populate pipe collections with ``conf``; add caching and rename the ``sleep`` config;
  add a URL fetcher and move the cast functions.

Fixes
~~~~~

- Account for empty dates.

v0.47.0 (2017-04-04)
--------------------

New
~~~

- Added currency symbol unicode values.

Fixes
~~~~~

- Catch ``TypeError`` exceptions.

v0.46.1 (2017-04-04)
--------------------

Fixes
~~~~~

- Correctly parse dates.

v0.46.0 (2017-04-04)
--------------------

Changes
~~~~~~~

- Use case-insensitive comparison.

v0.45.1 (2017-04-04)
--------------------

Fixes
~~~~~

- Fixed a syntax error; cast parts to strings before joining; use the correct import;
  don't convert input to text.

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

Fixes
~~~~~

- Fixed Python 2 tests; remove a duplicate key.

v0.43.0 (2017-03-24)
--------------------

New
~~~

- Added the ``geolocate`` pipe.

Changes
~~~~~~~

- Return ``inf`` when dividing by zero; parsers now don't need to return ``skip``.

v0.42.0 (2017-03-23)
--------------------

New
~~~

- Allow items to be type-cast when sorting; add a ``get_skip`` dict ``re.search``
  option; add an option to always return multiple items.

Fixes
~~~~~

- Handle the changed Yahoo API format; catch ``IndexError`` when casting to a date;
  decode the raw stream response.

v0.41.0 (2017-03-18)
--------------------

New
~~~

- Allow ``get_skip`` to take a dict; only check the conversion rate when necessary; find
  text "at" a location.

Changes
~~~~~~~

- Move ``kazeeki`` data and refactor the pipe; cast null numbers to ``NaN``; compress
  the collection module to a single file; use the microdom parser to find RSS links.

Fixes
~~~~~

- Don't block stderr during nosetests; convert decoded values to strings; strip
  whitespace from tokens; don't try to convert args when skipping.

v0.40.1 (2017-03-16)
--------------------

Fixes
~~~~~

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

- Renamed ``stringtokenizer`` to ``tokenizer``; rename functions; move ``invert_dict``
  and move/rename ``entity2text``.

v0.38.0 (2017-03-10)
--------------------

New
~~~

- Added the ``eq`` operator to the ``filter`` pipe; add the ``fetchtext`` pipe.

Changes
~~~~~~~

- Added more logging.

Fixes
~~~~~

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

Fixes
~~~~~

- Correctly parse the XML path.

Documentation
~~~~~~~~~~~~~

- Added more links to the documentation.

v0.35.3 (2016-07-26)
--------------------

Fixes
~~~~~

- Install Python 2 requirements under Python 2 (fixes #3).

v0.35.2 (2016-07-25)
--------------------

Fixes
~~~~~

- Update ``meza`` to fix a ``pygogo`` version conflict; store downloaded packages in the
  wheel dir; fix prefix generation.

Documentation
~~~~~~~~~~~~~

- Update the contribution docs.

v0.35.1 (2016-07-22)
--------------------

Fixes
~~~~~

- Fixed makefile lint command. [Reuben Cummings]

- Update pygogo requirement (fixes #2) [Reuben Cummings]

v0.35.0 (2016-07-19)
--------------------

New
~~~

- Limit the number of unique items tracked. [Reuben Cummings]

- Added grouping ability to count pipe. [Reuben Cummings]

Fixes
~~~~~

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

Fixes
~~~~~

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

Fixes
~~~~~

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

Fixes
~~~~~

- Added missing optional dependency. [Reuben Cummings]

v0.30.1 (2016-06-16)
--------------------

Fixes
~~~~~

- Fixed failed test runner. [Reuben Cummings]

- Fixed lxml dependency errors. [Reuben Cummings]

v0.30.0 (2016-06-15)
--------------------

New
~~~

- Try loading workflow from curdir first. [Reuben Cummings]

Fixes
~~~~~

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

Fixes
~~~~~

- Fixed test mode for input pipe. [Reuben Cummings]

- Fixed terminal parsing. [Reuben Cummings]

- Fixed input pipe if no inputs given. [Reuben Cummings]

- Fixed sleep config. [Reuben Cummings]

- Fixed json bool parsing. [Reuben Cummings]
