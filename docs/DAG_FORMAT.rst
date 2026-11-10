Bare-bones DAG format
=====================

A ``riko`` **workflow document** (``WorkflowDocument``) is a serialized ``Workflow``:
explicit JSON in which every node is named and identified, every edge names the port it
leaves and the port it enters, and the outputs are listed. The **bare-bones DAG**
(``PipeDag``) is a minimal format that captures only the essentials. ``Workflow.parse``
expands it into a validated ``Workflow``, which ``flow.serialize()`` writes as a
``WorkflowDocument``. ``PipeDag`` and the older pipe definition (``PipeDef``) are
importable from ``riko.types`` for annotating input.

PipeDag schema
--------------

- ``modules``: a list of module entries, each with these keys:

  - ``id``: *optional* and defaults to ``sw-{n}`` (1-based listing order). Required
    only when ``wires`` is given.
  - ``name``: the module to run (older DAGs spell it ``type``).
  - ``conf``: **opaque** configuration passed verbatim to the module.
  - ``options``: *optional* call options handed to the module (``emit``, ``assign``,
    ``field``, ``count``), as opposed to the configuration it parses.

  Any other key is offered to the workflow node as-is. A typo is reported rather than
  dropped.

- ``wires``: *optional* list of ``[source_id, target_id]`` pairs. Also accepts
  ``[source_id, target_id, target_port]`` triples for when the edge enters a port other
  than the default ``in``.

.. code-block:: json

    {
        "modules": [
            {"id": "sw-1", "name": "forever", "conf": {}},
            {
                "id": "sw-2",
                "name": "truncate",
                "conf": {"count": {"type": "int", "value": "3"}}
            }
        ],
        "wires": [
            ["sw-1", "sw-2"]
        ]
    }

When ``wires`` is omitted or empty, the modules are chained
**linearly in listing order** (see `pipe_forever`_):

.. code-block:: json

    {
        "modules": [
            {"name": "forever", "conf": {}},
            {"name": "truncate", "conf": {"count": {"type": "int", "value": "3"}}}
        ]
    }

Provide ``wires`` when the module listing order is **not** the execution order. E.g.,
the source is listed after the operator it feeds (see `pipe_reordered`_):

