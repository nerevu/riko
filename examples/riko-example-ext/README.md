# riko-example-ext

A minimal example of extending **riko** from an external distribution by adding a
new module (`example.shout`) via an entry point.

## Layout

```
riko-example-ext/
├── pyproject.toml       # declares the entry point
└── riko_example_ext.py  # the pipe (authored like a built-in module)
```

## Ext contract

1. **Author the pipe** with the public `riko.ext` decorators, exactly like a
   built-in. Give it an explicit `-> Stream` (or `-> Iterator[...]`) return
   annotation so riko can infer its metadata. For an async pipe, only use `async def`
   when the parser itself awaits I/O).
2. **Declare an entry point** under the `riko.modules` group in `pyproject.toml`,
   pointing it at the module itself:

   ```toml
   [project.entry-points."riko.modules"]
   "example.shout" = "riko_example_ext"
   ```

That's it. riko's `ModuleRegistry` reads `pipe`/`async_pipe` off the module and
takes its docstring summary as the discovery `description`
(`describe_module("example.shout")`). The package is imported only when `example.shout`
is first resolved.

For finer control, an entry point may instead name a `ModuleDefinition` (or a
zero-arg factory returning one). See [`../register_module.py`](../register_module.py).

## Use it

```bash
uv pip install -e .  # alongside riko
```

```python
from riko.collections import SyncPipe

next(SyncPipe("example.shout", source=[{"content": "hi"}]))
# {"content": "HI"}
```

## No packaging? Register at runtime instead

When you don't need a discoverable, installable plugin, skip the entry point and
call `riko.ext.register` directly:

- [`../register_module.py`](../register_module.py): explicit `sync_pipe=`/`async_pipe=` callables.
- [`../register_alias.py`](../register_alias.py): the `module=` convention.
