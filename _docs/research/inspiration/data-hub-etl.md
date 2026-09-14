# data-hub-etl

GPEDC (Greater Peoria) Data Hub ETL.

Fetches economic and demographic data from the U.S. [Bureau of Labor Statistics
(BLS)][bls] and the Census [American Community Survey (ACS)][acs] APIs, transforms it,
and populates the relevant Google Sheets. Currently run as a set of CLI scripts.

[bls]: https://www.bls.gov/developers/
[acs]: https://www.census.gov/data/developers/data-sets/acs-1year.html

## How it works

For a given table, the pipeline:

1. Generates the source series IDs (BLS series or ACS variables) from the table's
   config and mapping.
2. Fetches the latest data from the BLS or ACS API.
3. Transforms the responses into rows.
4. Batch-updates the destination Google Sheet via [gspread][gspread].

[gspread]: https://gspread.readthedocs.io/

## Tables

Each table is defined in `config.py` (`Config.TABLES`) with its destination sheet, year
range, geographies, and series; field mappings live in `app/mappings.py`.

| Table | Source |
| ----- | ------ |
| `Labor Force` | BLS |
| `LFPR` (labor force participation rate) | BLS |
| `Wage` | BLS |
| `Industries` | BLS |
| `Demographics` | ACS |
| `Education` | ACS |

## Requirements

- Python 3.7
- A **BLS registration key**
- A **Google service account** with access to the destination Sheets

```bash
pip install -r requirements.txt
```

Dependencies: `Click`, `meza`, `gspread`, `oauth2client`.

## Configuration

Set the BLS key in the environment (e.g. via a `.env` file):

```
BLS_REGISTRATION_KEY=your_bls_key
```

Provide Google service-account credentials as a JSON file, referenced by
`Config.GSPREAD_CREDENTIALS_FILE` in `config.py`.

> **Security:** `Clients-*.json` in this repo is a real Google service-account private
> key. Revoke/rotate it, remove it from version control, and load credentials from an
> ignored path instead.

## Usage

```bash
# Populate the default table (Labor Force)
manage populate

# Populate a specific table
manage populate -t Wage
manage populate --table_name Demographics
```

Run directly if `manage` isn't on your `PATH`:

```bash
./manage.py populate -t Industries
```

## Development

```bash
./manage.py lint      # flake8 (+ pylint with --strict)
./manage.py prettify  # format with black
./manage.py check     # lint staged changes
```

Deploy helpers (`deploy`, `add_keys`) target Heroku remotes.
