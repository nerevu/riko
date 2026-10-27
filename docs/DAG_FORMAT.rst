Bare-bones DAG format
=====================

A ``riko`` **workflow document** (``WorkflowDocument``) is a serialized ``Workflow``:
explicit JSON in which every node is named and identified, every edge names the port it
leaves and the port it enters, and the workflow outputs are listed. The **bare-bones
DAG** (``PipeDag``) is a minimal format that captures only the essentials.
``Workflow.parse`` expands it into a validated ``Workflow``, which ``flow.serialize()``
writes as a ``WorkflowDocument``. ``PipeDag`` and the older ``PipeDef`` are importable
from ``riko.types`` for annotating input.

Schema
------

.. code-block:: json

    {
        "modules": [
            {"id": "sw-1", "name": "forever", "conf": {}},
            {"id": "sw-2", "name": "truncate", "conf": {"count": {"type": "int", "value": "3"}}}
        ],
        "wires": [
            ["sw-1", "sw-2"]
        ]
    }

- **``modules``**: each entry names the module to run in ``name`` (older DAGs spell it
  ``type``). ``conf`` is **opaque**. It is copied through verbatim, so any module's
  native configuration is valid without transformation. ``id`` is *optional* and
  defaults to ``sw-{n}`` (1-based listing order). Supply ids only when ``wires``
  reference them. A module may also carry ``options``: the call options handed to the
  module (``emit``, ``assign``, ``field``, ``count``) as opposed to the configuration it
  parses. Any other key is offered to the workflow node as-is, so a typo is reported
  rather than dropped.
- **``wires``**: *optional* list of ``[source_id, target_id]`` pairs, or
  ``[source_id, target_id, target_port]`` triples when the edge enters a port other
  than the default ``in``. When ``wires`` is omitted or empty, the modules are chained
  **linearly in listing order**, so the concise form drops both ``wires`` and ``id``
  (see `pipe_forever`_):

.. code-block:: json

    {
        "modules": [
            {"name": "forever", "conf": {}},
            {"name": "truncate", "conf": {"count": {"type": "int", "value": "3"}}}
        ]
    }

Provide ``wires`` when the module listing order is **not** the execution order —
e.g. the source is listed after the operator it feeds
(see `pipe_reordered`_):

.. code-block:: json

    {
        "modules": [
            {"id": "trunc", "name": "truncate", "conf": {"count": {"type": "int", "value": "2"}}},
            {"id": "gen", "name": "forever", "conf": {}}
        ],
        "wires": [
            ["gen", "trunc"]
        ]
    }

Loading and saving
------------------

``Workflow.parse`` reads all three shapes: a ``PipeDag``, a ``PipeDef``, or a
``WorkflowDocument``. It takes a mapping or JSON text (``str`` or ``bytes``), detects
which shape it holds, and returns a validated ``Workflow``. Pass ``shape="dag"``,
``"v1"`` (a ``PipeDef``), or ``"v2"`` (a ``WorkflowDocument``) to pin the reading
instead. ``flow.serialize()`` writes the ``WorkflowDocument``, which parses back to an
equal ``Workflow``, and ``Workflow.load(path)`` reads and parses a file:

.. code-block:: python

    >>> from pathlib import Path
    >>> from tempfile import TemporaryDirectory
    >>> from riko import Workflow
    >>>
    >>> dag = {'modules': [{'name': 'forever'}, {'name': 'truncate'}]}
    >>> flow = Workflow.parse(dag)
    >>> flow
    Workflow(sw-1 -> sw-2; outputs: default)
    >>> text = '{"modules": [{"name": "forever"}, {"name": "truncate"}]}'
    >>> Workflow.parse(text, shape='dag') == flow
    True
    >>> document = flow.serialize()
    >>> Workflow.parse(document) == flow
    True
    >>> with TemporaryDirectory() as tmp:
    ...     path = Path(tmp) / 'flow.json'
    ...     _ = path.write_bytes(document)
    ...     Workflow.load(path) == flow
    True

Fan-in
------

