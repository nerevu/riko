---
source: ../../../../ckanutils/README.md
---

# ckanutils

## Introduction

ckanutils is a [Python library](#usage) for interacting with remote and local
[CKAN](http://ckan.org/) instances. It uses [ckanapi](https://github.com/ckan/ckanapi)
under the hood, and is essentially a high level wrapper for it. A command line interface
built on top of this library is available at
[ckanny](https://github.com/reubano/ckanny).

With ckanutils, you can

- Download a CKAN resource
- Upload CSV/XLS/XLSX files into a CKAN DataStore
- Create DataStore tables and insert or upsert records in chunks
- Create FileStore resources from a url, file path, or file object, or update existing
  ones
- Store and look up a hash per resource in a [hash table](#hash-table)
- Find the newest resources by package/resource name or tag
- and much more (see [Methods](#methods))

## Requirements

ckanutils has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.9

ckanutils requires the following in order to run properly:

- [Python 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled).
  Python 3 is not supported: the module uses `itertools.imap`/`ifilter`, `.next()`, and
  `err.message`.
- A CKAN API key with sysadmin rights. Creating a `CKAN` object calls CKAN's
  `get_site_user` action, which CKAN only allows for sysadmins.

## Installation

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

```text
 sudo pip install ckanutils
```

## Usage

ckanutils is intended to be used directly from Python. Everything lives in the single
module `ckanutils`; import the `CKAN` class with `from ckanutils import CKAN`.

Creating a `CKAN` object contacts the instance right away: it looks up the
[hash table](#hash-table) package (`package_show`) and the site user (`get_site_user`).
With an explicit `remote=None` (even if `CKAN_REMOTE_URL` is set), or with no `remote`
and no `CKAN_REMOTE_URL`, ckanutils uses ckanapi's `LocalCKAN`, which only works when
your code runs inside a CKAN installation.

### Examples

*Fetch a remote resource*

`fetch_resource` returns the streamed `requests.Response` for the resource's file; write
it to disk yourself.

```python
from ckanutils import CKAN

ckan = CKAN(remote="http://demo.ckan.org")
resource_id = "36f33846-cb43-438e-95fd-f518104a32ed"
r = ckan.fetch_resource(resource_id)

with open("path/to/file.csv", "wb") as f:
    for chunk in r.iter_content(chunk_size=2 ** 20):
        f.write(chunk)

print(r.encoding)
```

*Fetch a local resource*

```python
from ckanutils import CKAN

ckan = CKAN(api_key='mykey', remote=None)
resource_id = '36f33846-cb43-438e-95fd-f518104a32ed'
r = ckan.fetch_resource(resource_id)

with open('path/to/file.csv', 'wb') as f:
    for chunk in r.iter_content(chunk_size=2 ** 20):
        f.write(chunk)

print(r.encoding)
```

*show data*

`datastore_search` is ckanapi's action, called with keyword arguments; it returns a dict
whose `records` key holds the matching rows.

```python
from ckanutils import CKAN

ckan = CKAN(api_key='mykey', remote=None)
resource_id = '36f33846-cb43-438e-95fd-f518104a32ed'
r = ckan.datastore_search(resource_id=resource_id)
print(r['records'][0])
```

*Load a file into a DataStore table*

```python
from ckanutils import CKAN

ckan = CKAN(remote="http://demo.ckan.org", api_key="mykey")
ckan.update_datastore("36f33846-cb43-438e-95fd-f518104a32ed", "path/to/file.csv", chunksize_rows=1000)
```

## Methods

`CKAN(**kwargs)` accepts `remote`, `api_key`, `ua`, `hash_table`, `force`, and `quiet`
(see [Configuration](#configuration)).

Method | Description
-------|------------
`fetch_resource(resource_id, user_agent=None, stream=True)` | Return the `requests.Response` for the resource's `perma_link` (or `url`). Raises `NotFound` for an unknown resource and `NotAuthorized` on a 401 or a 403 in the redirect history; other HTTP statuses are returned as-is.
`create_resource(package_id, zip_as_shape=True, **kwargs)` | Create a FileStore resource from exactly one of `url`, `filepath`, or `fileobj` (`TypeError` if none). `name` defaults to the file name (or the Google Sheets `gid`), `format` comes from a `format=` url parameter or the extension, and a `zip` is typed `zipped shapefile` unless `zip_as_shape=False`. Also accepts `description`, `hash`, and `post` (send with `requests` instead of ckanapi).
`update_filestore(resource_id, **kwargs)` | Update an existing resource with the same keyword arguments as `create_resource`. Prints a message and returns `None` if the resource isn't found.
`update_datastore(resource_id, filepath, **kwargs)` | Load a csv/xls/xlsx file (path or file object) into the resource's DataStore table; see [Write semantics](#write-semantics). Returns the `insert_records` result, or `False` when no reader exists for the file type.
`create_table(resource_id, fields, **kwargs)` | `datastore_create` for an existing FileStore resource (`aliases`, `primary_key`, `indexes`, `force`). Raises `NotFound` if the resource doesn't exist.
`delete_table(resource_id, **kwargs)` | `datastore_delete`, optionally limited by `filters`. Prints a message and returns `None` when the table is missing or read-only.
`insert_records(resource_id, records, **kwargs)` | Write records with `datastore_upsert` in chunks of `chunksize` rows (`0` means all at once), from `start` to `stop`, using `method` `insert` (default), `upsert`, or `update`.
`get_hash(resource_id)` | Look up a resource's stored hash; see [Hash Table](#hash-table).
`create_hash_table(verbose=False)` | Create the hash table's DataStore table on the existing hash table resource.
`update_hash_table(resource_id, resource_hash, verbose=False)` | Upsert a resource's hash.
`get_package_id(resource_id)` | Return the id of the package that contains a resource (via `revision_show`).
`get_update_date(item)` | Return a package's, resource's, or revision's last-update `datetime` (`metadata_modified`, `last_modified`, or `revision_timestamp`).
`filter(items, tagged=None, named=None, updated=None)` | Yield the active items that match any given filter: `named` (case-insensitive substring of the name), `tagged` (exact tag), or `updated` (a predicate on the update date). With no filters, yield every active item.
`query(packages, **kwargs)` | Yield `{'rid': ..., 'pname': ...}` for the resources of the matching packages, newest first, for both packages and resources. Filters: `pnamed`, `ptagged`, `rnamed`, `rtagged`.
`find_ids(packages, **kwargs)` | Return the first `query` result (`{'rid': '', 'pname': ''}` if none). Raises `AttributeError` with the pinned tabutils today (see [Known issues](#known-issues)).
`get_filestore_update_func(resource, **kwargs)` | Build the `(func, args, data)` call used by `create_resource`/`update_filestore`.

The `CKAN` object also exposes these ckanapi actions directly, called with keyword
arguments: `datastore_search`, `datastore_create`, `datastore_delete`,
`datastore_upsert`, `resource_show`, `resource_create`, `package_show`,
`package_create`, `package_update`, `package_privatize` (`bulk_update_private`),
`revision_show`, `organization_list` (`organization_list_for_user`),
`organization_show`, `license_list`, and `group_list`. The `user` attribute holds the
site user returned at construction.

### Write semantics

`update_datastore` reads the whole file with the tabutils reader for its extension (the
extension comes from `filepath`, or from the `content_type` keyword when `filepath` has
none, e.g. a temporary file). Other keyword arguments are passed on to the reader.

- **No `primary_key`** (the default): the existing DataStore table is deleted and
  recreated, then every row is inserted. Each call is a full replace.
- **With `primary_key`**: the table is kept and the rows are upserted on that key
  (intended). Today the key never reaches `create_table`, so the upsert fails unless the
  table already has a unique key (see [Known issues](#known-issues)).
- Every column is `text` unless `type_cast=True`, which detects the column types and
  maps them to database types for `dialect` (default `postgres`). `type_cast=True`
  raises `AttributeError` with the pinned tabutils today (see
  [Known issues](#known-issues)).
- Rows are written `chunksize_rows` at a time (all at once if unset).

## Configuration

ckanutils will use the following
[Environment Variables](http://www.cyberciti.biz/faq/set-environment-variable-linux/) if
set:

Environment Variable|Description|`CKAN` keyword
--------------------|-----------|--------------
CKAN_API_KEY|Your CKAN API Key|`api_key`
CKAN_REMOTE_URL|Your CKAN instance remote url (unset means local mode)|`remote`
CKAN_USER_AGENT|Your user agent (default `ckanutils/<version>`)|`ua`

Other `CKAN` keywords:

Keyword|Default|Description
-------|-------|-----------
`hash_table`|`hash-table`|The hash table package id
`force`|`True`|Create, delete, and write DataStore tables even if they are read-only
`quiet`|`False`|Suppress debug statements

Module constants: `CHUNKSIZE_ROWS` (1000), `CHUNKSIZE_BYTES` (1048576), `DEF_HASH_PACK`
(`hash-table`), `DEF_HASH_RES` (`hash-table.csv`), and `CKAN_KEYS` (the keyword names
`CKAN` accepts).

## Hash Table

In order to support file hashing, ckanutils stores and looks up one hash per resource in
a hash table resource. By convention it is called `hash-table.csv`, and it has the
following schema:

field|type|description
------|----|-----------
datastore_id|text|The resource id (primary key)
hash|text|The hash the caller computed for the resource

By default the hash table resource is the first resource of the package `hash-table`.
ckanutils doesn't create this package or resource, and it doesn't hash files: the caller
creates them and computes the hash. [ckanny](https://github.com/reubano/ckanny)'s
`ds.update` creates the package and the `hash-table.csv` resource when they are missing
and stores SHA-1 hashes of the FileStore files. Optionally, you can set the hash table
package in the command line with ckanny's `-H, --hash-table` option, or in a Python file
as the `hash_table` keyword argument to `CKAN`.

- `get_hash(resource_id)` returns the stored hash, or prints a message and returns
  `None` when the resource has no row. It raises `NotFound` with `item` set to
  `package`, `resource`, or `datastore` when the hash table package, its resource, or
  its DataStore table is missing.
- `create_hash_table()` creates the DataStore table (`datastore_id` as primary key) on
  the existing hash table resource.
- `update_hash_table(resource_id, resource_hash)` upserts the row keyed by
  `datastore_id`.

Example:

```python
from ckanutils import CKAN

ckan = CKAN(hash_table="custom_hash_table")
hash = ckan.get_hash("36f33846-cb43-438e-95fd-f518104a32ed")
```

## Scripts

ckanutils comes with a built in task manager `manage.py` and a `Makefile`.

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

`tests/` holds no test modules, so `manage test` runs only the doctests in
`ckanutils.py` (`setup.cfg` turns on `with-doctest`). They build `CKAN()` without a
`remote`, so they need a local CKAN installation unless `CKAN_REMOTE_URL` is set, in
which case they run against that instance.

Or if `make` is more your speed...

```bash
make lint
make test
```

`make lint` runs `flake8 ckanutils tests`, but the module is `ckanutils.py` (there is no
`ckanutils/` directory), so flake8 reports the missing path; use `manage lint` or
`flake8 ckanutils.py tests`.

## Contributing

View
[CONTRIBUTING.rst](https://github.com/reubano/ckanutils/blob/master/CONTRIBUTING.rst)

## Known issues

- `update_datastore` with `primary_key` fails on a new table: it filters the
  `create_table` keywords by the file's column names, so `primary_key`, `aliases`, and
  `indexes` are dropped, while the rows are still sent with `method='upsert'`
  (`ckanutils.py:684`, `:702`, `:707`). CKAN then rejects the upsert with
  `table does not have a unique key defined`.
- `update_datastore(type_cast=True)` raises `AttributeError` with the pinned
  `tabutils==0.23.1`, which has no `fntools.get_dtype` (added in tabutils 0.25.0)
  (`ckanutils.py:691`).
- `find_ids` raises `AttributeError` with the pinned `tabutils==0.23.1`, which moved
  `find` from `process` to `fntools` (`ckanutils.py:715`).
- `insert_records` returns one more than the number of rows written, because its counter
  starts at 1 (`ckanutils.py:269`, `:301`).
- `get_package_id` prints the resource's revision id to stdout even with `quiet=True`
  (`ckanutils.py:743`).

## License

ckanutils is distributed under the [MIT License](http://opensource.org/licenses/MIT),
the same as [ckanapi](https://github.com/ckan/ckanapi).
