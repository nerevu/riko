# Yahoo Pipes module documentation

status.csv cannot be accurately regenerated from the current runtime catalog alone.

The file combines three different categories of information:

Historical Yahoo Pipes migration data
name
new_name
original
orig_type
Deprecated
alt
input
intype
output
outtype
Current implementation metadata
implemented
new_type
new_sub_type
loopable
listize
extract
field
ftype
ptype
emit
Obsolete or redundant migration fields
converted
dictize
pdictize

The current CSV already has stale runtime values. For example, regex, rename, and subelement are marked non-loopable even though they are processors other than input; regex is also recorded with emit=FALSE, while its current decorator explicitly sets emit=True.

The generator should therefore derive runtime facts from code and merge them with a small static historical manifest.

Recommended structure
riko/
  data/
    status.csv                 # generated; committed
    status_manifest.csv        # manually maintained historical data

scripts/
  generate_status.py

tests/
  test_generate_status.py

I would not make this a [project.scripts] entry point. The existing entries are user-facing application commands, whereas status generation is a repository maintenance operation.

1. Create a historical manifest

The manifest should contain only facts that cannot be discovered from the current Python modules.

I would use this schema:

name,module,new_name,original,orig_type,deprecated,alt,input,intype,output,outtype,target_type,target_subtype,target_loopable

Meaning:

Field   Purpose
name    Original Yahoo Pipes identifier, such as pipecsv
module  Actual Riko module name, such as csv
new_name    Historical renamed/display name, such as fetchcsv
original    Whether it originated in Yahoo Pipes
orig_type   Original Yahoo Pipes type
deprecated  Whether this historical identity is deprecated
alt Replacement or alias
input through outtype   Historical input/output model
target_type Intended type for an unimplemented pipe
target_subtype  Intended subtype for an unimplemented pipe
target_loopable Intended loopability for an unimplemented pipe

The separate module field is important. new_name is not consistently the importable module name: the current CSV maps pipecsv to fetchcsv, while the actual module is riko.modules.csv.

For implemented rows:

pipecsv,csv,fetchcsv,TRUE,source,FALSE,,n/a,n/a,items,item,,,
piperegex,regex,regex,TRUE,operator,FALSE,pipestrregex,item,text,items,text,,,

For unimplemented rows:

pipemax,,max,FALSE,operator,FALSE,,items,number,items,number,operator,aggregator,FALSE

The generator uses target_* only when module is absent or cannot be found.

2. Expose a stable runtime-options snapshot

The proposed ModuleMetadata gives the generator:

name
type
subtype
supported_subtypes
pollable
loopable
has_sync
has_async

That is enough for most status columns, but not:

listize
extract
field
ftype
ptype
emit

Those values currently live inside the decorator instance’s private _opts. The wrapper only exposes type, name, sub_type, and pollable.

Do not have the generator inspect closure cells. Instead, attach a frozen normalized snapshot when the wrapper is created.

For example:

from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Mapping


type EmitMode = Literal["auto", "true", "false"]


@dataclass(frozen=True, slots=True)
class ModuleOptions:
    listize: bool
    extract: str | None
    field: str | None
    ftype: BasicCastType
    ptype: BasicCastType
    emit: EmitMode

Inside the decorator:

def _status_options(self) -> ModuleOptions:
    declared_emit = self._opts.get("emit")

    if declared_emit is True:
        emit = "true"
    elif declared_emit is False:
        emit = "false"
    else:
        emit = "auto"

    return ModuleOptions(
        listize=bool(self._opts.get("listize", False)),
        extract=self._opts.get("extract"),
        field=self._opts.get("field"),
        ftype=self._opts["ftype"],
        ptype=self._opts["ptype"],
        emit=emit,
    )

Then attach it alongside the other wrapper metadata:

setattr(wrapper, "options", self._status_options())
Why emit needs three states

