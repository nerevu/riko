# HDX Ageing Service

## Introduction

The hdx-age-api is a [`Flask`](http://flask.pocoo.org) powered service to query
the age and status of an HDX resource. It performs updates asynchronously off a
Redis backed queue via a python worker process.

## Requirements

hdx-age-api has been tested on the following configuration:

- MacOS X 10.9.5
- Python 2.7.10
- Redis server v=2.8.17
- memcached 1.4.17
- postgres (PostgreSQL) 9.4.1

hdx-age-api requires the following in order to run properly in development mode:

- [Python >= 2.7](http://www.python.org/download)
- [Redis >= 2.8](http://www.redis.org)

hdx-age-api requires the following in order to run properly in production mode:

- [Python >= 2.7](http://www.python.org/download)
- [Redis >= 2.8](http://www.redis.org)
- [memcached >= 1.4](http://www.memcached.org)
- [postgres >= 9.4](http://www.postgres.org)

## Setup

### local

(You are using a [virtualenv](http://www.virtualenv.org/en/latest/index.html), right?)

    sudo pip install -r requirements.txt
    manage setup
    manage serve

Open a separate console to launch the worker

    manage work

Open a separate console to launch the dashboard (optional)

    manage dash

### Docker

    make setup
    make work

### Production

    pip install -r prod-requirements.txt
    sudo -u postgres pg_ctl start
    memcached -vv
    manage -m Production setup
    gunicorn app:create_app('Production') -w 3 -k gevent
    screen -dS worker -m python worker.py

## Usage

hdx-age-api is intended to be used via HTTP requests.

### Examples

#### cURL

*Check the status of the API*

```bash
# request
curl http://localhost:3000/v1/status/

# response
{
    "online": "True",
    "message": "Service for checking and updating HDX dataset ages.",
    "CKAN_instance": "https://data.hdx.rwlabs.org",
    "version": "0.5.2",
    "repository": "https://github.com/reubano/hdx-age-api"
}
```

*Update a package*

```bash
# request
curl http://localhost:3000/v1/update/<ckan_package_id>/

# response
{
    'job_id': "nvjf8ndo20u2b1o2",
    'job_status': "queued",
    'result_url': "http://localhost:3000/v1/result/nvjf8ndo20u2b1o2/"
}
```

*Get the result of a queued job*

```bash
# request
curl http://localhost:3000/v1/result/<job_id>/

# response
{
    'job_id': "nvjf8ndo20u2b1o2",
    'job_status': "started",
    'result': "None"
}
```

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

```bash
# request
r = requests.get('%s/update/<ckan_package_id>/' % endpoint)

# response
r.json()
# same as cURL above
```

*Get the result of a queued job*

```bash
# request
r = requests.get('%s/result/<job_id>/' % endpoint)

# response
r.json()
# same as cURL above

```

## Configuration

### API

All configuration options are available in `config.py`:

Option|Description|Default
------|-----------|-----------
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

### ckan

Under the hood, hdx-age-api uses [ckanutils](https://github.com/reubano/ckanutils) and requires that the following [Environment Variables](http://www.cyberciti.biz/faq/set-environment-variable-linux/) are set:

Environment Variable|Description
--------------------|-----------
CKAN_API_KEY|Your CKAN API Key
CKAN_REMOTE_URL|Your CKAN instance remote url
CKAN_USER_AGENT|Your user agent

## Scripts

hdx-age-api comes with a built in task manager `manage.py`.

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
[![](https://badge.imagelayers.io/luiscape/hdx-monitor-ageing-service:latest.svg)](https://imagelayers.io/?images=luiscape/hdx-monitor-ageing-service:latest 'Get your own badge on imagelayers.io')

This application needs a volume mounted, four environment variables, and a link to a redis instance in order to run successfully. When running, use the following Docker command:

```shell
$ docker run -d \
  -e CKAN_API_KEY=[SYSADMIN_API_KEY] \
  -e CKAN_REMOTE_URL=[CKAN_URL] \
  -e CKAN_PROD_URL=[CKAN_URL] \
  -e CKAN_USER_AGENT=[DESIRED_USER_AGENT] \
  -v ./data:/data \
  --link redis:redis \
  --name age \
  luiscape/hdx-monitor-ageing-service:latest
```

## License

hdx-age-api is distributed under the [MIT License](http://opensource.org/licenses/MIT), the same as [`Flask`](http://flask.pocoo.org).
