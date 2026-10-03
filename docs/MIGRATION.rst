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

Workflow documents replace pipe definitions
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A stored pipeline is now a **workflow document**: explicit JSON with named nodes, edges
that name the ports they leave and enter, and listed outputs. A node separates the
configuration its module parses (``conf``) from the call options handed to the module
(``options``), and a ``loop`` carries its embedded module as ``embed``. The typing names
``ModuleOptions`` and ``Embed`` in ``riko.types.modules`` describe those two fields.

A directory registered with ``riko.ext.register_pipeline_store(directory=…)``, and the
files ``PipelineResolver.load_definition`` reads from it, must hold workflow documents.
Convert a stored pipe definition once:

.. code-block:: python

    from riko.ext import migrate_v1_to_v2, serialize_workflow

    document = serialize_workflow(migrate_v1_to_v2(old_definition))

``build-workflow`` does the same conversion from the command line, so stored definitions can
be brought forward without writing a script:

.. code-block:: bash

    build-workflow old_definition.json -o flow.json

It now emits a workflow document rather than a pipe definition, and reads a bare-bones
DAG, a pipe definition, or a workflow document, detecting which unless
``--format {dag,v1,v2}`` pins it. ``compile-pipe`` takes workflow documents only and
exits with a message naming ``build-workflow`` when handed a pipe definition.
``run-pipe -p flow.json`` runs a workflow document directly.

In Python, ``riko.convert_dag`` is replaced by ``parse_dag``, which expands the same
bare-bones DAG into a ``Workflow`` instead of a pipe definition, and ``compile_pipe``
takes a workflow document (a ``Workflow`` or the mapping it parses from) rather than
a pipe definition.

.. code-block:: python

    # before
    definition = convert_dag(dag)
    source = compile_pipe(definition, "flow")

    # after
    workflow = parse_dag(dag)
    source = compile_pipe(workflow, "flow")

The ``gen-pipelines`` console script and the ``manage codegen --pipes`` selector were
removed along with the generated fixture trees they produced.

.. _CHANGES: CHANGES.rst