A boolean is not sufficient. When emit is unspecified, its resolved behavior can depend on module type, source status, or the actual returned value. The decorator internally treats an unspecified value differently from explicit True or False.

Use:

TRUE
FALSE
AUTO

in the generated CSV. Recording AUTO as FALSE would continue the current ambiguity.

3. Build the generator around list_modules

The generator should consume the same catalog used by the public discovery API rather than scanning modules independently.

Suggested structure:

from __future__ import annotations

import argparse
import csv
import io
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from riko.modules import list_modules
from riko.types.modules import ModuleMetadata

Core functions:

COLUMNS = (
    "name",
    "module",
    "new_name",
    "original",
    "implemented",
    "orig_type",
    "new_type",
    "new_sub_type",
    "Deprecated",
    "converted",
    "loopable",
    "alt",
    "input",
    "intype",
    "output",
    "outtype",
    "listize",
    "extract",
    "field",
    "ftype",
    "ptype",
    "dictize",
    "emit",
    "pdictize",
)


def load_manifest(path: Path) -> tuple[ManifestRow, ...]:
    ...


def load_runtime_modules() -> dict[str, ModuleMetadata]:
    modules = list_modules(show_metadata=True)
    return {module.name: module for module in modules}


def build_rows(
    manifest: Iterable[ManifestRow],
    modules: dict[str, ModuleMetadata],
) -> tuple[dict[str, str], ...]:
    ...


def render_csv(rows: Iterable[dict[str, str]]) -> str:
    ...


def generate(manifest_path: Path) -> str:
    manifest = load_manifest(manifest_path)
    modules = load_runtime_modules()
    rows = build_rows(manifest, modules)
    return render_csv(rows)
4. Define field precedence explicitly

For each manifest row:

runtime = modules.get(manifest.module)
implemented = runtime is not None

Then populate fields as follows.

Output field    Source
name    Manifest
module  Manifest/current catalog
new_name    Manifest
original    Manifest
implemented Whether runtime module exists
orig_type   Manifest
new_type    Runtime type, otherwise manifest target
new_sub_type    Runtime subtype, otherwise manifest target
Deprecated  Manifest
converted   Usually same as implemented
loopable    Runtime metadata, otherwise manifest target
alt Manifest
input–outtype   Manifest
listize–ptype   Runtime options when implemented
emit    Runtime option mode when implemented
dictize Remove, blank, or explicitly retain as legacy
pdictize    Remove, blank, or explicitly retain as legacy

Derived fields must always override historical values. There should not be a manifest override for an implemented module’s type, subtype, loopable, or decorator options.

5. Include runtime-only modules automatically

The current CSV omits several modules that are now listed in the code-level classifications. The current package lists aggregators, composers, sources, and transformers directly, including modules such as aggregate, timeout, join, loop, forever, geolocate, slugify, typecast, udf, and urlparse.

After processing the manifest:

referenced = {
    row.module
    for row in manifest
    if row.module is not None
}

for name, metadata in modules.items():
    if name not in referenced:
        rows.append(build_runtime_only_row(metadata))

A runtime-only row might look like:

,loop,loop,FALSE,TRUE,,operator,composer,FALSE,TRUE,FALSE,,,,,,,,pass,pass,,AUTO,

Do not invent a Yahoo Pipes name such as pipeloop unless it really had one.

6. Deterministic ordering

Preserve the broad grouping of the current file:

Unimplemented historical modules
Implemented active modules
Runtime-only modules
Deprecated historical aliases

Within each group, sort by:

row["name"] or row["module"]

For example:

def status_rank(row: StatusRow) -> int:
    if row.deprecated:
        return 3

    if not row.implemented:
        return 0

    if not row.original:
        return 2

    return 1

Then:

rows.sort(
    key=lambda row: (
        status_rank(row),
        row.name or row.module,
    )
)
7. Normalize serialization

Use one canonical representation:

def csv_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def csv_optional(value: object | None) -> str:
    if value is None:
        return ""

    if hasattr(value, "value"):
        return str(value.value)

    return str(value)

