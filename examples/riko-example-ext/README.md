# riko-example-ext

A minimal example of extending **riko** from an external distribution — adding a
new module (`example.shout`) discovered via an entry point, **without editing
riko core**.

## Layout

```
riko-example-ext/
├── pyproject.toml       # declares the entry point
└── riko_example_ext.py  # the pipe + its ModuleDefinition
```

## Ext contract

1. **Author the pipe** with the public `riko.ext` decorators, exactly like a
   built-in. Give it an explicit `-> Stream` (or `-> Iterator[...]`) return
   annotation so riko can infer its metadata. For an async pipe, only use `async def`
   when the parser itself awaits I/O).
2. **Expose a `ModuleDefinition`** (`shout_definition`). Point `module` at
   something exposing `pipe`/`async_pipe` (here, the module itself), or pass the
   callables explicitly as `sync_pipe`/`async_pipe`.
3. **Declare an entry point** under the `riko.modules` group in `pyproject.toml`:

   ```toml
   [project.entry-points."riko.modules"]
   "example.shout" = "riko_example_ext:shout_definition"
   ```

That's it. riko's `ModuleRegistry` discovers the entry point by name and imports
this package only when `example.shout` is first resolved.

## Use it

```bash
uv pip install -e .           # alongside riko
```

```python
from riko.collections import SyncPipe

SyncPipe("example.shout", source=[{"content": "hi"}])
# → [{"content": "HI"}]
```

The name is a plain string, so it also works in JSON pipelines and everywhere
else riko accepts a module name — no dependency on this package's Python objects.

## No packaging? Register at runtime instead

When you don't need a discoverable, installable plugin, skip the entry point and
call `riko.ext.register` directly:

- [`../register_module.py`](../register_module.py) — explicit `sync_pipe=`/`async_pipe=` callables.
- [`../register_alias.py`](../register_alias.py) — the `module=` convention, aliasing a built-in.
