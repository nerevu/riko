---
source: ../../../../csv2vcard/README.md
---

# csv2vcard

## INTRODUCTION

[csv2vcard](http://github.com/reubano/csv2vcard) is a [Python library](#library-example)
and [command line interface program](#cli-examples) that converts CSV files to vCard
(vcf) for importing into Contacts or similar address book programs. csv2vcard has been
tested on the following configuration:

* MacOS X 10.9.5
* Python 2.7.10

## Requirements

csv2vcard requires the following programs in order to run properly:

* [Python 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled).
  Python 3 is not supported.

## INSTALLATION

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

```text
sudo pip install csv2vcard
```

## Usage

csv2vcard is intended to be used either directly from Python or from the command line.

### Library Example

*normal usage*

```python
from __future__ import absolute_import, print_function
from tabutils.io import read_csv

from csv2vcard.vcard import gen_cards

records = read_csv("path/to/file.csv")

for card in gen_cards(records, mapping="default"):
    print(card.serialize())
```

`gen_cards(records, **kwargs)` builds its own `vCard` from a mapping module and yields
one `vobject` vCard per record. It takes these keyword arguments:

keyword | default | description
--------|---------|------------
`mapping` | `default` | name of a module in `csv2vcard/mappings` (imported as `csv2vcard.mappings.<name>`)
`group` | none | the contact group(s), comma separated
`chunksize` | `0` (all rows at once) | number of records to process at a time

Passing a prebuilt vCard instead (`gen_cards(records, vCard(mapping))`) is intended; not
implemented. Today that call raises
`TypeError: gen_cards() takes exactly 1 argument (2 given)`.

To use a mapping dict that isn't in a module under `csv2vcard/mappings`, build the card
yourself with `vCard(mapping)` (`csv2vcard.vcard`) and its `create_card` and `add_*`
methods, as `gen_cards` does.

### CLI Examples

*show help*

```text
csv2vcard -h
```

```bash
usage: csv2vcard [options] <source> <dest>

description: csv2vcard converts a csv file into a vCard

positional arguments:
  source                the source csv file (defaults to stdin)
  dest                  the output file (defaults to stdout)

optional arguments:
  -h, --help            show this help message and exit
  -g GROUP, --group GROUP
                        the contact group
  -m MAPPING, --mapping MAPPING
                        the account mapping
  -C ROWS, --chunksize ROWS
                        number of rows to process at a time
  -V, --version         show version and exit
  -o, --overwrite       overwrite destination file if it exists
  -d, --debug           display the options and arguments passed to the parser
  -v, --verbose         verbose output
```

`-g` takes a comma-separated list; each entry becomes a vCard category
(`-g "Friends,Work"`).

`-m` names a module in `csv2vcard/mappings` (`default` or `custom` ship with csv2vcard).

`-o` gives no protection when `dest` is a file path: the destination file is opened for
writing, and so emptied, as soon as the arguments are parsed, whether or not `-o` is
given.

*normal usage*

```text
csv2vcard file.csv file.vcf
```

*print output to stdout*

```text
csv2vcard file.csv
```

*read input from stdin*

```text
cat file.csv | csv2vcard - file.vcf
```

The first positional argument is always the source, so `-` stands for stdin when a
destination follows. `cat file.csv | csv2vcard` (no arguments) writes to stdout.

*specify a custom mapping*

```text
csv2vcard -m custom file.csv file.vcf
```

`custom` is a template stub to copy and edit: every key maps to `itemgetter('Field')`,
so on a real CSV each lookup falls back to its default and the cards come out empty. It
also lists keys csv2vcard never reads (`role`, `manager`, `tel`, `primary`,
`company_phone`).

## CUSTOMIZATION

### Code modification

If you would like to import csv files with field names different from the default, you
can modify the mapping file or create your own. New mappings must be placed in the
`csv2vcard/mappings` folder. The mapping object consists of a dictionary whose keys are
vCard attributes and whose values can be either a value or a function which returns the
corresponding value from a record (csv row). The mapping function will take in a record,
e.g.,

```python
{"first_name": "first", "last_name": "last", "company": "Work Inc."}
```

The most basic mapping function just returns a specific field, e.g.,

```python
from operator import itemgetter

mapping = {
    "given_name": itemgetter("first_name"),
    "family_name": itemgetter("last_name"),
}
```

But more complex parsing is also possible, e.g.,

```python
mapping = {
    "given_name": lambda r: r["name"].split(" ")[0],
    "family_name": lambda r: r["name"].split(" ")[1],
}
```

A mapping function that raises `KeyError` (a column missing from the CSV) silently
yields the attribute's default, so a misspelled column name produces an empty value
rather than an error. Mapping keys csv2vcard doesn't read (see the tables below) are
ignored.

### Required attributes

None. Every mapping key (attribute) is optional: a key missing from the mapping, or
whose function raises `KeyError`, falls back to its default. The name parts (`prefix`,
`given_name`, `middle_name`, `family_name`, `suffix`) and `nick_name` default to an
empty string; every other attribute defaults to none and is left off the card.

### Optional attributes

The default field is the CSV column the `default` mapping reads.

attribute | default field | example
----------|---------------|--------
prefix|prefix|Mr.
given_name|first_name|Dwight
middle_name|middle_name|Kurt
family_name|last_name|Schrute
suffix|suffix|III
nick_name|nick_name|schrute
title|job_title|Salesman
company|organization|Dunder Mifflin
department|department|Sales
bday|birthday|5/4/82
url|website|dschrute.github.io
company_url|company_website|dundermifflin.com
spouse|spouse| Angela
anniversary|anniversary|2014
email|e_mail_address|<dschrute@gmail.com>
phone|phone|555-123-4557
fax|fax|555-123-4558
cell|mobile|555-123-4559
work_phone|work_phone|555-123-4560
work_email|work_email|<dschrute@dundermifflin.com>
work_fax|work_fax|555-123-4561
note|note|One awesome guy!
po_box|po_box|2340
street|street|123 Uptown St.
street_2|street_2|Apt. 4
city|city|Scranton
state|state|PA
zip|zip|18447
country|country|U.S.
work_po_box|work_po_box|3815
work_street|work_street|456 Company Ln.
work_street_2|work_street_2|Suite. 45
work_city|work_city|Scranton
work_state|work_state|PA
work_zip|work_zip|18447
work_country|work_country|U.S.
other_po_box|other_po_box|1234
other_street|other_street|789 Lake Ave.
other_street_2|other_street_2|Unit 2
other_city|other_city|Scranton
other_state|other_state|PA
other_zip|other_zip|18447
other_country|other_country|U.S.

### Derived values

Besides the mapped attributes, each card gets:

* `FN` (full name): the non-empty name parts joined by spaces, in the order prefix,
  given, middle, family, suffix.
* `BDAY`: `bday` is parsed with `dateutil` and written as `YYYY-MM-DD` (`5/4/82` becomes
  `1982-05-04`).
* `CATEGORIES`: the group (`-g`/`group`) split on commas.
* `ID`: an identity for the contact, the MD5 hex digest of the full name plus the home
  email (or the work email when there's no home email), lowercased with spaces removed.
  The same person with the same email always gets the same `ID`.
* Type labels: addresses (`ADR`) are typed `HOME`, `WORK`, or `OTHER`, and an address is
  added only when at least one of its fields has a value. Emails are typed `INTERNET`
  plus `HOME` or `WORK`; URLs `HOME` or `WORK`; phones `CELL`, `HOME`, or `WORK` plus
  `VOICE` or `FAX`.

## Scripts

csv2vcard comes with a built in task manager `manage.py`.

### Setup

```text
pip install -r dev-requirements.txt
```

### Examples

*Run python linter and nose tests*

```bash
manage lint
manage test
```

## Contributing

Please mimic the coding style/conventions used in this repo. If you add new classes or
functions, please add the appropriate doc blocks with examples. Also, make sure the
python linter and nose tests pass.

Ready to contribute? Here's how:

1. Fork and clone.

```bash
git clone git@github.com:<your_username>/csv2vcard.git
cd csv2vcard
```

2. Setup a new [virtualenv](http://www.virtualenv.org/en/latest/index.html)

```bash
mkvirtualenv --no-site-packages csv2vcard
activate csv2vcard
python setup.py develop
pip install -r dev-requirements.txt
```

3. Create a branch for local development

```bash
git checkout -b name-of-your-bugfix-or-feature
```

4. Make your changes, run linter and tests, and submit a pull request through the GitHub
   website.

## Known issues

* `-o/--overwrite` has no effect for a destination path: `dest` is
  `argparse.FileType('w')`, which truncates the file at parse time
  (csv2vcard/main.py:47-49), before `write(..., overwrite=...)` runs
  (csv2vcard/main.py:81-84).
* `cat file.csv | csv2vcard file.vcf` reads `file.vcf` as the source, because the first
  positional argument is the source (csv2vcard/main.py:44-49). Use `-` for stdin.
* `csv2vcard/main.py` parses the command line when it is imported
  (csv2vcard/main.py:69), so importing it from another program parses that program's
  arguments.
* The `ID` property is not a standard vCard property (the standard one is `UID`), so
  address books may drop or ignore it (csv2vcard/vcard.py:414).
* Python 2 only: `csv2vcard/vobject.py:23` imports `StringIO`, and `md5` is applied to
  text (csv2vcard/vcard.py:413).
* A full name or email with non-ASCII characters can't be hashed into the `ID`: Python 2
  `md5` implicitly encodes the text as ASCII (csv2vcard/vcard.py:413).
* A `bday` value `dateutil` can't parse raises an error and stops the run
  (csv2vcard/vcard.py:123).
* `-v/--verbose` is accepted but changes nothing (csv2vcard/main.py:65-67).

## License

csv2vcard is distributed under the [MIT License](http://opensource.org/licenses/MIT),
the same as [tabutils](https://github.com/reubano/tabutils).