A wire's optional third entry names the port it enters, so an operator that takes more
than one stream — ``union``, ``join`` — is expressible directly. The first input port is
``in``; the additional ones are ``in:1``, ``in:2``, and so on:

.. code-block:: json

    {
        "modules": [
            {"id": "a", "name": "fetch", "conf": {"url": "feed_a.xml"}},
            {"id": "b", "name": "fetch", "conf": {"url": "feed_b.xml"}},
            {"id": "u", "name": "union"}
        ],
        "wires": [
            ["a", "u"],
            ["b", "u", "in:1"]
        ]
    }

Conf values from another node
-----------------------------

A ``conf`` entry written as ``{"terminal": "<name>", "type": ...}`` (a *terminal
reference*) takes its value from the node wired into the port ``in:<name>``. A name that
starts with a digit gets a leading underscore, so ``1_URL`` is wired into ``in:_1_URL``.
Each time the module resolves its ``conf``, the entry receives the next item that node
produces. A module with no stream wired into ``in`` (such as ``fetch`` below) resolves
it once, while a ``processor`` fed a ``stream`` resolves it once per input ``item``.

.. code-block:: json

    {
        "modules": [
            {"id": "url", "name": "urlbuilder", "conf": {"base": "https://example.com/feed.xml"}},
            {"id": "feed", "name": "fetch", "conf": {"url": {"terminal": "1_URL", "type": "url"}}}
        ],
        "wires": [
            ["url", "feed", "in:_1_URL"]
        ]
    }

Expansion rules (``Workflow.parse``)
------------------------------------

``Workflow.parse(dag)`` expands a ``PipeDag`` into a validated ``Workflow``:

1. Modules missing an ``id`` are assigned ``sw-{n}`` in 1-based listing order.
2. When ``wires`` is omitted or empty, consecutive modules are wired in listing order.
3. Each wire becomes an edge leaving the source's ``out`` port and entering the
   target's ``in`` port, or the port named by the wire's third entry.
4. Unlike a ``PipeDef``, there is **no** ``output`` node. The workflow's default output
   is its single leaf: the one module that never appears as a wire source.
5. The result is validated: an empty ``modules`` list, a wire referencing an unknown
   module, a cycle, a wire with the wrong number of entries, or more than one leaf all
   raise ``InvalidPipelineError``.

.. code-block:: python

    >>> from riko import Pipeline, Workflow
    >>>
    >>> dag = {
    ...     'modules': [
    ...         {'name': 'forever'},
    ...         {'name': 'truncate', 'conf': {'count': {'type': 'int', 'value': '3'}}},
    ...     ]
    ... }
    >>> flow = Workflow.parse(dag)
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
``flow.serialize()``, or hand it to ``compile_workflow``.

A pipe definition (``PipeDef``) converts the same way: ``Workflow.parse`` detects one,
and ``riko.ext.migrate_v1_to_v2`` converts one explicitly. Convert a serialized one
once before registering its directory with ``riko.ext.register_workflow_store``, which
reads ``WorkflowDocument``\s only:

.. code-block:: python

    import json
    from pathlib import Path

    from riko.ext import migrate_v1_to_v2

    path = Path("workflows/pipe_demo.json")
    pipe_def = json.loads(path.read_text())
    path.write_bytes(migrate_v1_to_v2(pipe_def).serialize())

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

See `pipe_forever`_ for a runnable example, and `test_workflow`_ and
`test_script`_ for the expansion and command guarantees.

For fuller worked examples, see the `example workflow documents`_
(``examples/workflows/*.json``), which riko runs directly. The
``examples/pyworkflows/*.py`` files beside them are hand-written workflow modules
(``WorkflowModule``\s), not ``compile-workflow`` output.

.. _pipe_forever: ../tests/dags/pipe_forever.json
.. _pipe_reordered: ../tests/dags/pipe_reordered.json
.. _test_workflow: ../tests/public/test_workflow.py
.. _test_script: ../tests/functional/test_script.py
.. _example workflow documents: ../examples/workflows
