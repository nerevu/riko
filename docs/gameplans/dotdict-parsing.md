# DotDict parsing sufficiently protect ordinary business data?

It reduces accidental interpretation because only two-element sequences qualify. But this is still structurally ambiguous:

["active", "text"]

could be:

a Riko typed value sequence;
an ordinary two-value business list.

So the guard reduces collisions but does not eliminate them.

The risk depends on where it is called:

parse_conf(conf=...)

is a safe context because the caller has declared the object to be configuration.

DotDict(record).get(...)

is still risky because the caller may be reading arbitrary business data.

Recommended implementation

Keep the sequence recognition, but make it precise and invoke it only during configuration parsing:

type ValueSeq = tuple[BasicValue, BasicValue]


def parse_value_seq(
    val: object,
) -> ValueSeq | None:
    if not isinstance(val, (list, tuple)) or len(val) != 2:
        return None

    first, second = val

    if not (
        isinstance(first, BasicValueType)
        and isinstance(second, BasicValueType)
    ):
        return None

    return first, second

Then:

def parse_conf(...):
    if value_seq := parse_value_seq(conf):
        ...

Is expressing types in plain text valuable enough?

Yes, as a configuration interchange format.

No, as an implicit interpretation rule for arbitrary DotDict values.

The best design is:

Keep the typed-value representation
Move its interpretation to configuration parsing
Make ordinary DotDict access literal
Recommended boundary

DotDict should handle:

nested paths
case-insensitive keys
raw retrieval
defaults
ordinary mapping behavior

parse_conf() should handle:

typed values
terminal references
subkeys
casting
dynamic configuration
configuration-specific sentinels

Conceptually:

raw = DotDict(conf).get_raw("URL")
url = parse_conf(item, raw)

or simply:

url = parse_conf(item, conf["URL"])

Business data remains literal:

item = DotDict(
    {
        "type": "currency",
        "value": 100,
    }
)

assert item.get("type") == "currency"
assert item.get("value") == 100

Configuration is interpreted explicitly:

conf = {
    "type": "url",
    "value": "example.com/feed",
}

assert parse_conf(conf=conf) == "http://example.com/feed"
Practical migration without breaking legacy pipelines

You do not need to remove the current behavior immediately.

Phase 1: distinguish raw and configuration access

Add or formalize a raw path:

DotDict.get_raw(...)

or:

DotDict.get(..., parse=False)

Then make configuration code explicitly request parsing.

I prefer a separate raw method over a boolean flag because call sites are clearer:

record.get_raw("value")

versus:

record.get("value", parse=False)
Phase 2: move typed parsing into parse_conf

Replace internal calls where DotDict.get() is being used to interpret configuration with:

parse_conf(item, conf)

Keep legacy behavior temporarily, but emit a warning only when ambiguous typed mappings are encountered outside known configuration paths.

Phase 3: make DotDict literal by default

After internal call sites and tests are converted:

DotDict.get()

returns stored data.

parse_conf()

interprets Riko configuration.

Phase 4: optionally retain compatibility mode

For loading old Yahoo Pipes definitions:

DotDict(..., config_mode=True)

or preferably at the workflow boundary:

parse_pipe_def(..., legacy_typed_values=True)

This keeps compatibility scoped to imported workflow definitions rather than spreading it across all runtime data.

