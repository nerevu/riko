---
source: ../../../../ckanny/README.md
---

# ckanny

## Introduction

ckanny is a [command line interface](#cli) for interacting with remote and local
[CKAN](http://ckan.org/) instances. Under the hood, it uses
[ckanutils](https://github.com/reubano/ckanutils).

With ckanny, you can

- Download a CKAN resource
- Create or update a CKAN package
- Update a CKAN DataStore from data in the FileStore
- Upload a local file into a CKAN DataStore or FileStore
- Copy a FileStore resource from one CKAN instance to another
- and much more (see [Commands](#commands))

ckanny performs smart updates. `ckanny ds.update` downloads the resource's FileStore
file, computes its SHA-1 hash, and only updates the DataStore if that hash differs from
the one recorded for the resource on the last successful update (see
[Hash Table](#hash-table)). This allows you to schedule a script to run on a frequent
basis, e.g., `@hourly` via a cron job, without updating the CKAN instance unnecessarily.

## Requirements

ckanny has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.9

ckanny requires the following in order to run properly:

- [Python 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled).
  Python 3 is not supported: the code uses `StringIO`, `.next()`, and `itertools.imap`,
  and `setup.py` declares Python 2.7 only.
- A filesystem with extended attributes (MacOS X or Linux), since
  [xattr](https://pypi.python.org/pypi/xattr) is a hard dependency (see
  [Encoding handoff](#encoding-handoff)).
- A CKAN API key with sysadmin rights on the target instance. Every command except `ver`
  builds a ckanutils `CKAN` object, and building it calls CKAN's `get_site_user` action,
  which CKAN only allows for sysadmins.

## Installation

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

```text
 sudo pip install ckanny
```

## CLI

ckanny comes with a built in command line interface `ckanny`.

### Usage

```text
 ckanny [<namespace>.]<command> [<args>]
```

### Commands

Command | Positional argument | Description
--------|---------------------|------------
`ver` | | Show ckanny version
`ds.delete` | `resource_id` | Delete a DataStore table (`-f` filters to apply before deleting, e.g., `{"name": "fred"}`)
`ds.update` | `resource_id` | Update a DataStore table from the resource's current FileStore file, skipping unchanged files (see [ds.update options](#dsupdate-options))
`ds.upload` | `source` (file path) | Upload a local csv/xls/xlsx file into a DataStore table (see [ds.upload options](#dsupload-options))
`fs.fetch` | `resource_id` | Download a FileStore resource
`fs.migrate` | `resource_id` | Copy a FileStore resource from one CKAN instance to another
`fs.update` | `rid` | Update an existing resource's name (`-n`); also sends every CLI option as a resource field today (see [Known issues](#known-issues))
`fs.upload` | `source` (file path or url) | Update the FileStore of an existing resource (`-R`), or create a new one in a package (`-p`)
`hdx.customize` | `org_id` | Introspect custom HDX organization values (crashes without `-w` with the pinned tabutils, see [Known issues](#known-issues))
`pk.create` | `org_id` | Create a package (aka dataset)
`pk.update` | `pid` | Update a package (aka dataset)

Every command except `ver` accepts `-k API_KEY` and `-u UA`, every one but `fs.migrate`
(which takes `-s`/`-d`) accepts `-r REMOTE`, and every one but `ds.delete` accepts `-q`
(suppress debug statements); see [Configuration](#configuration).

### Examples

*show help*

```text
ckanny -h
```

```bash
usage: ckanny [<namespace>.]<command> [<args>]

positional arguments:
  command     the command to run

optional arguments:
  -h, --help  show this help message and exit

available commands:
  ver                      Show ckanny version

  [ds]
    delete                 Deletes a datastore table
    update                 Updates a datastore table based on the current filestore resource
    upload                 Uploads a file to a datastore table

  [fs]
    fetch                  Downloads a filestore resource
    migrate                Copies a filestore resource from one ckan instance to another
    update                 Updates an existing resource
    upload                 Updates the filestore of an existing resource or creates a new one

  [hdx]
    customize              Introspects custom organization values

  [pk]
    create                 Creates a package (aka dataset)
    update                 Updates a package (aka dataset)
```

*show version*

```text
ckanny ver
```

*fetch a resource*

```text
ckanny fs.fetch -k <CKAN_API_KEY> -r <CKAN_URL> <resource_id>
```

When `-d` is a directory, `fs.fetch` names the file from the response's
`Content-Disposition` header (falling back to the resource id), or after the resource id
with `-n`, and prints the written file path. With the pinned `tabutils==0.23.1` the
naming step raises `AttributeError` today (see [Known issues](#known-issues)). It also
saves the response encoding for `ds.upload` (see [Encoding handoff](#encoding-handoff)).

*show fs.fetch help*

```text
ckanny fs.fetch -h
```

```bash
usage: ckanny fs.fetch
       [-h] [-q] [-n] [-c CHUNKSIZE_BYTES] [-u UA] [-k API_KEY] [-r REMOTE]
       [-d DESTINATION]
       [resource_id]

Downloads a filestore resource

positional arguments:
  resource_id           the resource id

optional arguments:
  -h, --help            show this help message and exit
  -q, --quiet           suppress debug statements
  -n, --name-from-id    Use resource id for filename
  -c CHUNKSIZE_BYTES, --chunksize-bytes CHUNKSIZE_BYTES
                        number of bytes to read/write at a time (default:
                        1048576)
  -u UA, --ua UA        the user agent (uses `CKAN_USER_AGENT` ENV if
                        available) (default: None)
  -k API_KEY, --api-key API_KEY
                        the api key (uses `CKAN_API_KEY` ENV if available)
                        (default: None)
  -r REMOTE, --remote REMOTE
                        the remote ckan url (uses `CKAN_REMOTE_URL` ENV if
                        available) (default: None)
  -d DESTINATION, --destination DESTINATION
                        the destination folder or file path (default:
                        .)
```

The `-d` default is the current working directory.

*update a datastore table only if its file changed*

```text
ckanny ds.update -k <CKAN_API_KEY> -r <CKAN_URL> <resource_id>
```

*force a datastore update even if the file is unchanged*

```text
ckanny ds.update -f <resource_id>
```

*upload a file fetched with `fs.fetch` into a datastore table*

```text
ckanny ds.upload -R <resource_id> path/to/file.csv
```

*copy a resource between instances*

```text
ckanny fs.migrate -s <SOURCE_CKAN_URL> -d <DEST_CKAN_URL> <resource_id>
```

`fs.migrate` downloads the resource from `-s` and uploads it to the resource with the
**same id** on `-d`, so that resource must already exist on the destination; it doesn't
create one. Both `-s` and `-d` default to `CKAN_REMOTE_URL`, and the command exits with
an error when they are equal, so pass at least one of them. A single `-k` API key is
used for both instances.

*create a package*

```text
ckanny pk.create -k <CKAN_API_KEY> -r <CKAN_URL> <org_id>
```

*create a package with resources*

```text
ckanny pk.create -k <CKAN_API_KEY> -r <CKAN_URL> -f 'file1.csv,file2.csv' -n 'File 1,File 2' <org_id>
```

`-n/--names` is required alongside `-f`: files are paired with names one to one, so a
file without a matching name is silently skipped, and `-f` alone attaches no resources.
Entries containing `http` are attached as links when the package is created. Local files
are uploaded to the FileStore after the package is created, one new resource each. The
resource format comes from a `format=` url parameter, else the file extension, else
`csv`.

*show pk.create help*

```text
ckanny pk.create -h
```

```bash
usage: ckanny pk.create
       [-h] [-q] [-p] [-u UA] [-k API_KEY]
       [-r REMOTE] [-e END] [-S START]
       [-M MAINTAINER] [-L LOCATION]
       [-c CAVEATS] [-y TYPE] [-T TAGS]
       [-t TITLE] [-m METHODOLOGY]
       [-d DESCRIPTION] [-n NAMES] [-f FILES]
       [-s SOURCE] [-l LICENSE_ID]
       [org_id]

Creates a package (aka dataset)

positional arguments:
  org_id                the organization id

optional arguments:
  -h, --help            show this help message and exit
  -q, --quiet           Suppress debug statements
  -p, --private         Make package private
  -u UA, --ua UA
                        The user agent (uses `CKAN_USER_AGENT` ENV if
                        available) (default: ckanutils/0.14.9)
  -k API_KEY, --api-key API_KEY
                        The api key (uses `CKAN_API_KEY` ENV if available)
                        (default: None)
  -r REMOTE, --remote REMOTE
                        The remote ckan url (uses `CKAN_REMOTE_URL` ENV if
                        available) (default: None)
  -e END, --end END
                        Data end date
  -S START, --start START
                        Data start date (default: 09/25/2015)
  -M MAINTAINER, --maintainer MAINTAINER
                        The package maintainer
  -L LOCATION, --location LOCATION
                        Location the data represents (default: world)
  -c CAVEATS, --caveats CAVEATS
                        Package caveats
  -y TYPE, --type TYPE
                        Package type (default: dataset)
  -T TAGS, --tags TAGS
                        Comma separated list of tags
  -t TITLE, --title TITLE
                        Package title (default: Untitled 2015-09-25
                        12:36:14.141533)
  -m METHODOLOGY, --methodology METHODOLOGY
                        Data collection methodology (default: observed)
  -d DESCRIPTION, --description DESCRIPTION
                        Dataset description (default: same as `title`)
  -n NAMES, --names NAMES
                        Comma separated list of file names (requires `files`)
  -f FILES, --files FILES
                        Comma separated list of file paths to add
  -s SOURCE, --source SOURCE
                        Data source (default: Multiple sources)
  -l LICENSE_ID, --license-id LICENSE_ID
                        Data license (default: cc-by-igo)
```

`pk.create` rules:

- The `-S` and `-t` defaults are the current UTC date and time when the command runs
  (shown above as of 09/25/2015). `-S`/`-e` are parsed as dates and stored as
  `dataset_date` (`MM/DD/YYYY` or `MM/DD/YYYY-MM/DD/YYYY`).
- The package name is the slugified title.
- `org_id` (an organization id or name) must be an organization the API user administers
  (a sysadmin administers every organization), and `-L` must name an existing CKAN group
  (`world` by default). Otherwise the command exits with an error.
- `-m` accepts any text. `observed`, `census`, `registry`, and `survey` map to HDX's
  methodology labels; any other value is stored as methodology `Other` with the text in
  `methodology_other`.
- A `-l` license id that isn't in the instance's license list is replaced with
  `hdx-other`. The original value is kept in `license_other` only when `hdx-other` is
  itself missing from the license list; on HDX, where `hdx-other` exists, it is dropped.
- `-p` makes the package private after creating it. The new package id is printed.

*update a package*

```text
ckanny pk.update -t 'New title' -T 'tag1,tag2' <package_id>
```

`pk.update` takes the same metadata options as `pk.create`
(`-l -s -d -m -t -T -y -c -L -S -e -p`, without defaults) and merges them over the
current package: each field keeps its current value unless a non-empty new value is
given. Today an omitted `-l` still resets the license to `hdx-other` and an omitted `-m`
resets the methodology to `Other` (see [Known issues](#known-issues)).

### ds.update options

`ckanny ds.update [options] resource_id`

Flag | Default | Description
-----|---------|------------
`-H, --hash-table` | `hash-table` | The hash table package id
`-g, --hash-group` | `HDX` | Display name of the organization that owns the hash table package (used only when creating it)
`-f, --force` | off | Update the DataStore even if the file hasn't changed
`-p, --primary-key` | | Unique field(s), e.g., `'field1,field2'`; switches from replace to upsert (see [Write semantics](#write-semantics))
`-t, --type-cast` | off | Detect column types instead of storing every column as `text` (raises `AttributeError` with the pinned tabutils today, see [Known issues](#known-issues))
`-s, --sanitize` | off | Underscorify and lowercase field names
`-c, --chunksize-rows` | `1000` | Number of rows to write at a time
`-C, --chunksize-bytes` | `1048576` | Number of bytes to read/write at a time (has no effect today, see [Known issues](#known-issues))
`-F, --first-row` | `0` | The first row (zero indexed)
`-o, --first-col` | `0` | The first column (zero indexed)
`-d, --date-format` | `%m/%d/%y` | Date format passed to `strftime()`
`-u, --ua` | `CKAN_USER_AGENT`, else `ckanutils/<version>` | The user agent
`-r`, `-k`, `-q` | | Remote, API key, quiet (see [Configuration](#configuration))

Exit status: `0` when the update succeeds or when the file is unchanged
(`No new data found. Not updating datastore.`); non-zero with an `ERROR:` message when
the resource can't be fetched or the DataStore update fails.

### ds.upload options

`ckanny ds.upload [options] source`

Flag | Default | Description
-----|---------|------------
`-R, --resource-id` | the source file name up to its first `.` | The DataStore resource id
`-e, --encoding` | `utf-8` | The file encoding; overridden by the encoding `fs.fetch` saved on the file
`-p`, `-t`, `-s`, `-c`, `-F`, `-o` | | As for `ds.update`

`ds.upload` doesn't consult or update the hash table.

### Write semantics

`ds.update` and `ds.upload` write a whole file into the DataStore table of an existing
FileStore resource. The reader is chosen from the file extension (`ds.update` downloads
into a temporary file, so it uses the response's content type instead).

- **Without `-p`** (the default) the existing DataStore table is deleted and recreated,
  then every row is inserted: a full replace.
- **With `-p`** the table is kept and rows are upserted on the given key (intended).
  Today the key is not passed when the table is created, so the upsert fails unless the
  table already has a unique key (see [Known issues](#known-issues)).
- Every column is created as `text` unless `-t` is given (`-t` currently crashes with
  the pinned tabutils, see [Known issues](#known-issues)).

## Configuration

ckanny will use the following
[Environment Variables](http://www.cyberciti.biz/faq/set-environment-variable-linux/) if
set:

Environment Variable|Description|Overridden by
--------------------|-----------|-------------
CKAN_API_KEY|Your CKAN API Key|`-k, --api-key`
CKAN_REMOTE_URL|Your CKAN instance remote url|`-r, --remote` (`-s`/`-d` for `fs.migrate`)
CKAN_USER_AGENT|Your user agent|`-u, --ua`

When no remote url is set (neither `-r` nor `CKAN_REMOTE_URL`), ckanny talks to a
*local* CKAN through ckanapi's `LocalCKAN`, which only works when ckanny runs inside a
CKAN installation. Set a remote url everywhere else.

## Hash Table

In order to support file hashing, `ckanny ds.update` keeps a hash table resource called
`hash-table.csv` with the following schema:

field|type|description
------|----|-----------
datastore_id|text|The resource id (primary key)
hash|text|SHA-1 hex digest of the resource's FileStore file at its last successful update

By default the hash table resource will be placed in the package `hash-table`; ckanny
reads the table from the package's first resource. Optionally, you can set the hash
table package in the command line with the `-H, --hash-table` option, or in a Python
file as the `hash_table` keyword argument to `CKAN`.

Example:

```text
ckanny ds.update -H custom_hash_table 36f33846-cb43-438e-95fd-f518104a32ed
```

ckanny creates whatever part of the hash table is missing on the first `ds.update`:

- If the package doesn't exist, ckanny creates it in the organization whose display name
  equals `-g, --hash-group` (default `HDX`). The organization must be one the API user
  administers (a sysadmin administers every organization); if no such organization is
  found, the command fails.
- If the package has no resource, ckanny creates `hash-table.csv` in it.
- It then creates the DataStore table with `datastore_id` as its primary key.

Each `ds.update` run then:

1. downloads the resource's FileStore file;
2. looks up the row keyed by the resource id. With no row (the first run) the file
   always counts as changed;
3. computes the SHA-1 hash of the downloaded bytes and compares it with the stored hash;
4. if unchanged and `-f` isn't given, prints
   `No new data found. Not updating datastore.` and exits `0`;
5. otherwise updates the DataStore (see [Write semantics](#write-semantics));
6. upserts the new hash only if the update succeeded and the file changed. A failed
   update leaves the old hash in place, so the next run retries. A forced update of an
   unchanged file leaves the hash as it was.

## Encoding handoff

`fs.fetch` saves the HTTP response encoding (when the server reports one) as the
extended attribute `com.ckanny.encoding` on the downloaded file. `ds.upload` reads that
attribute back and uses it instead of `-e, --encoding`; if the file has no such
attribute, `-e` (default `utf-8`) applies. Copying the file to a filesystem without
extended attributes drops the saved encoding.

## Scripts

ckanny comes with a built in task manager `manage.py` and a `Makefile`.

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

`manage test` runs nose (with doctests, per `setup.cfg`) and then the script tests in
`tests/test.py`.

Or if `make` is more your speed...

```bash
make lint
make test
```

`make test` runs `python tests/test_script.py`, which doesn't exist, so it fails; use
`manage test`.

## Contributing

View [CONTRIBUTING.rst](https://github.com/reubano/ckanny/blob/master/CONTRIBUTING.rst)

## Known issues

- `ds.update -C/--chunksize-bytes` has no effect: the command reads
  `kwargs['chunk_bytes']` instead of `chunksize_bytes`, so downloading and hashing
  always use 1048576 bytes (`ckanny/datastorer.py:84`).
- `-p/--primary-key` upserts fail on a new table: ckanutils `update_datastore` filters
  the `datastore_create` options by the file's column names, so `primary_key` never
  reaches the table definition, while the rows are still sent with `method='upsert'`
  (`ckanutils.py:684`, `:702`, `:707`). CKAN then rejects the upsert with
  `table does not have a unique key defined`.
- `ds.update` with a missing hash table package and no organization whose display name
  matches `-g` crashes with `StopIteration` instead of an error message
  (`ckanny/datastorer.py:108-111`).
- `fs.fetch` crashes with `AttributeError` with the pinned `tabutils==0.23.1`, which no
  longer has `process.make_filepath` (`ckanny/filestorer.py:67`).
- `-t/--type-cast` crashes with `AttributeError` with the pinned `tabutils==0.23.1`:
  ckanutils calls `fntools.get_dtype`, which tabutils only added in 0.25.0
  (`ckanutils.py:691`).
- `hdx.customize` without `-w` crashes with `AttributeError`: ckanutils `find_ids` calls
  `process.find`, which tabutils 0.23.1 moved to `fntools` (`ckanutils.py:715`);
  `hdx.py:35` has the same problem when it looks up 3W fields.
- `fs.migrate` raises `UnboundLocalError` instead of printing the fetch error when the
  source download fails, because its cleanup unlinks a temporary file that was never
  created (`ckanny/filestorer.py:120-139`).
- `pk.update` without `-l` resets the package license to `hdx-other`: `licenses` is a
  one-shot iterator, `None` is never in it, and the non-empty `hdx-other` wins the merge
  over the current license (`ckanny/package.py:249-251`, `:293-298`).
- `pk.update` without `-m` resets the package methodology to `Other`:
  `methods.get(None, 'Other')` is non-empty and wins the same merge
  (`ckanny/package.py:278`, `:293-298`).
- `fs.update` passes every CLI option, including `api_key`, `remote`, and `ua`, through
  to `update_filestore`, which merges them into the resource fields it sends to CKAN
  (`ckanny/filestorer.py:224`, `ckanutils.py:455`).

## License

ckanny is distributed under the [MIT License](http://opensource.org/licenses/MIT), the
same as [ckanutils](https://github.com/reubano/ckanutils).
