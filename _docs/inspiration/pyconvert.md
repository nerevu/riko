# pyconvert

## Introduction

pyconvert is a [Python library](#library) and command-line tool for converting tabular
data from one file format to another. It reads records with
[tabutils](https://github.com/reubano/tabutils) and writes them back out in a different
format.

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

- [Python >= 2.7](http://www.python.org/download)

It also depends on `tabutils` and `csv2vcard`.

## Installation

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

    sudo pip install pyconvert

## Supported formats

| Direction | Formats |
| --------- | ------- |
| Input     | `csv`, `xls`, `xlsx`, `dbf`, `mdb` |
| Output    | `csv`, `json`, `geojson`, `vcf` / `vcard` |

By default the source and destination formats are inferred from the file extensions.

## Command line

    pyconvert [options] <source> <dest>

If called with no arguments, pyconvert reads from STDIN and writes to STDOUT. Source and
destination formats are taken from the file extensions unless overridden.

### Options

| option | description |
| ------ | ----------- |
| `-s, --src-ext EXT` | the source file extension/format |
| `-d, --dest-ext EXT` | the destination file extension/format |
| `-e, --encoding` | file encoding |
| `-S, --sheet NUM` | zero-indexed sheet to open (xls/xlsx) |
| `-a, --sanitize` | underscorify and lowercase field names |
| `-u, --dedupe` | deduplicate field names |
| `-n, --no-header` | source has no header row |
| `-D, --debug` | display the parsed options and arguments |
| `-v, --version` | show version and exit |
| `-V, --verbose` | verbose output |

### Examples

*Convert a CSV file to JSON*

```bash
pyconvert path/to/file.csv path/to/file.json
```

*Convert an Excel file to vCard*

```bash
pyconvert contacts.xlsx contacts.vcf
```

*Convert a DBF to GeoJSON, specifying formats explicitly*

```bash
pyconvert data.dbf data.geojson -s dbf -d geojson
```

*Pipe from STDIN to STDOUT*

```bash
cat file.csv | pyconvert -s csv -d json > file.json
```

## Library

pyconvert may also be used directly from Python.

```python
from pyconvert import convert

with open('file.csv') as source, open('file.json', 'w') as dest:
    convert(source, dest)
```

The `pyconvert.io` module exposes the individual readers/writers, e.g. `from_csv`,
`from_xls`, `to_csv`, `to_json`, `to_geojson`, and `to_vcard`.

## Scripts

pyconvert comes with a built-in task manager `manage.py`.

### Setup

    pip install -r dev-requirements.txt

### Examples

*Run the linter and tests*

```bash
manage lint
manage test
```

## License

pyconvert is distributed under the [MIT License](http://opensource.org/licenses/MIT).
