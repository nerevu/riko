---
source: ../../../../HDX/hdx-age-api/README.md
---

# HDX Ageing Service

## Introduction

The hdx-age-api is a [`Flask`](http://flask.pocoo.org) powered service to
calculate and query the age and update status of HDX datasets (CKAN packages).
It fetches package metadata from CKAN, works out how old each dataset is
relative to its expected update frequency, and stores one record per dataset in
a database that is exposed via a REST API. Updates run asynchronously off a
Redis backed queue via a python worker process.

## Requirements

hdx-age-api has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.10
- Redis server v=2.8.17
- memcached 1.4.17
- postgres (PostgreSQL) 9.4.1

hdx-age-api requires the following in order to run properly in development mode:

- [Python 2.7](http://www.python.org/download) (Python 3 is not supported)
- [Redis >= 2.8](http://www.redis.org)

hdx-age-api requires the following in order to run properly in production mode:

- [Python 2.7](http://www.python.org/download)
- [Redis >= 2.8](http://www.redis.org)
- [memcached >= 1.4](http://www.memcached.org)
- [postgres >= 9.4](http://www.postgres.org)

## Setup

### local

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

```text
pip install -r requirements.txt
export CKAN_REMOTE_URL=https://data.hdx.rwlabs.org
manage setup
manage serve
```

Open a separate console to launch the worker

```text
manage work
```

Open a separate console to launch the dashboard (optional)

```text
manage dash
```

The `manage` command is provided by the `manage.py` package in
`requirements.txt`; `python manage.py <command>` works as well.

**Note:** `manage` runs in `Development` mode by default. Development mode
mocks each dataset's update frequency with a random value (`MOCK_FREQ`) and
only processes 50 datasets (`ROW_LIMIT`), so the stored data is *not* real.
Use `manage -m Production <command>` (or override the options per request, see
[Update datasets](#update-datasets)) to get real results.

### Docker

```text
make setup
make run
```

`make setup` creates a virtualenv, installs the requirements, and creates the
SQLite database at `data/app.db`. `make run` starts the worker (in a `screen`
session) and then the API in `Docker` mode. `make worker` starts only the worker.

### Production

```text
pip install -r prod-requirements.txt
sudo -u postgres pg_ctl start
memcached -vv
manage -m Production setup
gunicorn "app:create_app('Production')" -w 3 -k gevent
screen -dS worker -m python worker.py
```

## Usage

hdx-age-api is intended to be used via HTTP requests. All endpoints are
prefixed with `/v1` and served on port 3000 by default.

Endpoint | Description
---------|------------
`GET /v1/status/` | Service status
`GET /v1/update/` | Queue an update of *every* dataset
`GET /v1/update/<package_id>/` | Queue an update of a single dataset
`GET /v1/result/<job_id>/` | Status and result of a queued update
`GET /v1/age` | Query the stored dataset records
`GET /v1/age/<dataset_id>` | A single stored dataset record

### Dataset records

Each update stores one record per dataset (the `Age` model in `app/models.py`).
Records are keyed by `dataset_id`; re-running an update overwrites the existing
record.

Field | Type | Description
------|------|------------
`dataset_id` | string | CKAN package id (primary key)
`dataset_name` | string | CKAN package name (url slug)
`dataset_title` | string | CKAN package title
`last_updated` | datetime | Most recent update timestamp across the package's resources
`age` | integer | Days between `last_updated` and the time of the update run
`frequency` | integer | Expected update frequency in days, from the package's `data_update_frequency` field (missing or empty → `0`)
`frequency_category` | string | Human readable `frequency` (see below)
`status` | string | Update status (see below)
`needs_update` | boolean | `true` if `status` is `Due for update`, `Overdue`, or `Delinquent`
`downloads` | integer | Total downloads, summed across the package's resources (`tracking_summary.total`)
`utc_created` | datetime | When the record was first created
`utc_updated` | datetime | When the record was last updated

Packages with no resources are skipped.

#### Status

`status` is determined by comparing `age` against three thresholds for the
dataset's `frequency`:

`frequency` | `frequency_category` | `Due for update` at | `Overdue` at | `Delinquent` at
------------|----------------------|---------------------|--------------|----------------
0 | Archived | — | — | always
1 | Every day | 1 day | 2 days | 3 days
7 | Every week | 7 days | 14 days | 21 days
14 | Every two weeks | 14 days | 21 days | 28 days
30 | Every month | 30 days | 44 days | 60 days
90 | Every three months | 90 days | 120 days | 150 days
180 | Every six months | 180 days | 210 days | 240 days
365 | Every year | 365 days | 425 days | 455 days

A dataset younger than the `Due for update` threshold is `Up-to-date`.
Datasets with a frequency of `0` (`Archived`, which includes datasets with no
`data_update_frequency` set) are always `Delinquent`.

Any other `frequency` value gets the status `Invalid frequency` and no
`frequency_category`. Such records can't be saved (`frequency_category` is
required), so they are reported in the job's `errors` and count toward
`ERR_LIMIT` (see [Get the result of a job](#get-the-result-of-a-job)).

### Examples

#### cURL

*Check the status of the API*

```bash
# request
curl http://localhost:3000/v1/status/

# response
{
  "CKAN_instance": "https://data.hdx.rwlabs.org",
  "message": "Service for checking and updating HDX dataset ages.",
  "online": true,
  "repository": "https://github.com/reubano/HDX-Age-API",
  "version": "0.6.2"
}
```

#### Update datasets

```bash
# request (single dataset)
curl http://localhost:3000/v1/update/<ckan_package_id>/

# request (every dataset in every organization readable with your API key)
curl http://localhost:3000/v1/update/

# response
{
  "job_id": "nvjf8ndo20u2b1o2",
  "job_status": "queued",
  "result_url": "http://localhost:3000/v1/result/nvjf8ndo20u2b1o2/"
}
```

The update endpoints accept the following query parameters, which override the
matching [configuration](#api) options for that request:

Parameter | Description
----------|------------
`sync` | Run the update immediately and return its result instead of queueing a job (default: `false`)
`chunk_size` | `CHUNK_SIZE`
`row_limit` | `ROW_LIMIT`
`err_limit` | `ERR_LIMIT`
`mock_freq` | `MOCK_FREQ`
`timeout` | `TIMEOUT`
`result_ttl` | `RESULT_TTL`
`remote` | CKAN instance url (default: `CKAN_REMOTE_URL`)
`ua` | CKAN user agent (default: `CKAN_USER_AGENT`)

For example, `curl "http://localhost:3000/v1/update/?row_limit=0&mock_freq=false"`
updates all datasets with their real frequencies. With `sync=true` the response
is `{"result": <job result>}` (see below). `/v1/status/` also accepts `remote`.

#### Get the result of a job

```bash
# request
curl http://localhost:3000/v1/result/<job_id>/

# response (job still running)
{
  "job_id": "nvjf8ndo20u2b1o2",
  "job_status": "started",
  "result": null
}

# response (job finished)
{
  "job_id": "nvjf8ndo20u2b1o2",
  "job_status": "finished",
  "result": {
    "elapsed_time": "2 minutes ,5 seconds",
    "errors": {},
    "rows_added": 50
  }
}
```

`job_status` is one of `queued`, `started`, `finished`, `failed`, or
`job not found`. The HTTP status code reflects it:

`job_status` | HTTP status
-------------|------------
`queued`, `started` | 202
`finished` | 200
`failed` | 500
`job not found` | 404

A finished job's `result` contains:

Field | Description
------|------------
`rows_added` | Number of dataset records successfully created or updated
`errors` | Records that failed to save, as `{<dataset_id>: <error response>}`
`elapsed_time` | How long the update took

A job fails once `errors` reaches `ERR_LIMIT` entries, or if it runs longer than
`TIMEOUT`. Results are kept for `RESULT_TTL` seconds.

#### Query dataset records

The `/v1/age` endpoints are generated by
[Flask-Restless](https://flask-restless.readthedocs.org/en/0.17.0/) from the
`Age` model.

```bash
# request
curl http://localhost:3000/v1/age

# response
{
  "num_results": 1,
  "objects": [
    {
      "age": 12,
      "dataset_id": "4fb1bb1e-6e66-4d4b-8e2e-3f0e0b9a6c5b",
      "dataset_name": "ebola-cases-2014",
      "dataset_title": "Ebola Cases 2014",
      "downloads": 1520,
      "frequency": 7,
      "frequency_category": "Every week",
      "last_updated": "2015-10-27T09:15:42.517000",
      "needs_update": true,
      "status": "Due for update",
      "utc_created": "2015-10-01T12:00:00",
      "utc_updated": "2015-11-08T12:00:00"
    }
  ],
  "page": 1,
  "total_pages": 1
}
```

Results are paginated with the `page` and `results_per_page` parameters (max
1000). Filter and sort with the `q` parameter, e.g., all datasets that need an
update, oldest first:

```bash
curl -G http://localhost:3000/v1/age \
  --data-urlencode 'q={"filters":[{"name":"needs_update","op":"eq","val":true}],"order_by":[{"field":"age","direction":"desc"}]}'
```

See the
[Flask-Restless docs](https://flask-restless.readthedocs.org/en/0.17.0/searchformat.html)
for the full query format.

**Note:** this endpoint also accepts `POST`, `PUT`, `PATCH`, and `DELETE` (the
worker uses them to store records) and has no authentication.

#### Python

initialize

```python
# init requirements
import requests

endpoint = 'http://localhost:3000/v1'
```

*Check the status of the API*

```python
# request
r = requests.get('%s/status/' % endpoint)

# response
r.json()
# same as cURL above
```

*Update a package*

```python
# request
r = requests.get('%s/update/<ckan_package_id>/' % endpoint)

# response
r.json()
# same as cURL above
```

*Get the result of a queued job*

```python
# request
r = requests.get('%s/result/<job_id>/' % endpoint)

# response
r.status_code  # 202 until the job finishes
r.json()
# same as cURL above
```

*Get datasets that need an update*

```python
import json

q = {'filters': [{'name': 'needs_update', 'op': 'eq', 'val': True}]}
r = requests.get('%s/age' % endpoint, params={'q': json.dumps(q)})
r.json()['objects']
```

## Configuration

### API

All configuration options are available in `config.py`:

Option|Description|Default
------|-----------|-----------
HOST |The server host| `127.0.0.1` (`0.0.0.0` in Production and Docker modes)
PORT |The server port| 3000 (or the `PORT` environment variable)
API_URL_PREFIX |Prefix for all API endpoints| `/v1`
API_MAX_RESULTS_PER_PAGE |Max `results_per_page` for `/v1/age`| 1000
CACHE_TIMEOUT |Amount of time to store memcache keys (in seconds)| 3600  # 1 hour
MOCK_FREQ |Mock the `frequency` field of a ckan package| False
DEBUG |Enable the Flask debugger| False
MEMCACHE |Enable Memcache| True
TESTING |Testing mode| False
PROD |Production mode| False
CHUNK_SIZE |Number of rows to process at a time| 10000
ERR_LIMIT |Number of errors to encounter before failing| 10
ROW_LIMIT |Total number of rows to process| 0  # All
TIMEOUT |Max amount of time given to finish a job (in seconds)| 10800  # 3 hours
RESULT_TTL |Amount of time to store a job result (in seconds)| 21600  # 6 hours

### Modes

Select a mode with `manage -m <mode>` (`Development` by default) or
`create_app('<mode>')`.

Mode | Database | Overrides
-----|----------|----------
Development | SQLite `app.db` | `MOCK_FREQ=True`, `DEBUG=True`, `CHUNK_SIZE=10`, `ROW_LIMIT=50`, `MEMCACHE=False`, `TIMEOUT=600`, `RESULT_TTL=1200`
Production | `DATABASE_URL`, or postgres `postgres://reubano@localhost/app` | `PROD=True`, `HOST=0.0.0.0`
Docker | SQLite `data/app.db` | `PROD=True`, `HOST=0.0.0.0`, `MEMCACHE=False`
Test | SQLite in memory | `TESTING=True`, `ROW_LIMIT=10`, `MEMCACHE=False`, `TIMEOUT=30`, `RESULT_TTL=60`

Alternatively, pass a config file with `manage -f <file>`, or set the
`APP_SETTINGS` environment variable to a config file path.

### ckan

Under the hood, hdx-age-api uses [ckanutils](https://github.com/reubano/ckanutils) and
requires that the following
[Environment Variables](http://www.cyberciti.biz/faq/set-environment-variable-linux/)
are set:

Environment Variable|Description
--------------------|-----------
CKAN_API_KEY|Your CKAN API Key
CKAN_REMOTE_URL|Your CKAN instance remote url
CKAN_USER_AGENT|Your user agent

### Other environment variables

Environment Variable|Description
--------------------|-----------
REDISTOGO_URL|Redis url (default: `redis://<REDIS_PORT_6379_TCP_ADDR>:6379`)
REDIS_PORT_6379_TCP_ADDR|Redis host, set by Docker's `--link redis:redis` (default: `localhost`)
DATABASE_URL|Production database url (also sets the Heroku `SERVER_NAME`)
MEMCACHIER_SERVERS / MEMCACHE_SERVERS|Memcache servers
MEMCACHIER_USERNAME / MEMCACHIER_PASSWORD|Memcache credentials (Production mode)
PORT|Server port
SECRET_KEY|Flask secret key
STAGE|Set to `true` on a staging server
APP_SETTINGS|Path to a config file

## Scripts

hdx-age-api comes with a built in task manager `manage.py`.

Command | Description
--------|------------
`serve` | Run the dev server (`-h` host, `-p` port, `-t` threaded)
`work` | Run the rq worker
`dash` | Run the rq dashboard
`setup` | Clear the database and create new tables
`createdb` | Create the database tables
`cleardb` | Remove all tables
`lint` | Check style with flake8
`test` | Run nose tests (`-x` stop after first error)

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

## Docker Usage

[![imagelayers badge](https://badge.imagelayers.io/luiscape/hdx-monitor-ageing-service:latest.svg)](https://imagelayers.io/?images=luiscape/hdx-monitor-ageing-service:latest 'Get your own badge on imagelayers.io')

This application needs a volume mounted, three environment variables, and a link to a
redis instance in order to run successfully. When running, use the following Docker
command:

```shell
$ docker run -d \
  -e CKAN_API_KEY=[SYSADMIN_API_KEY] \
  -e CKAN_REMOTE_URL=[CKAN_URL] \
  -e CKAN_USER_AGENT=[DESIRED_USER_AGENT] \
  -v "$(pwd)/data:/hdx-monitor-ageing-service/data" \
  --link redis:redis \
  --name age \
  luiscape/hdx-monitor-ageing-service:latest
```

The SQLite database is stored at `/hdx-monitor-ageing-service/data/app.db`
inside the container.

## License

hdx-age-api is distributed under the [MIT License](http://opensource.org/licenses/MIT),
the same as [`Flask`](http://flask.pocoo.org).