Use:

csv.DictWriter(
    stream,
    fieldnames=COLUMNS,
    lineterminator="\n",
)

The current CSV inconsistently uses blank cells, None, n/a, and booleans. The generator should distinguish:

blank: unknown or not applicable
n/a: historical value explicitly designated not applicable
AUTO: dynamically determined runtime behavior
TRUE / FALSE: actual booleans
8. CLI behavior
uv run python scripts/generate_status.py

Writes:

riko/data/status.csv

Add check mode:

uv run python scripts/generate_status.py --check

Behavior:

if args.check:
    existing = output_path.read_text(encoding="utf-8")

    if existing != generated:
        print("riko/data/status.csv is stale")
        return 1

    return 0

Useful arguments:

--check
--output PATH
--manifest PATH

Avoid an --update-manifest option. The manifest represents intentional historical decisions and should not be inferred or silently rewritten.

9. Validation rules

The generator should fail before writing when:

A manifest name appears more than once.
An active canonical runtime mapping appears more than once.
A row is marked deprecated but has neither alt nor a valid canonical module.
An implemented manifest row points to a nonexistent module.
Runtime sync and async wrappers disagree on metadata.
An unimplemented row lacks target_type or target_subtype.
A manifest tries to override derived runtime metadata.
A runtime module is omitted from the final result.
A generated row has a column not listed in COLUMNS.

Allow multiple historical aliases to point to the same runtime module, particularly deprecated aliases.

10. Tests

Minimum test set:

def test_generation_is_deterministic():
    first = generate(MANIFEST)
    second = generate(MANIFEST)

    assert first == second
def test_checked_in_status_is_current():
    generated = generate(MANIFEST)
    existing = STATUS.read_text(encoding="utf-8")

    assert generated == existing
def test_every_runtime_module_is_exported():
    rows = parse_generated_status()
    exported = {row["module"] for row in rows if row["module"]}
    runtime = set(list_modules())

    assert runtime <= exported
def test_runtime_metadata_wins_over_manifest():
    row = get_row("regex")

    assert row["implemented"] == "TRUE"
    assert row["new_type"] == "processor"
    assert row["new_sub_type"] == "transformer"
    assert row["loopable"] == "TRUE"
    assert row["emit"] == "TRUE"
def test_input_is_the_only_non_loopable_processor():
    rows = parse_generated_status()

    modules = {
        row["module"]
        for row in rows
        if row["new_type"] == "processor"
        and row["loopable"] == "FALSE"
        and row["implemented"] == "TRUE"
    }

    assert modules == {"input"}
Recommended implementation sequence
Finalize ModuleMetadata and list_modules.
Add immutable decorator-option metadata to wrappers.
Extract historical-only information from the current CSV into status_manifest.csv.
Implement the merge and validation functions.
Generate the first new status.csv.
Review the intentional diff, especially stale loopable and emit values.
Add --check to CI.
Later remove dictize and pdictize; code search currently finds them only in the status file and documentation, not in runtime implementation.

The important boundary is: code owns current behavior; the manifest owns history; status.csv is only the generated report.

---

# Shelf integration addendum

## Built-in versus extension documentation

`status.csv` remains a Yahoo Pipes migration and built-in runtime report. It must not
become a cross-package connector catalog.

When the declarative transformation work lands, built-in modules such as:

```text
coalesce
strtransform
dropfields
```

appear automatically as runtime-only rows through `list_modules()` unless a real Yahoo
Pipes identity exists in the historical manifest.

Protocol, storage, SQL, dbt, orchestration, and optional enrichment modules installed
from extension packages are documented through:

```text
riko modules list
riko plugins list
package-owned generated reference pages
```

The status generator should support an explicit `builtins_only=True` catalog query so an
installed connector extra cannot make the checked-in `status.csv` nondeterministic.
Tests must verify that entry-point modules are excluded from this historical report while
remaining visible in the public module registry.
