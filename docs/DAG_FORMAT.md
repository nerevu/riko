# Bare-bones DAG format

riko pipelines are stored as verbose JSON pipe definitions (`tests/pipelines/*.json`):
every wire is a full `src`/`tgt` endpoint record, and a terminal `output` module is
always present. The **bare-bones DAG** is a minimal authoring format that captures only
the essentials and expands to a full pipe definition via `convert_dag`.

## Schema

```json
{
    "modules": [
        {"id": "sw-1", "type": "forever", "conf": {}},
        {"id": "sw-2", "type": "truncate", "conf": {"count": {"type": "number", "value": "3"}}}
    ],
    "wires": [
        ["sw-1", "sw-2"]
    ]
}
```

- **`modules`** — the same `id`/`type`/`conf` triples used in a full pipe definition.
  `conf` is **opaque**: it is copied through verbatim, so any module's native
  configuration is valid without transformation. `id` is *optional* and defaults to
  `sw-{n}` (1-based listing order); supply ids only when `wires` reference them.
- **`wires`** — *optional* list of `[source_id, target_id]` pairs. The verbose
  `{"src": {...}, "tgt": {...}}` endpoints and wire ids are generated for you.
  When `wires` is omitted or empty, the modules are chained **linearly in listing
  order**, so the concise form drops both `wires` and `id`
  (see `tests/dags/pipe_forever.json`):

```json
{
    "modules": [
        {"type": "forever", "conf": {}},
        {"type": "truncate", "conf": {"count": {"type": "number", "value": "3"}}}
    ]
}
```

Provide `wires` when the module listing order is **not** the execution order —
e.g. the source is listed after the operator it feeds
(see `tests/dags/pipe_reordered.json`):

```json
{
    "modules": [
        {"id": "trunc", "type": "truncate", "conf": {"count": {"type": "number", "value": "2"}}},
        {"id": "gen", "type": "forever", "conf": {}}
    ],
    "wires": [
        ["gen", "trunc"]
    ]
}
```

## Expansion rules (`convert_dag`)

`riko.compile.convert_dag(dag)` returns a full pipe definition:

1. Modules missing an `id` are assigned `sw-{n}` in 1-based listing order.
2. When `wires` is omitted or empty, consecutive modules are wired in listing order.
3. A terminal `{"id": "_OUTPUT", "type": "output", "conf": {}}` module is appended.
4. Every `[src, tgt]` pair becomes a `_INPUT`/`_OUTPUT` wire.
5. Every **sink** (a module that never appears as a wire source) is connected to
   `_OUTPUT`.

The expanded definition is accepted directly by `parse_pipe_def` / `build_pipeline`
and produces the same stream as the equivalent hand-written pipeline.

## Limitation

Every expanded wire targets `_INPUT`, so fan-in operators such as `union`/`join`
— whose secondary inputs need `_OTHER{n}` targets in a full pipe definition —
cannot be expressed by the `[source, target]` pair format. Author those as a full
pipe definition instead.

## Commands

Both are registered in `[project.scripts]`:

```sh
# bare-bones DAG -> full JSON pipeline (stdout, or -o path)
convert_dag tests/dags/pipe_forever.json -o pipe_forever.json

# JSON pipeline -> generated Python module (stdout, or -o path)
compile pipe_forever.json -o pipe_forever.py
```

Chaining them turns a DAG straight into runnable Python:

```sh
convert_dag tests/dags/pipe_forever.json -o pipe_forever.json
compile pipe_forever.json
```

See `tests/dags/pipe_forever.json` for a runnable example and `tests/test_compile.py`
(`test_convert_dag_*`) for the round-trip guarantees.
