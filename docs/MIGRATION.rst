Migrating to riko
=================

This guide has two parts:

* **Upgrading from the** ``legacy`` **branch** — the concrete, verified
  differences between the ``legacy`` branch (``git checkout legacy``) and the
  current tree. ``legacy`` **is the** ``v0.72.x`` **release**; the current tree
  is the ``features`` branch, and those commits contain the final legacy-removal work.
  Every example below was run on both — the ``# LEGACY`` and ``# CURRENT`` comments show
  the actual observed behavior.
* **Milestone changes** — larger behavior changes that landed across the 2026
  release series (expanded from `CHANGES.rst <CHANGES.rst>`_). These are already
  present on the ``legacy`` branch, so they are **not** part of the
  legacy → current diff, but they matter if you are upgrading from an older
  release.

The sections below cover the known user-facing migration changes.

.. contents:: Contents
   :local:
   :depth: 2

----

Part 1 — Upgrading from the ``legacy`` branch
=============================================

Legacy ``Context`` describe kwargs are ignored
----------------------------------------------

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
----------------------

On the ``legacy`` branch ``Objconf`` survived as a deprecated factory that warned
and returned a ``DynamicConf``. The current release removes it outright.

.. code-block:: python

    from riko import Objconf     # LEGACY:  OK — DeprecationWarning, returns DynamicConf
                                 # CURRENT: ImportError

**Action:** import ``DynamicConf`` from the extension surface. It moved from the
top level (``riko``) to a private module (``riko._objectify``), with the stable
re-export at ``riko.ext.config``:

.. code-block:: python

    from riko.ext.config import DynamicConf   # LEGACY & CURRENT: OK
    from riko import DynamicConf              # LEGACY: OK   CURRENT: ImportError

Legacy JSON pipeline forms are removed
--------------------------------------

The current tree deletes the Yahoo!-Pipes-era **nested-loop shape** — a ``loop``
module carrying its embedded submodule under ``conf["embed"]["value"]`` with two
levels of ``emit`` / ``assign`` / ``field``. The input converter that read that
shape is gone, so hand-authored JSON using it no longer compiles.

The canonical forms are the **compact loop** (``type="loop"`` with a top-level
``embed`` reference and the embed's ``conf``) and, for processor loops, a
**direct processor node**. If you author pipeline JSON by hand, see
`DAG_FORMAT.md <DAG_FORMAT.md>`_ for the current format.

The terminal ``output`` node is **unaffected** — it is still recognized as the
pipeline's sink marker (``type: "output"``). What was removed is only its
treatment as a *resolvable virtual module*; the node itself stays and needs no
change.

Pipelines built with the ``SyncPipe`` / ``AsyncPipe`` API are unaffected by all
of the above.

``get_path`` is now part of the stable surface
----------------------------------------------

``get_path`` is importable from ``riko`` on both branches, but only the current
release lists it in ``riko.__all__`` (so ``from riko import *`` now includes it):

.. code-block:: python

    from riko import get_path            # LEGACY & CURRENT: OK
    "get_path" in riko.__all__           # LEGACY: False   CURRENT: True

----

Part 2 — Milestone changes (release history)
============================================

These landed across the 2026 releases and are already on the ``legacy`` branch.
They are relevant when upgrading from a release **older** than the one noted. See
`CHANGES.rst <CHANGES.rst>`_ for the full per-release history.

Twisted replaced by AnyIO (v0.72.0)
-----------------------------------

The async runtime is now AnyIO. There is **no Twisted backend** — Twisted is not
imported and not importable anywhere in ``riko``. The ``riko.bado`` backend still
exists and runs on AnyIO, but it is an internal module (private per the stability
policy): applications should use the stable re-exports ``riko.run``,
``riko.backend``, ``riko.isasync``, and ``riko.issync`` rather than importing from
``riko.bado`` directly. Backend selection is purely "does ``anyio`` import?":

.. code-block:: python

    from riko import backend        # "anyio" when the `async` extra is
                                         # installed, else "empty" (sync-only)

There is no ``RIKO_ASYNC_BACKEND`` env var. Install the ``async`` extra
(``anyio`` + ``httpx``) to enable async processing. Code written against the old
Twisted/``deferred`` API must move to ``async`` / ``await``.

Three-tier import surface (v0.70.0)
-----------------------------------

Imports now fall into three tiers knowable from the path alone:

========== ========================================= =====================================
Tier       Import from                               Guarantee
========== ========================================= =====================================
Stable     ``riko`` / ``riko.api``                   SemVer; breaking change ⇒ major bump
Extension  ``riko.ext``                              SemVer, for module/pipe authors
Private    any ``_name`` or ``riko._*`` module       none; may change any release
========== ========================================= =====================================

The stable surface is exactly ``riko.__all__`` (mirrored by ``riko.api.__all__``;
see `API_STABILITY.md <API_STABILITY.md>`_ for the authoritative tier breakdown)::

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
------------------------------------------

A ``SyncPipe`` / ``AsyncPipe`` / ``SyncCollection`` / ``AsyncCollection``
instance now represents **one execution**.

.. code-block:: python

    flow = SyncPipe("fetchdata", conf=conf)
    first = list(flow)     # runs the pipeline
    second = list(flow)    # yields []  (the run is spent — older releases re-ran it)

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

    from riko import PipelineStateError

    flow.close()
    flow.count()           # raises PipelineStateError

``ExecutionMode`` replaces the describe booleans (v0.70.0)
----------------------------------------------------------

``Context`` gained a ``mode: ExecutionMode`` field
(``RUN`` / ``DESCRIBE_INPUTS`` / ``DESCRIBE_DEPENDENCIES`` / ``DESCRIBE``), part
of the stable surface (``from riko import ExecutionMode``).
``describe_input`` / ``describe_dependencies`` became read-only properties
derived from it. (The constructor's final acceptance of the old kwargs is the
Part 1 legacy → current diff.)

``Objconf`` → ``DynamicConf`` (v0.71.0)
---------------------------------------

The ``Objconf`` class was replaced by ``DynamicConf`` (from
``riko.ext.config``). v0.71.0 kept ``Objconf`` as a deprecated factory; the
current release removes it entirely (Part 1).

``return_value`` removed
------------------------

The ``return_value`` symbol was removed entirely — there is no shim. Remove any
imports or references. (Note: the ``coroutine`` decorator is **not** an async
marker — it marks pub/sub generator pipelines using ``send`` / ``receive``.)
