---
source: ../../../../covid19-il-data-api/README.md
---

# COVID19 IL Data API

A Flask web API and companion CLI that scrapes daily COVID-19 data published by the
[Illinois Department of Public Health (IDPH)][idph] and stores it on local disk, on
Amazon S3, or in the [CKAN][ckan] portal at `data.openpeoria.com`. Stored reports are
keyed by date (`YYYYMMDD`); the routes that would serve them back crash as shipped
(see [Known issues](#known-issues)).

- **Version:** 0.2.0
- **License:** MIT
- **Author:** Reuben Cummings (Nerevu Group)

[idph]: https://www.dph.illinois.gov/
[ckan]: https://ckan.org/

## Overview

The service fetches three kinds of daily reports from IDPH and moves them between
backends:

- **Report types:** `county`, `zip`, `hospital`
- **Backends:** `idph` (live scrape), `local` (disk), `s3` (Amazon S3),
  `ckan` (open-data portal)

The backends are not interchangeable. Each operation is wired only for the
backends in `REPORT_FUNCS` (`app/api.py:726-748`):

| Backend | get (read) | post (write) | delete |
| ------- | ---------- | ------------ | ------ |
| `idph` | yes: scrapes `https://www.dph.illinois.gov/sitefiles/<report_name>.json` | no | no |
| `local` | no | yes: writes `<basename>.json` to the current directory | no |
| `s3` | yes: reads `<basename>.json` from the bucket | yes | no |
| `ckan` | yes: returns the CKAN resource records whose name contains `<basename>` (metadata, not report data) | yes | yes |

Any other combination raises `KeyError` from the `REPORT_FUNCS` lookup. The CLI
`choices` accept all four backends for every option, so nothing warns you
beforehand. Where the error fires:

- reading from `local` fails immediately (`app/api.py:757`);
- writing to `idph` fails only once a non-empty report was fetched
  (`app/api.py:791`);
- deleting from anything but `ckan` fails only once a report was found
  (`app/api.py:762`); with nothing found the result is a `404 No reports found`.

Jobs can be run inline or enqueued to a Redis-backed [RQ][rq] worker, with an
[rq-dashboard][rqd] mounted at `/dashboard` for monitoring. Only "add" is
genuinely queued (see [Jobs](#jobs)).

[rq]: https://python-rq.org/
[rqd]: https://github.com/Parallels/rq-dashboard

## Data

### Object naming

Each report type has a `basename` in `Config.REPORTS` (`config.py:133-262`),
formatted with the report date as `YYYYMMDD`:

| Report type | IDPH `report_name` | `basename` |
| ----------- | ------------------ | ---------- |
| `county` | `COVIDHistoricalTestResults` | `IL_county_COVID19_data_{YYYYMMDD}` |
| `zip` | `COVIDZip` | `IL_zip_COVID19_data_{YYYYMMDD}` |
| `hospital` | `COVIDHospitalRegions` | `IL_regional_hospital_data_{YYYYMMDD}` |

The `local` and `s3` destinations store the report as `<basename>.json`
(pretty-printed JSON, sorted keys).

### Report contents

What the IDPH scrape returns for a requested date (`app/api.py:517-587`):

| Report type | Keys | Date rule |
| ----------- | ---- | --------- |
| `county` | `county`, `state`, `demographics` | Empty unless the date lies between IDPH's earliest `testDate` and its `LastUpdateDate`; `demographics` is filled only for the last-updated date |
| `zip` | `zipcodes` | Empty unless the date equals IDPH's last-updated date |
| `hospital` | `state`, `region` | Empty unless the date lies between the earliest `reportDate` and the last-updated date; `region` is filled only for the last-updated date |

An empty report is not written; the add result is `304 No data found ...`.

### Date window

Every report command and the `/v1/report` routes walk back from an end date:
dates `end`, `end - 1 day`, ..., `end - (days - 1)` (`app/api.py:968-970`,
`manage.py:175-177`). `end` defaults to today and `days` to `7` (`Config.DAYS`).

### Write rules per destination

- `local`: always overwrites `<basename>.json` in the process's current directory
  (`app/api.py:478`).
- `s3`: if the object already exists, returns `304 ... already exists!` and does not
  upload, unless `overwrite` is set (`app/api.py:439-441`).
- `ckan` (filestore, the default): converts the report to CSV per CKAN resource,
  prepends the resource's existing datastore rows for other dates, and replaces the
  resource file with `resource_update` (`app/api.py:261-284,321-328`).
- `ckan` with `datastore`: inserts with `datastore_upsert` only the rows whose `date`
  is not already in the resource; when the resource has no dates yet nothing is
  posted (`app/api.py:237-258,310-320`).

The CKAN resource and package for each report section are fixed in
`Config.REPORTS[...]["csv_options"]`: `county` posts to `il-covid19-cases-county`
(county rows) and `il-covid19-cases-state` (age, gender and race demographics);
`zip` posts four resources to `illinois-covid19-cases-zip-code`; `hospital` posts
`region` and `state` resources to `illinois-regional-hospital-data`.

## Requirements

- Python 3.8 (`runtime.txt` pins 3.8.5)
- Redis (for the `--enqueue` job queue and the RQ dashboard)
- A `CKAN_API_KEY` in `.env` for the `ckan` backend. It is listed in
  `REQUIRED_SETTINGS`, but a missing key is only logged at startup; the CKAN request
  header is then built with a `None` value (`app/api.py:87`).

Optional, depending on backend:

- AWS credentials (for the `s3` backend; see [Configuration](#configuration))
- `config.py` sets `SQLALCHEMY_*` database URIs (PostgreSQL in production), but
  nothing in `app/` uses a database.

## Installation

```bash
pip install -r requirements.txt      # or: base-requirements.txt for the minimal set
pip install -r dev-requirements.txt  # for development/testing
```

Create a `.env` file in the project root:

```text
CKAN_API_KEY=your_ckan_api_key
```

> **Note:** the existing `.env` contains a real CKAN key — rotate it and keep it out of
> version control.

## Configuration

Environment variables read by `config.py` and `app/`:

| Variable | Purpose | Default |
| -------- | ------- | ------- |
| `CKAN_API_KEY` | CKAN API key for `https://data.openpeoria.com/api/3/action` | none |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | S3 credentials, used when there is no `nerevu` AWS profile (`app/api.py:62-71`) | none |
| `S3_BUCKET` | Bucket for the `s3` backend | `covid19-il` |
| `REDIS_URL`, then `REDISTOGO_URL` | Redis for RQ and the dashboard | `redis://127.0.0.1:6379` (host from `REDIS_PORT_6379_TCP_ADDR` if set) |
| `RQ_DASHBOARD_USERNAME`, `RQ_DASHBOARD_PASSWORD` | Basic auth for `/dashboard`; applied only when both are set | none |
| `COVID19-IL-DATA-API_SECRET` | `Config.SECRET` | random per process |
| `MAILGUN_DOMAIN`, `MAILGUN_SMTP_PASSWORD` | Error-log email | none |
| `STAGE` | Staging server; adds `-stage` to the server name | unset |
| `DATABASE_URL`, `REDIS_URL`, `MEMCACHIER_SERVERS`, `REDISTOGO_URL` | Any one marks a production server: in the `Production`, `Heroku` and `Custom` modes this enables Talisman HTTPS and `SERVER_NAME`; in every mode it enables the production required-setting checks | unset |

In production the secret, Mailgun, AWS and RQ dashboard settings are listed in
`REQUIRED_PROD_SETTINGS`; missing ones are logged, not fatal.

The boto3 session and S3 client are created when `app.api` is imported
(`app/api.py:62-74`), so the AWS settings are read on every startup.

## Running the server

Development server (via the `manage.py` CLI, which wraps Flask-Script):

```bash
./manage.py serve            # defaults to http://localhost:5000
./manage.py serve -p 8000    # custom port
./manage.py serve -t         # threaded
```

Production (Heroku-style, from the `Procfile`):

```bash
# web
gunicorn "app:create_app(config_mode='Heroku')" -w 3 -k gevent
# worker (the Procfile line is `manage -m Heroku work`; this repo installs no
# `manage` command, so run the script directly)
./manage.py -m Heroku work
```

The config mode is selected with `-m/--cfgmode` (`Development` (default),
`Production`, `Heroku`, `Custom`, `Ngrok`, `Test`; see `config.py`). A config file
can be given with `-f/--cfgfile`.

## API endpoints

All data routes are namespaced under the `/v1` prefix. Responses are JSON with a
`status` field holding the HTTP reason phrase (for example `"OK"`). A top-level
`status_code` in a handler's result sets the HTTP status and is not included in the
body (`app/utils.py:71-95`). Unhandled errors return HTTP 500 with
`{"result": "<ExceptionName>", "status": "Internal Server Error"}`
(`app/housekeeping.py:29-40`).

| Method(s) | Route | Description |
| --------- | ----- | ----------- |
| `GET` | `/` | Redirects to the API root |
| `GET` | `/v1` | API documentation / link index |
| `GET` | `/v1/status` | Age of the newest S3 object; raises `KeyError` as shipped (see below) |
| `GET` | `/v1/ipsum` | Random sentence (health-check / demo) |
| `GET` | `/v1/result/<job_id>` | Envelope of an enqueued job |
| `POST` | `/v1/report` | Fetch reports from a source and write them to a destination |
| `GET` | `/v1/report` | Read reports; raises `NameError` as shipped |
| `DELETE` | `/v1/report` | Delete reports; raises as shipped |
| `DELETE` | `/v1/memoization/<path>` | Delete the cache key `/v1/<path>` (only `/v1/ipsum` is stored under such a key) |
| `GET` | `/v1/memoization/<path>` | Raises `TypeError` as shipped |
| — | `/dashboard` | RQ dashboard (basic-auth protected when both RQ dashboard credentials are set) |

The `/v1` and `/v1/ipsum` routes are wrapped with a cache lifetime of
`ROUTE_TIMEOUT = 0`, so they are sent with no-cache headers (`app/utils.py:200-206`).

### `/v1/report` parameters

Query-string and form values are merged and parsed with `ast.literal_eval`
(`app/utils.py:395-406`):

| Parameter | Meaning | Default |
| --------- | ------- | ------- |
| `end` | End date, `YYYYMMDD` | today |
| `days` | Number of days to walk back from `end` | `7` |
| `report_type` | `county`, `zip` or `hospital` | `county` |
| `source` | Backend to read from | `idph` for POST and DELETE, `s3` for GET |
| `dest` | Backend to write to (POST) | `local` |
| `enqueue` | Queue the work on RQ | off |
| `datastore` | CKAN datastore insert instead of filestore (POST to `ckan`) | off |
| `overwrite` | Replace an existing S3 object (POST to `s3`) | off |

A successful `POST` returns `result` as an object keyed by report date
(`YYYYMMDD`), each value being that date's add result (`ok`, `message`,
`status_code` and backend fields such as `content_length`). The body also has
`ok`, `message` and `status`; the HTTP status is `200` when every date succeeded and
`500` otherwise. With no parameters, `POST /v1/report` scrapes the last 7 days of
the `county` report from IDPH and writes `IL_county_COVID19_data_<date>.json` files
into the server process's current directory.

### `/v1/status`

`get_status` lists the bucket objects with the report type's prefix, takes the date in
the newest key, and returns `last_updated` and `dataset_age` (days) under `result`. The
HTTP status is `200` when the newest object is under 2 days old and `500` otherwise
(`app/api.py:875-892`). Any `source` other than `s3` returns `501 Not implemented!`. The
route does not pass `report_type`, so with the default `source=s3` it raises `KeyError`
(see [Known issues](#known-issues)); the CLI `status` command passes it and works.

### Jobs

Job envelopes (`app/api.py:123-142`) have the shape
`{"ok": ..., "result": {"job_id", "job_status", "job_result", "status_code", "url"}}`,
where `url` points at `/v1/result/<job_id>` and `status_code` maps the RQ status:
`deferred`, `queued`, `started` → `202`; `finished` → `200`; `failed` → `500`;
an unknown job → `404` (`app/api.py:91-98`). `GET /v1/result/<job_id>` returns this
envelope with HTTP `200` whatever the job's state; the mapped code is only in the
body.

- **add** (`--enqueue` / `enqueue=true`): enqueues the fetch, then a dependent job
  that posts the fetched report once the fetch finishes (`app/api.py:808-814`). The
  response is the envelope of the second job.
- **load**: enqueues the fetch and immediately treats the envelope as the report,
  so it reports "Successfully found data" with the job envelope as the result
  (`app/api.py:825-828`).
- **remove**: not queued; returns `501 Enqueuing is not yet enabled for this
  action!` (`app/api.py:867-868`).

The worker (`worker.py`) listens on the `high`, `default` and `low` queues; jobs are
enqueued on `default`.

## CLI commands

`manage.py` exposes the data pipeline and dev tasks. Common report commands:

```bash
# Fetch reports from IDPH and save them to S3; walks back N days from the end date
./manage.py add_reports    --source idph --dest s3 --report-type county --days 7

# Read reports from S3 (logs a found/not-found message per date, not the data)
./manage.py load_reports   --report-type zip --days 30

# Delete reports (only the ckan backend supports delete)
./manage.py remove_reports --source ckan --report-type hospital --days 7

# Show backend status (only --source s3 is implemented)
./manage.py status --source s3 --report-type county

# Run the RQ worker (python -u worker.py)
./manage.py work
```

Each command logs its results instead of printing data. A failing date is logged
with its traceback and the loop continues; in `Development` mode (debug on) the
failure also opens the `pdb` post-mortem debugger (`app/helpers.py:88-95`).

Options per report command (`manage.py:132-288`):

| Option | Description | `add_reports` | `load_reports` | `remove_reports` | `status` |
| ------ | ----------- | ------------- | -------------- | ---------------- | -------- |
| `-d, --end` | Report ending date (`YYYYMMDD`) | today | today | today | — |
| `-n, --days` | Number of days to walk back from the end date | 7 | 7 | 7 | — |
| `-s, --source` | Backend to read from | `idph` | — (always `s3`) | `idph` (fails unless `ckan`) | `local` (returns 501 unless `s3`) |
| `-t, --dest` | Backend to write to | `local` | — | — | — |
| `-r, --report-type` | `county` / `zip` / `hospital` | `county` | `county` | `county` | `county` |
| `-e, --enqueue` | Queue the work on the RQ worker | off | off | off (returns 501) | — |
| `-a, --datastore` | CKAN datastore insert instead of filestore | off | — | — | — |

`add_reports` has no `--overwrite` option, so it never replaces an existing S3
object; `overwrite` is available only as a `/v1/report` parameter.

Development helpers: `check`, `checkstage`, `test`, `lint`, `prettify` (black),
`deploy`, `add_keys`, `require`. `deploy` runs `git push origin features`, or
`git push origin master` with `-r production`; `add_keys` adds your SSH key to a
Heroku remote; `require` writes `base-requirements.txt` from `pip freeze`.

## Data files

The working tree also holds some static geospatial and sample data:

- `IL_hospital_regions_map.geojson`, `IL_zip_codes.geojson` — boundary geometries
- `IL_regional_hospital_data_*.json` — regional hospital reports, named like the
  `local` destination's output

## Development

```bash
./manage.py test     # nose (the tests/ directory is empty)
./manage.py lint     # flake8 (+ pylint with --strict)
./manage.py prettify # format with black
```

CI is configured via `.travis.yml`.

## Known issues

- `GET /v1/status` raises `KeyError` because `report_type` is never passed to
  `get_status` (`app/api.py:919`, `app/api.py:106`).
- `GET /v1/report` raises `NameError` after loading the reports: `report_phrase` is
  never assigned in `Report.get` (`app/api.py:1009`).
- `DELETE /v1/report` raises: with the default `source=idph`, `KeyError` from the
  `("idph", "delete", ...)` lookup (`app/api.py:762`); in every case, `NameError` for
  `report_phrase` in `Report.delete` (`app/api.py:1037`).
- Deleting from `ckan` deletes the resources, then raises `KeyError` building the
  result, because the delete responses have no `name` key (`app/api.py:862`,
  `app/api.py:608-615`).
- `POST /v1/report` with `days=0` raises `UnboundLocalError`: with no dates in the
  loop, `report_date`, `message` and `status_code` are never assigned
  (`app/api.py:977-989`).
- `GET /v1/memoization/<path>` raises `TypeError`: `Memoization.get` takes no `path`
  argument (`app/api.py:1054`). The clear-all branch of `delete` is unreachable
  because only the `<path>` route is registered (`app/api.py:1070-1072,1105-1107`).
- `remove_reports` with its default `--source idph`, any command with `--source
  local`, and `add_reports --dest idph` raise `KeyError` from `REPORT_FUNCS`
  (`app/api.py:757,762,791`).
- An enqueued load returns the job envelope as if it were report data
  (`app/api.py:825-828`).
- The `Procfile` worker runs `manage -m Heroku work`, but `setup.py` defines no
  `manage` console script.
- `./manage.py check` calls `helpers/check-stage` and `./manage.py checkstage` calls
  `app/tests/test.sh`, neither of which exists; `./manage.py lint --strict` reads
  `tests/standard.rc`, which does not exist (`manage.py:61,68,99`).
