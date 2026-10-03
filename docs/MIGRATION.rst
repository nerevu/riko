Migrating riko
==============

.. contents:: Contents
   :local:
   :depth: 2

API Stability
-------------

riko follows semantic versioning for the supported public surfaces listed below.
A module's ``__all__`` defines the public names exported by that module; it does
**not** by itself define the complete set of supported modules or namespaces.

Tiers
^^^^^

Stable application API: ``riko``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The top-level application-facing facade is everything listed in ``riko.__all__``.
It includes the pipe/collection API, compiler API, module-discovery API, public
exceptions and context types, path/temp-file helpers, and the promoted async
runtime helpers. Breaking changes to these names require the corresponding SemVer
treatment. The current export list is intentionally not duplicated here.

Stable typing API: ``riko.types``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``riko.types`` is the supported typing surface for applications and extension
code. Its package exports are stable. The non-underscored typing submodule
``riko.types.modules`` is also a supported import path. Underscore-prefixed modules
under ``riko.types`` are implementation typing machinery and are private. Export lists
are intentionally not duplicated here.

Extension API: ``riko.ext``
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``riko.ext`` is the supported API for module and integration authors. Its current
membership is defined by ``riko.ext.__all__`` and includes decorators, module
metadata and naming types, parsed configuration types, parser/wrapper protocols,
and registry interfaces. Non-underscored submodules beneath ``riko.ext`` are part
of the extension surface; underscore-prefixed modules are private. The export list
is intentionally not duplicated here.

Module catalog API: ``riko.modules``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``riko.modules`` is a supported secondary namespace for built-in module discovery,
metadata, and the module decorators it re-exports. Its ``__all__`` is protected by
SemVer; extension authors should prefer ``riko.ext`` for authoring contracts.
Individual implementation modules beneath ``riko.modules`` are not made stable by
this guarantee unless they are documented separately.

Async runtime API: ``riko.bado``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``riko.bado`` is the supported async-runtime namespace. Its current membership is
defined by ``riko.bado.__all__``; every exported name is also re-exported from the
top-level ``riko``. The export list is intentionally not duplicated here.

Private and unspecified modules
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Any import path containing an underscore-prefixed module or name is an
implementation detail unless that name is explicitly re-exported through a
supported namespace. Other non-underscored modules may remain importable for
compatibility, but they carry no SemVer guarantee unless listed above or
explicitly documented as public.

Marker
^^^^^^

riko ships a ``py.typed`` marker, so type checkers treat it as a typed dependency.

Compatibility during refactors
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

After 1.0 release, names that move will keep a re-export at their old import path for at
least one minor release; behavior-changing removals will be listed in `CHANGES`_.

Version upgrades
----------------

`CHANGES`_ is the source of truth for version-specific migration information. When
upgrading across multiple releases, read every intervening release entry in order,
especially its ``Changes`` and ``Removed`` sections. Those entries record behavior
changes, renamed or removed APIs, and the replacement forms needed to migrate.

This guide intentionally contains only the durable compatibility model and supported API
boundaries. It should change only when those policies or surfaces change, not for each
release.

Workflow call options and stored pipelines
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A workflow node now separates the configuration a module parses (``conf``) from the
options handed to the module itself (``options``). The typing name ``LoopOptions`` in
``riko.types.modules`` is now ``ModuleOptions``, since those options apply to every
module rather than to ``loop`` alone, and ``LoopConf`` holds only ``embed``.

Move a loop's ``emit``, ``assign``, ``field``, and ``count`` out of its ``conf``:

.. code-block:: python

    # before
    ModuleNode(id="loop", name="loop", conf={"embed": embed, "emit": True})

    # after
    ModuleNode(id="loop", name="loop", conf={"embed": embed}, options={"emit": True})

The same ``options`` mapping is accepted in an authoring mapping and is serialized only
when it is non-empty.

A directory registered with ``riko.ext.register_pipeline_store(directory=…)``, and the
files ``PipelineResolver.load_definition`` reads from it, must now hold canonical
workflow JSON. Convert stored definitions in the released pipe-definition format once:

.. code-block:: python

    from riko.ext import migrate_v1_to_v2, serialize_workflow

    canonical = serialize_workflow(migrate_v1_to_v2(old_definition))

The ``gen-pipelines`` console script and the ``manage codegen --pipes`` selector were
removed along with the generated fixture trees they produced. ``compile-pipe`` and
``convert-dag`` are unchanged and still take the older pipe-definition format.

.. _CHANGES: CHANGES.rst
