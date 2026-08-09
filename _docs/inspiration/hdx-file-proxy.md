# HDX File Proxy API

## Introduction

The hdx-file-proxy is a [`Flask`](http://flask.pocoo.org) powered service to proxy csv and excel files on HDX.

## Requirements

hdx-file-proxy has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.10
- postgres (PostgreSQL) 9.4.1

hdx-file-proxy requires the following in order to run properly in development mode:

- [Python >= 2.7](http://www.python.org/download)

Additionally, hdx-file-proxy requires the following in order to run properly in production mode:

- [postgres >= 9.4](http://www.postgres.org)

## Setup

### local

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

    sudo pip install -r requirements.txt
    manage setup
    manage populate
    manage serve

### Production

    pip install -r prod-requirements.txt
    sudo -u postgres pg_ctl start
    memcached -vv
    manage -m Production setup
    manage -m Production populate
    gunicorn app:create_app('Production') -w 3 -k gevent
    screen -dS worker -m python worker.py

## Usage

hdx-file-proxy is intended to be used via HTTP requests.

### Examples

#### cURL

*Check the data returned from HDX API*

```bash
# request
curl http://localhost:3000/v1/data/

# response
{
  "num_results": 0,
  "objects": [{
    "adm0_name": "Afghanistan",
    "adm1_name": "Badakhshan",
    "cm_name": "Bread",
    "id": 1,
    "mkt_name": "Fayzabad",
    "mp_month": "3",
    "mp_price": 50.0000000000,
    "mp_year": 2015,
    "utc_created": "2015-10-28T04:02:14.556843",
    "utc_updated": "2015-10-28T04:02:14.557005"
  }],
  "page": 1,
  "total_pages": 0
}
```

#### Python

initialize

```python
# init requirements
import requests

endpoint = 'http://localhost:3000/v1'
```

*Check the data returned from HDX API*

```python
# request
r = requests.get('%s/data/' % endpoint)

# response
r.json()
# same as cURL above
```

## Configuration

### API

All configuration options are available in `config.py`:

Option|Description|Default
------|-----------|-----------
ENDPOINT|The HDX url|https://data.hdx.rwlabs.org
RID|Resource id of the file you wish to fetch|b5b850a5-76da-4c33-a410-fd447deac042
API_KEY|Your HDX API Key|MY_API_KEY
DEBUG |Enable the Flask debugger| False
TESTING |Testing mode| False
PROD |Production mode| False
CHUNK_SIZE |Number of rows to process at a time| 10000

### ckan

Under the hood, hdx-file-proxy uses [ckanutils](https://github.com/reubano/ckanutils) and uses the following [Environment Variables](http://www.cyberciti.biz/faq/set-environment-variable-linux/) if set:

Environment Variable|Description
--------------------|-----------
CKAN_API_KEY|Your CKAN API Key

## Scripts

hdx-file-proxy comes with a built in task manager `manage.py`.

### Examples

*View all available commands*

```bash
manage
```

*Run python linter and nose tests*

```bash
pip install -r dev-requirements.txt
manage lint
manage test
```

*Run dev server on custom port and with multiple threads*

```bash
manage serve -tp 3001
```

## License

hdx-file-proxy is distributed under the [MIT License](http://opensource.org/licenses/MIT), the same as [`Flask`](http://flask.pocoo.org).
