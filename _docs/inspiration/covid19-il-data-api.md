# COVID19 IL Data API

A Flask web API and companion CLI that scrapes daily COVID-19 data published by the
[Illinois Department of Public Health (IDPH)][idph], stores it (locally, on Amazon S3,
or in a [CKAN][ckan] datastore), and serves it back as JSON time series.

- **Version:** 0.2.0
- **License:** MIT
- **Author:** Reuben Cummings (Nerevu Group)

[idph]: https://www.dph.illinois.gov/
[ckan]: https://ckan.org/

## Overview

The service fetches three kinds of daily reports from IDPH and moves them between
several backends:

- **Report types:** `county`, `zip`, `hospital`
- **Sources / destinations:** `idph` (live scrape), `local` (disk), `s3` (Amazon S3),
  `ckan` (open-data portal)

Long-running fetch/upload jobs can be run inline or enqueued to a Redis-backed
[RQ][rq] worker, with an [rq-dashboard][rqd] mounted at `/dashboard` for monitoring.

[rq]: https://python-rq.org/
[rqd]: https://github.com/Parallels/rq-dashboard

## Requirements

- Python 3.8
- Redis (for the `--enqueue` job queue and caching)
- A `CKAN_API_KEY` in `.env` — **required** to read from or write to CKAN

Optional, depending on backend:

- AWS credentials (for the `s3` source/destination)
- PostgreSQL / Memcached (used in production config)

## Installation

```bash
pip install -r requirements.txt      # or: base-requirements.txt for the minimal set
pip install -r dev-requirements.txt  # for development/testing
```

Create a `.env` file in the project root:

```
CKAN_API_KEY=your_ckan_api_key
```

> **Note:** the existing `.env` contains a real CKAN key — rotate it and keep it out of
> version control.

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
# worker
./manage.py -m Heroku work
```

The config mode is selected with `-m/--cfgmode` (`Development`, `Heroku`, etc.; see
`config.py`).

## API endpoints

All data routes are namespaced under the `/v1` prefix.

| Method(s) | Route | Description |
| --------- | ----- | ----------- |
| `GET` | `/` | Redirects to the API root |
| `GET` | `/v1` | API documentation / link index |
| `GET` | `/v1/status` | Status of the S3 bucket / stored reports |
| `GET` | `/v1/ipsum` | Random sentence (health-check / demo) |
| `GET` | `/v1/result/<job_id>` | Result of an enqueued job |
| `GET` `POST` `DELETE` | `/v1/report` | Fetch, upload, or delete reports |
| `GET` `DELETE` | `/v1/memoization/<path>` | Inspect or clear the memoization cache |
| — | `/dashboard` | RQ dashboard (optionally basic-auth protected) |

## CLI commands

`manage.py` exposes the data pipeline and dev tasks. Common report commands:

```bash
# Upload (or save) reports; walks back N days from the end date
./manage.py add_reports    --source idph --dest s3 --report-type county --days 7

# Fetch reports as a time series
./manage.py load_reports   --report-type zip --days 30

# Delete reports
./manage.py remove_reports --report-type hospital --days 7

# Show backend status
./manage.py status --source s3 --report-type county

# Run the RQ worker
./manage.py work
```

Shared options for the report commands:

| Option | Description | Default |
| ------ | ----------- | ------- |
| `-d, --end` | Report ending date (`YYYYMMDD`) | today |
| `-n, --days` | Number of historical days to fetch back from the end date | 7 |
| `-s, --source` | Source location: `idph` / `local` / `s3` / `ckan` | `idph` |
| `-t, --dest` | Destination: `idph` / `local` / `s3` / `ckan` (add only) | `local` |
| `-r, --report-type` | `county` / `zip` / `hospital` | `county` |
| `-e, --enqueue` | Queue the work on the RQ worker instead of running inline | off |
| `-a, --datastore` | Add via CKAN datastore instead of filestore (add only) | off |

Development helpers: `check`, `checkstage`, `test`, `lint`, `prettify` (black),
`deploy`, `add_keys`, `require`.

## Data files

The repo also ships some static geospatial and sample data:

- `IL_hospital_regions_map.geojson`, `IL_zip_codes.geojson` — boundary geometries
- `IL_regional_hospital_data_*.json` — sample regional hospital snapshots

## Development

```bash
./manage.py test    # run tests (nose)
./manage.py lint     # flake8 (+ pylint with --strict)
./manage.py prettify # format with black
```

CI is configured via `.travis.yml`.
