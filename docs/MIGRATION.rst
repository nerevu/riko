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

Stable: ``riko`` / ``riko.api``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The stable application-facing API is everything listed in ``riko.__all__``, mirrored by
``riko.api.__all__``. Breaking changes to this surface require the corresponding SemVer
treatment. The current export list is intentionally not duplicated here.

Extension: ``riko.ext``
~~~~~~~~~~~~~~~~~~~~~~~

``riko.ext`` is the supported API for module and integration authors. Its current
membership is defined by ``riko.ext.__all__`` and includes decorators, module metadata
and naming types, parsed configuration types, parser/wrapper protocols, and registry
interfaces. The export list is intentionally not duplicated here.

Async runtime: ``riko.bado``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``riko.bado`` is the supported async-runtime namespace. Its current membership is
defined by ``riko.bado.__all__``; every exported name is also re-exported from the
top-level ``riko``. The export list is intentionally not duplicated here.

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
