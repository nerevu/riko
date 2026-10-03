Bare-bones DAG format
=====================

A ``riko`` **workflow document** is explicit JSON: every node is named and
identified, every edge names the port it leaves and the port it enters, and the
workflow's outputs are listed. The **bare-bones DAG** is a minimal authoring format
that captures only the essentials and expands into a validated workflow document via
``parse_dag``.

Schema
------

.. code-block:: json

    {
        "modules": [
            {"id": "sw-1", "type": "forever", "conf": {}},
            {"id": "sw-2", "type": "truncate", "conf": {"count": {"type": "int", "value": "3"}}}
        ],
        "wires": [
            ["sw-1", "sw-2"]
        ]
    }

- **``modules``**: each entry names the module ``type`` to run. ``conf`` is **opaque**:
  it is copied through verbatim, so any module's native configuration is valid without
  transformation. ``id`` is *optional* and defaults to ``sw-{n}`` (1-based listing
  order); supply ids only when ``wires`` reference them. A module may also carry
  ``options`` — the call options handed to the module itself (``emit``, ``assign``,
  ``field``, ``count``) as opposed to the configuration it parses. Any other key is
  offered to the workflow node as-is, so a typo is reported rather than dropped.
- **``wires``**: *optional* list of ``[source_id, target_id]`` pairs, or
  ``[source_id, target_id, target_port]`` triples when the edge enters a port other
  than the default ``in``. When ``wires`` is omitted or empty, the modules are chained
  **linearly in listing order**, so the concise form drops both ``wires`` and ``id``
  (see `pipe_forever`_):

.. code-block:: json

    {
        "modules": [
            {"type": "forever", "conf": {}},
            {"type": "truncate", "conf": {"count": {"type": "int", "value": "3"}}}
        ]
    }

Provide ``wires`` when the module listing order is **not** the execution order —
e.g. the source is listed after the operator it feeds
(see `pipe_reordered`_):

.. code-block:: json

    {
        "modules": [
            {"id": "trunc", "type": "truncate", "conf": {"count": {"type": "int", "value": "2"}}},
            {"id": "gen", "type": "forever", "conf": {}}
        ],
        "wires": [
            ["gen", "trunc"]
        ]
    }

Fan-in
------

A wire's optional third entry names the port it enters, so an operator that takes more
than one stream — ``union``, ``join`` — is expressible directly. The first input is
``in``; the additional ones are ``in:1``, ``in:2``, and so on:

.. code-block:: json

    {
        "modules": [
            {"id": "a", "type": "fetch", "conf": {"url": "feed_a.xml"}},
            {"id": "b", "type": "fetch", "conf": {"url": "feed_b.xml"}},
            {"id": "u", "type": "union"}
        ],
        "wires": [
            ["a", "u"],
            ["b", "u", "in:1"]
        ]
    }

Expansion rules (``parse_dag``)
------------------------------------

``riko.parse_dag(dag)`` returns a validated workflow document:

1. Modules missing an ``id`` are assigned ``sw-{n}`` in 1-based listing order.
2. When ``wires`` is omitted or empty, consecutive modules are wired in listing order.
3. Each wire becomes an edge leaving the source's ``out`` port and entering the
   target's ``in`` port, or the port named by the wire's third entry.
4. There is **no** terminal output module. The workflow's default output is its single
   leaf — the one module that never appears as a wire source.
5. The result is validated: an empty ``modules`` list, a wire referencing an unknown
   module, a cycle, a wire with the wrong number of entries, or more than one leaf all
   raise ``InvalidPipelineError``.

.. code-block:: python

    >>> from riko import Pipeline, parse_dag
    >>>
    >>> dag = {
    ...     'modules': [
    ...         {'type': 'forever'},
    ...         {'type': 'truncate', 'conf': {'count': {'type': 'int', 'value': '3'}}},
    ...     ]
    ... }
    >>> spec = parse_dag(dag)
    >>> list(spec.nodes)
    ['sw-1', 'sw-2']
    >>> spec.outputs['default']
    Endpoint(node='sw-2', port='out')
    >>> len(list(Pipeline(spec)))
    3

The expanded workflow is an ordinary workflow document: run it with ``Pipeline``,
serialize it with ``riko.ext.serialize_workflow``, or hand it to ``compile_pipe``.

Commands
--------

Three console scripts work on these documents:

.. code-block:: bash

    # any supported form -> workflow document (stdout, or -o path)
    build-workflow tests/dags/pipe_forever.json -o flow.json

    # workflow document -> generated Python module (stdout, or -o path)
    compile-pipe flow.json -o flow.py

    # run a workflow document directly
    run-pipe -p flow.json

``build-workflow`` is the lenient one. It reads a bare-bones DAG, a pipe definition
(the older ``{"src": ..., "tgt": ...}`` wire format), or a workflow document, and
always emits a validated workflow document. It detects which
form it was given; pass ``--format {dag,v1,v2}`` to pin the reading instead. The output
is indented for reading by default; ``-c``/``--compact`` writes the byte-stable
single-line form. A document it cannot read or cannot validate is reported on stderr
and exits non-zero.

``compile-pipe`` takes workflow documents only — hand it an older form and it exits
with a message telling you to run ``build-workflow`` first. It emits a Python module that
rebuilds the workflow from typed configuration classes and exposes a ``pipe`` (or,
with ``-a``/``--async``, an ``async_pipe``) callable over it. ``-v``/``--verbose``
reports the modules used and the bytes written to stderr.

Both read stdin when given ``-`` or no path at all, so they compose:

.. code-block:: bash

    build-workflow dag.json | compile-pipe - -o flow.py

See `pipe_forever`_ for a runnable example, and `test_build_workflow`_ and
`test_script`_ for the expansion and command guarantees.

For fuller worked pipelines, see the `example pipelines`_
(``examples/pipelines/*.json``). Those are workflow documents run directly by
riko, and the ``examples/pypipelines/*.py`` modules beside them are hand-written Python
equivalents, not ``compile-pipe`` output.

.. _pipe_forever: ../tests/dags/pipe_forever.json
.. _pipe_reordered: ../tests/dags/pipe_reordered.json
.. _test_build_workflow: ../tests/public/test_build_workflow.py
.. _test_script: ../tests/functional/test_script.py
.. _example pipelines: ../examples/pipelines
