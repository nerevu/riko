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
code. Its package exports are stable. The non-underscored typing submodules
``riko.types.modules`` and ``riko.types.compile`` are also supported import paths.
Underscore-prefixed modules under ``riko.types`` are implementation typing
machinery and are private. Export lists are intentionally not duplicated here.

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

.. _CHANGES: CHANGES.rst
