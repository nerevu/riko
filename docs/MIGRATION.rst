Migrating riko
==============

.. contents:: Contents
   :local:
   :depth: 2

API Stability
-------------

riko follows semantic versioning for its stable application and extension
surfaces. ``riko.bado`` is additionally documented as the supported async-runtime
namespace.

Tiers
^^^^^

Stable: ``riko``
~~~~~~~~~~~~~~~~

The stable application-facing API is everything listed in ``riko.__all__``. It
includes the pipe/collection API, compiler API, module-discovery API, public
exceptions and context types, path/temp-file helpers, and the promoted async
runtime helpers:

.. code-block:: python

    >>> import riko
    >>> sorted(riko.__all__)
    ['AsyncCollection', 'AsyncPipe', 'Context', 'ExecutionMode', 'Modules', 'PipeState', 'PipelineStateError', 'RikoError', 'Sinks', 'Sources', 'SyncCollection', 'SyncPipe', 'Targets', 'Transforms', 'UnsupportedModuleError', 'UnsupportedPipelineError', 'as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'async_write', 'backend', 'build_pipeline', 'compile_pipe', 'convert_dag', 'describe_module', 'export', 'extract_dependencies', 'get_async_temp_file', 'get_module_metadata', 'get_path', 'get_temp_file', 'isasync', 'issync', 'list_modules', 'list_targets', 'parse_pipe_def', 'run']

Breaking changes to this surface require the corresponding SemVer treatment.

Extension: ``riko.ext``
~~~~~~~~~~~~~~~~~~~~~~~

``riko.ext`` is the supported API for module and integration authors. It
contains decorators, module metadata and naming types, parsed configuration
types, parser/wrapper protocols, and registry interfaces:

.. code-block:: python

    >>> import riko.ext
    >>> sorted(riko.ext.__all__)
    ['AsyncOperatorWrapper', 'AsyncProcessorWrapper', 'AsyncSplitterWrapper', 'DynamicConf', 'ModuleDefinition', 'ModuleMetadata', 'ModuleName', 'ModuleNameLike', 'ModuleRegistry', 'ModuleSubtype', 'ModuleType', 'ModuleWrapper', 'SyncOperatorWrapper', 'SyncProcessorWrapper', 'SyncSplitterWrapper', 'derive_category', 'get_conf_type', 'normalize_module_name', 'operator', 'processor', 'register', 'splitter']

Async runtime: ``riko.bado``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``riko.bado`` is the supported async-runtime namespace. Every name it exports is
also re-exported from the top-level ``riko``:

.. code-block:: python

    >>> import riko.bado
    >>> sorted(riko.bado.__all__)
    ['as_async', 'async_map', 'async_map_stream', 'async_read', 'async_return', 'async_sleep', 'async_write', 'backend', 'get_async_temp_file', 'isasync', 'issync', 'run']

Private implementation
~~~~~~~~~~~~~~~~~~~~~~

Underscore-prefixed names and modules are implementation details unless they are
explicitly re-exported through a supported namespace. They carry no independent
compatibility guarantee.

Marker
^^^^^^

riko ships a ``py.typed`` marker, so type checkers treat it as a typed dependency.

Compatibility during refactors
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

After 1.0 release, names that move will keep a re-export at their old import path for at
least one minor release; behavior-changing removals will be listed in
`CHANGES`_.

Upgrading from the ``legacy`` branch
------------------------------------

concrete, verified differences between the ``legacy`` branch (``git checkout legacy``)
and the current tree. ``legacy`` **is the** ``v0.72.x`` **release**; the current tree
is the ``features`` branch, and those commits contain the final legacy-removal work.
Every example below was run on both. The ``# LEGACY`` and ``# CURRENT`` comments show
the actual observed behavior.

Legacy ``Context`` describe kwargs are ignored
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Both branches expose ``mode: ExecutionMode`` and derive ``describe_input`` /
``describe_dependencies`` as **read-only properties**. The difference is the
constructor: the ``legacy`` branch still translated the old boolean kwargs into a
mode; the current release drops them, so they fall through ``**kwargs`` and are
silently ignored.

.. code-block:: python

    from riko import Context, ExecutionMode

    Context(describe_input=True).mode   # LEGACY:  ExecutionMode.DESCRIBE_INPUTS
                                        # CURRENT: ExecutionMode.RUN   (ignored)

    # Works identically on both branches:
    Context(mode=ExecutionMode.DESCRIBE_INPUTS).describe_input   # -> True

Assigning to the property raises ``AttributeError`` on **both** branches (it has
no setter) — that is not a new change:

.. code-block:: python

    ctx = Context(mode=ExecutionMode.DESCRIBE_INPUTS)
    ctx.describe_input = True            # LEGACY & CURRENT: AttributeError

**Action:** pass ``mode=ExecutionMode.DESCRIBE_INPUTS`` /
``DESCRIBE_DEPENDENCIES`` / ``DESCRIBE`` instead of ``describe_input=`` /
``describe_dependencies=``.

``Objconf`` is removed
^^^^^^^^^^^^^^^^^^^^^^

``Objconf`` is no longer part of the top-level API. ``DynamicConf`` is the supported
replacement for extension authors:

.. code-block:: python

    >>> from riko.ext import DynamicConf
    >>> DynamicConf.__name__
    'DynamicConf'

Legacy JSON pipeline forms are removed
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The current tree deletes the Yahoo!-Pipes-era **nested-loop shape** — a ``loop``
module carrying its embedded submodule under ``conf["embed"]["value"]`` with two
levels of ``emit`` / ``assign`` / ``field``. The input converter that read that
shape is gone, so hand-authored JSON using it no longer compiles.

The canonical forms are the **compact loop** (``type="loop"`` with a top-level
``embed`` reference and the embed's ``conf``) and, for processor loops, a
**direct processor node**. If you author pipeline JSON by hand, see
`DAG_FORMAT.rst <DAG_FORMAT.rst>`_ for the current format.

The terminal ``output`` node is **unaffected** — it is still recognized as the
pipeline's sink marker (``type: "output"``). What was removed is only its
treatment as a *resolvable virtual module*; the node itself stays and needs no
change.

Pipelines built with the ``SyncPipe`` / ``AsyncPipe`` API are unaffected by all
of the above.

``get_path`` is now part of the stable surface
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``get_path`` is now an explicitly supported top-level API:

.. code-block:: python

    >>> from riko import get_path
    >>> get_path("feed.xml").endswith("feed.xml")
    True

Milestone changes (release history)
-----------------------------------

These landed across the 2026 releases and are already on the ``legacy`` branch.
They are relevant when upgrading from a release **older** than the one noted. See
`CHANGES.rst <CHANGES.rst>`_ for the full per-release history.

Twisted replaced by AnyIO (v0.72.0)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The async runtime is now AnyIO. There is **no Twisted backend** — Twisted is not
imported and not importable anywhere in ``riko``. The ``riko.bado`` runtime still exists
and runs on AnyIO. It is the supported async-runtime namespace and also exposes selected
backend primitives used by riko internally.

Application-facing async helpers are re-exported unchanged through ``riko``. Each
resolves to the same object as its ``riko.bado`` counterpart, but application code
should use the top-level ``riko`` form — e.g. ``riko.run``, ``riko.backend``,
``riko.isasync``.

Backend selection is purely "does ``anyio`` import?":

.. code-block:: python

    from riko import backend        # "anyio" when the `async` extra is
                                    # installed, else "empty" (sync-only)

There is no ``RIKO_ASYNC_BACKEND`` env var. Install the ``async`` extra
(``anyio`` + ``httpx``) to enable async processing. Code written against the old
Twisted/``deferred`` API must move to ``async`` / ``await``.

Three-tier import surface (v0.70.0)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Imports now fall into three tiers knowable from the path alone:

========== ========================================= =====================================
Tier       Import from                               Guarantee
========== ========================================= =====================================
Stable     ``riko`` / ``riko.api``                   SemVer; breaking change ⇒ major bump
Extension  ``riko.ext``                              SemVer, for module/pipe authors
Private    any ``_name`` or ``riko._*`` module       none; may change any release
========== ========================================= =====================================

The stable surface is exactly ``riko.__all__`` (mirrored by ``riko.api.__all__``;
see `API Stability`_ for the authoritative tier breakdown)::

    AsyncCollection, AsyncPipe, Context, ExecutionMode, PipeState,
    PipelineStateError, SyncCollection, SyncPipe, UnsupportedModuleError,
    UnsupportedPipelineError, backend, build_pipeline, compile_pipe, convert_dag,
    export, extract_dependencies, get_module_metadata, get_path, isasync, issync,
    list_modules, list_targets, parse_pipe_def, run

Utilities that previously leaked into ``riko`` now live in private modules and
are **no longer importable from** ``riko`` (use the noted home, or pin your own
copy):

================================  ======================
Removed import                    Now lives in (private)
================================  ======================
``from riko import Objconf``      *removed* (see Part 1)
``from riko import Objectify``    ``riko._objectify``
``from riko import objectify``    ``riko._objectify``
``from riko import listize``      ``riko._iterutils``
``from riko import get_abspath``  ``riko.paths``
``from riko import replacer``     ``riko._strutils``
================================  ======================

Single-execution pipe lifecycle (v0.70.0)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A ``SyncPipe`` / ``AsyncPipe`` / ``SyncCollection`` / ``AsyncCollection``
instance now represents **one execution**.

.. code-block:: python

    flow = SyncPipe("fetchdata", conf=conf)
    first = list(flow)     # runs the pipeline
    second = list(flow)    # yields []  (the run is spent, but older releases re-ran it)

* Iterating an exhausted, closed, or failed pipe yields an empty stream — it
  never raises (ordinary spent-iterator semantics).
* Chaining (``.filter()``, ``.count()``, …) is the one state-enforcing operation:
  allowed while ``NEW`` / ``RUNNING`` / ``EXHAUSTED``, but raises
  ``PipelineStateError`` on ``CLOSED`` / ``FAILED``.
* Lifecycle API: ``PipeState`` enum
  (``NEW`` / ``RUNNING`` / ``EXHAUSTED`` / ``CLOSED`` / ``FAILED``); read-only
  ``.state`` / ``.closed`` / ``.exhausted`` / ``.failed``; ``.close()`` /
  ``.terminate()`` (sync), ``await .aclose()`` (async); context-manager support
  (a pipe that owns a worker pool shuts it down on exit).

.. code-block:: python

    flow.close()
    flow.count()           # raises riko.PipelineStateError

``ExecutionMode`` replaces the describe booleans (v0.70.0)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``Context`` gained a ``mode: ExecutionMode`` field
(``RUN`` / ``DESCRIBE_INPUTS`` / ``DESCRIBE_DEPENDENCIES`` / ``DESCRIBE``), part
of the stable surface (``from riko import ExecutionMode``).
``describe_input`` / ``describe_dependencies`` became read-only properties
derived from it. (The constructor's final acceptance of the old kwargs is the
Part 1 legacy → current diff.)

``Objconf`` → ``DynamicConf`` (v0.71.0)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The ``Objconf`` class was replaced by ``DynamicConf`` (from
``riko.ext.config``). v0.71.0 kept ``Objconf`` as a deprecated factory; the
current release removes it entirely (Part 1).

``return_value`` removed
^^^^^^^^^^^^^^^^^^^^^^^^

The ``return_value`` symbol was removed entirely; there is no compatibility
shim. Remove any imports or references. (Note: the ``coroutine`` decorator is **not**
an async marker. It marks pub/sub generator pipelines using ``send`` / ``receive``.)

.. _CHANGES: CHANGES.rst

