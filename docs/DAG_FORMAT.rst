Bare-bones DAG format
=====================

A ``riko`` **workflow document** (``WorkflowDocument``) is a serialized ``Workflow``:
explicit JSON in which every node is named and identified, every edge names the port it
leaves and the port it enters, and the workflow's outputs are listed. The **bare-bones
DAG** (``PipeDag``) is a minimal format that captures only the essentials. ``parse_dag``
expands it into a validated ``Workflow``, which ``serialize_workflow`` writes as a
``WorkflowDocument``. ``PipeDag`` and the older ``PipeDef`` are importable from
``riko.types`` for annotating input.

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

Conf values from another node
-----------------------------

A ``conf`` entry written as ``{"terminal": "<name>", "type": ...}`` takes its value
from the node wired into the port ``in:<name>``. A name that starts with a digit gets
a leading underscore, so ``1_URL`` is wired into ``in:_1_URL``. Each time the module
resolves its ``conf``, the entry receives the next item that node produces: a module
with no stream wired into ``in`` (such as ``fetch`` below) resolves it once, while a
``processor`` fed a ``stream`` resolves it once per input ``item``.

.. code-block:: json

    {
        "modules": [
            {"id": "url", "type": "urlbuilder", "conf": {"base": "https://example.com/feed.xml"}},
            {"id": "feed", "type": "fetch", "conf": {"url": {"terminal": "1_URL", "type": "url"}}}
        ],
        "wires": [
            ["url", "feed", "in:_1_URL"]
        ]
    }

Expansion rules (``parse_dag``)
------------------------------------

``riko.parse_dag(dag)`` returns a validated ``Workflow``:

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
    >>> flow = parse_dag(dag)
    >>> list(flow.nodes)
    ['sw-1', 'sw-2']
    >>> flow.outputs['default']
    Endpoint(node='sw-2', port='out')
    >>> sorted({node.name for node in flow.nodes.values()})
    ['forever', 'truncate']
    >>> len(list(Pipeline(flow)))
    3

The result is an ordinary ``Workflow``: list the modules it uses from its ``nodes``, run
it with ``Pipeline``, serialize it to a ``WorkflowDocument`` with
``riko.ext.serialize_workflow``, or hand it to ``compile_workflow``.

A pipe definition (``PipeDef``) converts the same way through
``riko.ext.migrate_v1_to_v2``. Convert a stored one once before registering its
directory with ``riko.ext.register_workflow_store``, which reads
``WorkflowDocument``\s only:

.. code-block:: python

    from riko.ext import migrate_v1_to_v2, serialize_workflow

    document = serialize_workflow(migrate_v1_to_v2(pipe_def))

Commands
--------

Three console scripts work on these files:

.. code-block:: bash

    # PipeDag, PipeDef, or WorkflowDocument -> WorkflowDocument (stdout, or -o path)
    build-workflow tests/dags/pipe_forever.json -o flow.json

    # WorkflowDocument -> WorkflowModule (stdout, or -o path)
    compile-workflow flow.json -o flow.py

    # run a WorkflowDocument directly
    run-pipe -p flow.json

``build-workflow`` is the lenient one. It reads a serialized ``PipeDag``, a serialized
pipe definition (``PipeDef``, the older ``{"src": ..., "tgt": ...}`` wire format), or a
``WorkflowDocument``, and always emits a validated ``WorkflowDocument``. It detects
which form it was given. Pass ``--format {dag,v1,v2}`` to pin the reading instead. The
output is indented for reading by default. ``-c``/``--compact`` writes the byte-stable
single-line form. A file it cannot read or cannot validate is reported on stderr
and exits non-zero.

``compile-workflow`` takes ``WorkflowDocument``\s only. Hand it a serialized ``PipeDag``
or ``PipeDef`` and it exits with a message telling you to run ``build-workflow``
first. It emits a workflow module (``WorkflowModule``): Python source that rebuilds
the workflow from typed configuration classes and exposes a ``pipe`` (or, with ``-a``/
``--async``, an ``async_pipe``) callable over it. ``-v``/``--verbose`` reports the
modules used and the bytes written to stderr.

Both read stdin when given ``-`` or no path at all, so they compose:

.. code-block:: bash

    build-workflow dag.json | compile-workflow - -o flow.py

See `pipe_forever`_ for a runnable example, and `test_build_workflow`_ and
`test_script`_ for the expansion and command guarantees.

For fuller worked examples, see the `example workflow documents`_
(``examples/workflows/*.json``), which riko runs directly. The
``examples/pyworkflows/*.py`` files beside them are hand-written workflow modules
(``WorkflowModule``\s), not ``compile-workflow`` output.

.. _pipe_forever: ../tests/dags/pipe_forever.json
.. _pipe_reordered: ../tests/dags/pipe_reordered.json
.. _test_build_workflow: ../tests/public/test_build_workflow.py
.. _test_script: ../tests/functional/test_script.py
.. _example workflow documents: ../examples/workflows