.. code-block:: json

    {
        "modules": [
            {
                "id": "trunc",
                "name": "truncate",
                "conf": {"count": {"type": "int", "value": "2"}}
            },
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
its shape, and returns a validated ``Workflow``. Pass ``shape="dag"``, ``"v1"`` (a
``PipeDef``), or ``"v2"`` (a ``WorkflowDocument``) to pin the reading instead.
``flow.serialize()`` writes the ``WorkflowDocument``, which parses back to an
equivalent ``Workflow``. ``Workflow.load(path)`` reads and parses a file:

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

A wire's optional third entry names the port it enters. An operator that takes more than
one stream (such as ``union`` or ``join``) is expressible directly. The first stream
enters the default port ``in``. Each additional stream enters a numbered port starting
at ``in:1``, so ``in:1`` is the second input:

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

A ``conf`` entry written as ``{"terminal": "<name>", "type": ...}`` is a *terminal
reference*. It takes its value from the node wired into the ``in:<name>`` port. A name
that starts with a digit gets a leading underscore, so ``1_URL`` is wired into
``in:_1_URL``. Each time the module resolves its ``conf``, the entry receives the next
item that node produces. A module with no stream wired into ``in`` (such as ``fetch``
below) resolves it once. A ``processor`` module fed a ``stream`` resolves it once per input
``item``.

.. code-block:: json

    {
        "modules": [
            {
                "id": "url",
                "name": "urlbuilder",
                "conf": {"base": "https://example.com/feed.xml"}
            },
            {
                "id": "feed",
                "name": "fetch",
                "conf": {"url": {"terminal": "1_URL", "type": "url"}}
            }
        ],
        "wires": [
            ["url", "feed", "in:_1_URL"]
        ]
    }

Conversion rules (``Workflow.parse``)
-------------------------------------

When calling ``Workflow.parse`` on a ``PipeDag``, the following occurs:

1. Modules missing an ``id`` are assigned ``sw-{n}`` in 1-based listing order.
2. When ``wires`` is omitted or empty, consecutive modules are wired in listing order.
3. Each wire becomes an edge leaving the source's ``out`` port and entering the
   target's ``in`` port (or the port named by the wire's third entry).
4. Empty ``modules``, a wire referencing an unknown module, a cycle, or a wire with the
   wrong number of entries raise ``InvalidPipelineError``.

Unlike a ``PipeDef``, there is **no** ``output`` node. The workflow yields items from
the one module that is never a wire's source. ``parse`` returns a validated
``Workflow``. List its node ids with ``nodes``, and its module names with
``dependencies``. Run it with ``Pipeline``, serialize it to a ``WorkflowDocument`` with
``flow.serialize()``, or hand it to ``compile_workflow``.

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
    >>> flow.dependencies
    ('forever', 'truncate')
    >>> list(Pipeline(flow))
    [{'forever': True}, {'forever': True}, {'forever': True}]

When calling ``Workflow.parse`` on a ``PipeDef``, you must list every wire. Each wire is
an object whose ``src`` and ``tgt`` name a module and a port (``_OUTPUT`` or
``_INPUT``). The ``output`` module marks the workflow's output. Additionally, each
module must name its module in ``type`` and provide both an ``id`` and a ``conf``.

The ``PipeDef`` below builds the same pipeline as the ``PipeDag`` above:

.. code-block:: python

    >>> from riko import Pipeline, Workflow
    >>>
    >>> pipe_def = {
    ...     'modules': [
    ...         {'id': 'sw-1', 'type': 'forever', 'conf': {}},
    ...         {
    ...             'id': 'sw-2',
    ...             'type': 'truncate',
    ...             'conf': {'count': {'type': 'int', 'value': '3'}},
    ...         },
    ...         {'id': '_OUTPUT', 'type': 'output', 'conf': {}},
    ...     ],
    ...     'wires': [
    ...         {
    ...             'src': {'id': '_OUTPUT', 'moduleid': 'sw-1'},
    ...             'tgt': {'id': '_INPUT', 'moduleid': 'sw-2'},
    ...         },
    ...         {
    ...             'src': {'id': '_OUTPUT', 'moduleid': 'sw-2'},
    ...             'tgt': {'id': '_INPUT', 'moduleid': '_OUTPUT'},
    ...         },
    ...     ],
    ... }
    >>> flow = Workflow.parse(pipe_def)
    >>> list(flow.nodes)
    ['sw-1', 'sw-2']
    >>> flow.outputs['default']
    Endpoint(node='sw-2', port='out')
    >>> list(Pipeline(flow))
    [{'forever': True}, {'forever': True}, {'forever': True}]

Unlike ``PipeDag``, ``PipeDef`` can have inputs. The below example extends the above by
showing how you can feed ``truncate`` a count read from an ``input`` module. Its wire
enters at the terminal ``count``:

.. code-block:: python

    >>> from riko import Context, Pipeline, Workflow
    >>>
    >>> pipe_def = {
    ...     'modules': [
    ...         {'id': 'sw-1', 'type': 'forever', 'conf': {}},
    ...         {
    ...             'id': 'sw-2',
    ...             'type': 'truncate',
    ...             'conf': {'count': {'terminal': 'count', 'type': 'int'}},
    ...         },
    ...         {
    ...             'id': 'sw-3',
    ...             'type': 'input',
    ...             'conf': {
    ...                 'name': 'count',
    ...                 'type': 'int',
    ...                 'default': '3',
    ...                 'prompt': 'How many items?',
    ...             },
    ...         },
    ...         {'id': '_OUTPUT', 'type': 'output', 'conf': {}},
    ...     ],
    ...     'wires': [
    ...         {
    ...             'src': {'id': '_OUTPUT', 'moduleid': 'sw-1'},
    ...             'tgt': {'id': '_INPUT', 'moduleid': 'sw-2'},
    ...         },
    ...         {
    ...             'src': {'id': '_OUTPUT', 'moduleid': 'sw-3'},
    ...             'tgt': {'id': 'count', 'moduleid': 'sw-2'},
    ...         },
    ...         {
    ...             'src': {'id': '_OUTPUT', 'moduleid': 'sw-2'},
    ...             'tgt': {'id': '_INPUT', 'moduleid': '_OUTPUT'},
    ...         },
    ...     ],
    ... }
    >>> flow = Workflow.parse(pipe_def)
    >>> dict(flow.input_schemas['count'])
    {'type': 'integer', 'default': 3, 'description': 'How many items?'}
    >>> pipeline = Pipeline(flow)
    >>> list(pipeline)
    [{'forever': True}, {'forever': True}, {'forever': True}]
    >>> list(pipeline.with_context(Context(inputs={'count': 2})))
    [{'forever': True}, {'forever': True}]
    >>> Workflow.parse(flow.serialize()) == flow
    True

Workflow inputs
---------------

While a ``PipeDag`` has no inputs, a ``WorkflowDocument`` may list a top-level
``input_schemas``. It maps each input to its `JSON Schema`_ (draft 7) ``InputSchema``.
Any JSON Schema keyword is allowed, and ``type`` must name JSON types. A bare JSON type
name is shorthand (``"string"`` reads as ``{"type": "string"}``). An input whose schema
has no ``default`` is required, and a node's ``conf`` or ``map`` keyword refers to an
input as ``{"input": name}``.

A run fills values from its context's ``inputs`` or ``InputSchema``\'s ``default``. It
also checks the given values against their ``InputSchema``. It rejects missing inputs
and invalid values, and substitutes values for their references.

.. code-block:: python

    >>> from riko import Context, Pipeline, Workflow
    >>>
    >>> document = {
    ...     "input_schemas": {
    ...         "count": {
    ...             "type": "integer",
    ...             "default": 3,
    ...             "description": "How many items?",
    ...         }
    ...     },
    ...     "nodes": [
    ...         {"id": "sw-1", "name": "forever"},
    ...         {
    ...             "id": "sw-2",
    ...             "name": "truncate",
    ...             "conf": {"count": {"input": "count"}},
    ...         },
    ...     ],
    ...     "edges": [{"source": {"node": "sw-1"}, "target": {"node": "sw-2"}}],
    ... }
    >>> flow = Workflow.parse(document)
    >>> pipeline = Pipeline(flow)
    >>> list(pipeline)
    [{'forever': True}, {'forever': True}, {'forever': True}]
    >>> list(pipeline.with_context(Context(inputs={"count": 2})))
    [{'forever': True}, {'forever': True}]

``"default": null`` allows ``null``. ``flow.input_schemas`` lists a parsed workflow's
input schemas, and ``flow.validate()`` validates them.

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
``PipeDef``, or a ``WorkflowDocument``, and emits a validated ``WorkflowDocument``. It
detects which form it was given. Pass ``--format {dag,v1,v2}`` to pin the reading
instead. The output is indented for reading by default. ``-c``/``--compact`` writes a
byte-stable single-line form. It reports on stderr if it can't read or validate a file,
and exits non-zero.

Convert a serialized ``PipeDef`` with ``build-workflow`` before registering its
directory with ``riko.ext.register_workflow_store``. It migrates the ``input`` module's
configuration to `Workflow inputs`_. It also converts the ``default``, and the
``prompt`` becomes the schema's description.

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
.. _JSON Schema: https://json-schema.org/understanding-json-schema/
