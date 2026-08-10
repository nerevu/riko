# ckanny

## Introduction

ckanny is a [command line interface](#cli) for interacting with remote and local [CKAN](http://ckan.org/) instances. Under the hood, it uses [ckanutils](https://github.com/reubano/ckanutils).

With ckanny, you can

- Download a CKAN resource
- Create a CKAN package
- Update a CKAN DataStore from data in the FileStore
- Copy a FileStore resource from one CKAN instance to another
- and much more...

ckanny performs smart updates by computing the hash of a file and will only update the datastore if the file has changed. This allows you to schedule a script to run on a frequent basis, e.g., `@hourly` via a cron job, without updating the CKAN instance unnecessarily.

## Requirements

ckanny has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.9

ckanny requires the following in order to run properly:

- [Python >= 2.7](http://www.python.org/download) (MacOS X comes with python preinstalled)

## Installation

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

     sudo pip install ckanny

## CLI

ckanny comes with a built in command line interface `ckanny`.

### Usage

     ckanny [<namespace>.]<command> [<args>]

### Examples

*show help*

    ckanny -h

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
    upload                 Updates the filestore of an existing resource or creates a new one

  [hdx]
    customize              Introspects custom organization values

  [pk]
    create                 Creates a package (aka dataset)
```

*show version*

    ckanny ver

*fetch a resource*

    ckanny fs.fetch -k <CKAN_API_KEY> -r <CKAN_URL> <resource_id>

*show fs.fetch help*

    ckanny fs.fetch -h

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

*create a package*

    ckanny pk.create -k <CKAN_API_KEY> -r <CKAN_URL> <org_id>

*create a package with resources*

    ckanny pk.create -k <CKAN_API_KEY> -r <CKAN_URL> -f 'file1.csv,file2.csv' <org_id>

*show pk.create help*

    ckanny pk.create -h

```bash
usage: /Users/reubano/.virtualenvs/ckan/bin/ckanny pk.create
       [-h] [-q] [-u UA] [-k API_KEY]
       [-r REMOTE] [-e END] [-S START]
       [-L LOCATION] [-c CAVEATS] [-y TYPE]
       [-T TAGS] [-t TITLE]
       [-m {observed,other,census,survey,registry}]
       [-d DESCRIPTION] [-f FILES] [-s SOURCE]
       [-l LICENSE_ID]
       [org_id]

Creates a package (aka dataset)

positional arguments:
  org_id                the organization id

optional arguments:
  -h, --help            show this help message and exit
  -q, --quiet           suppress debug statements
  -u UA, --ua UA
                        the user agent (uses `CKAN_USER_AGENT` ENV if
                        available) (default: None)
  -k API_KEY, --api-key API_KEY
                        the api key (uses `CKAN_API_KEY` ENV if available)
                        (default: None)
  -r REMOTE, --remote REMOTE
                        the remote ckan url (uses `CKAN_REMOTE_URL` ENV if
                        available) (default: None)
  -e END, --end END
                        Data end date
  -S START, --start START
                        Data start date (default: 09/25/2015)
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
  -m {observed,other,census,survey,registry}, --methodology {observed,other,census,survey,registry}
                        Data collection methodology (default: observed)
  -d DESCRIPTION, --description DESCRIPTION
                        Dataset description (default: same as `title`)
  -f FILES, --files FILES
                        Comma separated list of file paths to add
  -s SOURCE, --source SOURCE
                        Data source (default: Multiple sources)
  -l LICENSE_ID, --license-id LICENSE_ID
                        Data license (default: cc-by-igo)
```
## Configuration

ckanny will use the following [Environment Variables](http://www.cyberciti.biz/faq/set-environment-variable-linux/) if set:

Environment Variable|Description
--------------------|-----------
CKAN_API_KEY|Your CKAN API Key
CKAN_REMOTE_URL|Your CKAN instance remote url
CKAN_USER_AGENT|Your user agent

## Hash Table

In order to support file hashing, ckanny creates a hash table resource called `hash_table.csv` with the following schema:

field|type
------|----
datastore_id|text
hash|text

By default the hash table resource will be placed in the package `hash_table`. ckanny will create this package if it doesn't exist. Optionally, you can set the hash table package in the command line with the `-H, --hash-table` option, or in a Python file as the `hash_table` keyword argument to `CKAN`.

Example:

    ckanny ds.update -H custom_hash_table 36f33846-cb43-438e-95fd-f518104a32ed

## Scripts

ckanny comes with a built in task manager `manage.py` and a `Makefile`.

### Setup

    pip install -r dev-requirements.txt

### Examples

*Run python linter and nose tests*

```bash
manage lint
manage test
```

Or if `make` is more your speed...

```bash
make lint
make test
```

## Contributing

View [CONTRIBUTING.rst](https://github.com/reubano/ckanny/blob/master/CONTRIBUTING.rst)

## License

ckanny is distributed under the [MIT License](http://opensource.org/licenses/MIT), the same as [ckanutils](https://github.com/reubano/ckanutils).
