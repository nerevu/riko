# riko-example-ext

A minimal example of extending **riko** from an external distribution — adding a
new module (`example.shout`) **without editing riko core**.

## Ext contract

1. **Author a module** with the public `riko.ext` decorators, exactly like a
   built-in (`src/riko_example_ext/shout.py`). Give the pipe an explicit
   `-> Stream` or `-> Iterator[...]` return annotation so riko can infer its metadata.
2. **Expose a `ModuleDefinition`** (`src/riko_example_ext/modules.py`) that provides the
   module and its description.
3. **Declare an entry point** under the `riko.modules` group in `pyproject.toml`:

   ```toml
   [project.entry-points."riko.modules"]
   "example.shout" = "riko_example_ext.modules:shout_definition"
   ```

That's it. riko's `ModuleRegistry` discovers the entry point by name and imports this
package only when `example.shout` is first resolved.

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
