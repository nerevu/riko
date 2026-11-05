---
source: ../../../../pyconvert/README.md
---

# pyconvert

## Introduction

pyconvert is a [Python library](#library) for converting tabular data from one file
format to another. It reads records with [tabutils](https://github.com/reubano/tabutils)
and writes them back out in a different format. The working surface is the library
function `pyconvert.convert()`. A [command-line tool](#command-line) is drafted in
`bin/pyconvert` but is unfinished and not installed.

With pyconvert, you can

- Read CSV / XLS / XLSX / DBF / MDB files
- Write CSV / JSON / GeoJSON / vCard files
- Convert between any supported input and output format
- Pipe data via STDIN/STDOUT
- Read Uñicôdë text

## Requirements

pyconvert has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.10

pyconvert requires the following in order to run properly:

- [Python 2.7](http://www.python.org/download) (`setup.py` declares only Python 2
  classifiers; Python 3 is untested)

It also depends on `tabutils` and `csv2vcard` (pinned in `requirements.txt`:
`tabutils==0.17.0`, `csv2vcard==0.6.0`, `manage.py==0.2.10`).

## Installation

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

pyconvert is not published on PyPI under this name (the PyPI package `pyconvert` is an
unrelated project). Install it from a checkout:

```bash
pip install -r requirements.txt
pip install .
```

This installs the `pyconvert` package only. `setup.py` declares no `scripts` or
`entry_points`, so no `pyconvert` command is put on your path.

## Supported formats

| Direction | Formats | Functions (`pyconvert.io`) |
| --------- | ------- | -------------------------- |
| Input     | `csv`, `xls`, `xlsx`, `dbf`, `mdb` | `from_csv`, `from_xls` (also used for `xlsx`), `from_dbf`, `from_mdb` |
| Output    | `csv`, `json`, `geojson`, `vcf` / `vcard` | `to_csv`, `to_json`, `to_geojson`, `to_vcard` |

The source and destination formats are inferred from the file extensions of
`source.name` and `dest.name` unless `src_ext`/`dest_ext` are given. Inference takes the
text after the last `.` of the name, so a file object whose name has no extension
(`<stdin>`, `<stdout>`, a `StringIO`) needs the format passed explicitly, otherwise
`convert` raises `IndexError` (`pyconvert/__init__.py:111-113`). An extension outside
the table raises `ValueError('Input format "..." is not supported.')` or
`ValueError('Output format "..." is not supported.')`.

Other names in `pyconvert.io` are not part of the conversion table:

- `from_json` exists but is not registered as an input format, so `json` input raises
  `ValueError`.
- `to_xls`, `to_xlsx`, `to_qif`, `to_ofx`, `to_gpx`, `to_ical`, `to_dbf`, and `to_hdf`
  are stubs that return `None` (`pyconvert/io.py:86-139`).
- `hdx`/`hdxify` are an unrelated timesheet helper, not a converter.

### vCard output

`to_vcard` builds cards with `csv2vcard.vcard.gen_cards`. `convert` calls the writer
with the records only (`pyconvert/__init__.py:121`), so vCard output always uses
csv2vcard's `default` mapping and no contact group. The source columns must therefore
use that mapping's names, e.g. `first_name`, `middle_name`, `last_name`, `prefix`,
`suffix`, `job_title`, `organization`, `birthday`, `e_mail_address`, `phone`, `mobile`,
`street`, `city`, `state`, `zip`, `country`, and the `work_*`/`other_*` address and
contact columns (see `csv2vcard/mappings/default.py`). To choose another mapping or a
group, call `pyconvert.io.to_vcard(records, mapping=..., group=...)` yourself.

## Library

pyconvert is used directly from Python.

```python
from pyconvert import convert

with open("file.csv") as source, open("file.json", "w") as dest:
    convert(source, dest)
```

### `convert(source, dest, src_ext=None, dest_ext=None, **kwargs)`

| Argument | Default | Meaning |
| -------- | ------- | ------- |
| `source` | required | an open file object to read |
| `dest` | required | an open file object to write |
| `src_ext` | extension of `source.name` | the input format (a key of the input table above) |
| `dest_ext` | extension of `dest.name` | the output format (a key of the output table above) |
| `**kwargs` | none | forwarded unchanged to the input reader only |

`convert` reads every record with the reader for `src_ext`, passes the records to the
writer for `dest_ext` with no options, and writes the result to `dest` with
`tabutils.io.write`. It returns `None`. Open the source in whatever mode the tabutils
reader for that format expects; the draft script opens every source as `r+b`.

Every keyword argument goes to the reader (`pyconvert/__init__.py:116`); none reaches
the writer. Whether a given keyword (for example `encoding`, `sheet`, `sanitize`,
`dedupe`, or `has_header`) has an effect depends on the tabutils reader for that format.

To convert from STDIN to STDOUT, give both formats, because the standard streams have no
file extension:

```python
import sys

from pyconvert import convert

convert(sys.stdin, sys.stdout, src_ext="csv", dest_ext="json")
```

## Command line

`bin/pyconvert` is an unfinished draft of a command-line front end. It is not tracked in
the repository, not installed by `setup.py`, and does not compile:
`python -m py_compile bin/pyconvert` fails with
`IndentationError: unindent does not match any outer indentation level` at line 76 (tabs
and spaces are mixed). The usage and options below describe what the draft defines; none
of them can be run today. Use the [library](#library) instead.

```text
pyconvert [options] <source> <dest>
```

The draft's help text says that with no arguments it reads from STDIN and writes to
STDOUT. Even if the script compiled, that call would fail: STDIN and STDOUT have no file
extension, so `-s` and `-d` would be required (see
[Supported formats](#supported-formats)).

### Options

These options are defined by the draft script. `-D` and `-v` would stop before
converting. Otherwise every option, including `debug`, `verbose`, and `version` with
their `False` values, is passed as a keyword argument to the reader through `convert`,
and `-n` becomes `has_header=False`. None of them configures the writer.

| option | description |
| ------ | ----------- |
| `-s, --src-ext EXT` | the source file extension/format |
| `-d, --dest-ext EXT` | the destination file extension/format |
| `-e, --encoding` | file encoding |
| `-S, --sheet NUM` | zero-indexed sheet to open (xls/xlsx), default `0` |
| `-a, --sanitize` | underscorify and lowercase field names |
| `-u, --dedupe` | deduplicate field names |
| `-n, --no-header` | source has no header row |
| `-D, --debug` | display the parsed options and arguments |
| `-v, --version` | show version and exit |
| `-V, --verbose` | verbose output |

### Examples

These are the intended invocations of the draft script; they do not run today. The
library equivalent of each is shown underneath.

*Convert a CSV file to JSON*

```bash
pyconvert path/to/file.csv path/to/file.json
```

```python
with open("path/to/file.csv") as source, open("path/to/file.json", "w") as dest:
    convert(source, dest)
```

*Convert an Excel file to vCard* (the sheet must use csv2vcard's default column names;
see [vCard output](#vcard-output))

```bash
pyconvert contacts.xlsx contacts.vcf
```

```python
with open("contacts.xlsx", "rb") as source, open("contacts.vcf", "w") as dest:
    convert(source, dest)
```

*Convert a DBF to GeoJSON, specifying formats explicitly*

```bash
pyconvert data.dbf data.geojson -s dbf -d geojson
```

```python
with open("data.dbf", "rb") as source, open("data.geojson", "w") as dest:
    convert(source, dest, src_ext="dbf", dest_ext="geojson")
```

*Pipe from STDIN to STDOUT*

```bash
cat file.csv | pyconvert -s csv -d json > file.json
```

See the STDIN/STDOUT example under [Library](#library).

## Scripts

pyconvert comes with a built-in task manager `manage.py`.

### Setup

```text
pip install -r dev-requirements.txt
```

### Examples

*Run the linter and tests*

```bash
manage lint
manage test
```

`manage test` runs `helpers/test`, which runs `nosetests` and then `tests/test.py`. The
script tests in `tests/test.py` call `bin/convert --help` and `bin/pyconvert`, so they
fail (see [Known issues](#known-issues)).

## Known issues

- The command-line tool is not installed: `setup.py:63-98` declares no `scripts` or
  `entry_points`, and `bin/pyconvert` is untracked.
- `bin/pyconvert` does not compile: `IndentationError` at `bin/pyconvert:76` (mixed tabs
  and spaces).
- `bin/pyconvert:77` calls `pprint`, which is never imported, so `-D/--debug` would
  raise `NameError`.
- `bin/pyconvert:79` uses `from . import __version__` inside a script, so `-v/--version`
  would raise `ImportError`.
- `bin/pyconvert:70` calls `parser.parse_args()` at import time, so importing the script
  parses the importer's command line.
- Reading from STDIN or writing to STDOUT without `src_ext`/`dest_ext` raises
  `IndexError` because the extension is taken from the stream name
  (`pyconvert/__init__.py:111-113`).
- vCard output cannot choose a mapping or group: `convert` calls the writer with no
  options (`pyconvert/__init__.py:121`).
- Every keyword given to `convert` goes to the reader; writers receive none
  (`pyconvert/__init__.py:116`, `:121`).
- `manage test` fails at its script tests: `tests/test.py:35` runs `bin/convert --help`,
  which does not exist, and `tests/test.py:60` runs the uncompilable `bin/pyconvert`.

## License

pyconvert is distributed under the [MIT License](http://opensource.org/licenses/MIT).
