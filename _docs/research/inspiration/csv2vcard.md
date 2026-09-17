# csv2vcard

## INTRODUCTION

[csv2vcard](http://github.com/reubano/csv2vcard) is a [Python library](#library-example) and [command line interface program](#cli-examples) that converts CSV files to vCard (vcf) for importing into Contacts or similar address book programs. csv2vcard has been tested on the following configuration:

* MacOS X 10.9.5
* Python 2.7.10

## Requirements

csv2vcard requires the following programs in order to run properly:

* [Python >= 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled)

## INSTALLATION

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

    sudo pip install csv2vcard

## Usage

csv2vcard is intended to be used either directly from Python or from the command line.

### Library Example

*normal usage*

```python
from __future__ import absolute_import, print_function
from tabutils.io import read_csv

from csv2vcard.vcard import vCard, gen_cards
from csv2vcard.mappings.default import mapping

vcard = vCard(mapping)
records = read_csv("path/to/file.csv")

for card in gen_cards(records, vcard):
    print(card.serialize())
```

### CLI Examples

*show help*

    csv2vcard -h

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

*normal usage*

    csv2vcard file.csv file.vcf

*print output to stdout*

    csv2vcard file.csv

*read input from stdin*

    cat file.csv | csv2vcard file.vcf

*specify a custom mapping*

    csv2vcard -m custom file.csv file.vcf

## CUSTOMIZATION

### Code modification

If you would like to import csv files with field names different from the default, you can modify the mapping file or create your own. New mappings must be placed in the `csv2vcard/mappings` folder. The mapping object consists of a dictionary whose keys are vCard attributes and whose values can be either a value or a function which returns the corresponding value from a record (csv row). The mapping function will take in a record, e.g.,

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

### Required attributes

one of the following mapping keys (attributes) must be present

attribute | default field | example
----------|---------------|--------
has_header': True,
is_split': False,
bank': 'Bank Name',
currency': 'USD',
delimiter': ',',
account': itemgetter('Field'),
account_id': itemgetter('Field'),
date': itemgetter('Field'),
type': itemgetter('Field'),
amount': itemgetter('Field'),
balance': itemgetter('Field'),
desc': itemgetter('Field'),
payee': itemgetter('Field'),
notes': itemgetter('Field'),
class': itemgetter('Field'),
id': itemgetter('Field'),
check_num': itemgetter('Field'),

### Optional attributes

attribute | default field | example
----------|---------------|--------
nick_name|nick_name|reubano
title|job_title|Manager
company|organization|Nerevu Development
department|department|IT
bday|birthday|5/4/82
url|website|reubano.github.io
company_url|company_website|nerevu.com
spouse|spouse|Brenda
anniversary|anniversary|5/5/2012
email|e_mail_address|reubano@gmail.com
phone|phone|555-123-4557
fax|fax|555-123-4558
cell|mobile|555-123-4559
work_phone|work_phone|555-123-4560
work_email|work_email|rcummings@nervu.com
work_fax|work_fax|555-123-4561
note|note|One awesome guy!
po_box|po_box|2340
street|street|123 Uptown St.
street_2|street_2|Apt. 4
city|city|Peoria
state|state|IL
zip|zip|61605
country|country|U.S.
work_po_box|work_po_box|3815
work_street|work_street|456 Company Ln.
work_street_2|work_street_2|Suite. 45
work_city|work_city|Chicago
work_state|work_state|IL
work_zip|work_zip|60643
work_country|work_country|U.S.

## Scripts

csv2vcard comes with a built in task manager `manage.py`.

### Setup

    pip install -r dev-requirements.txt

### Examples

*Run python linter and nose tests*

```bash
manage lint
manage test
```

## Contributing

Please mimic the coding style/conventions used in this repo. If you add new classes or functions, please add the appropriate doc blocks with examples. Also, make sure the python linter and nose tests pass.

Ready to contribute? Here's how:

1. Fork and clone.


```bash
git clone git@github.com:<your_username>/csv2ofx.git
cd csv2ofx
```

2. Setup a new [virtualenv](http://www.virtualenv.org/en/latest/index.html)

```bash
mkvirtualenv --no-site-packages csv2ofx
activate csv2ofx
python setup.py develop
pip install -r dev-requirements.txt
```

3. Create a branch for local development

```bash
git checkout -b name-of-your-bugfix-or-feature
```

4. Make your changes, run linter and tests, and submit a pull request through the GitHub website.

## License

csv2vcard is distributed under the [MIT License](http://opensource.org/licenses/MIT), the same as [tabutils](https://github.com/reubano/tabutils).
