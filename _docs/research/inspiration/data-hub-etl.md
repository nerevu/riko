---
source: ../../../../data-hub-etl/README.md
---

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
   config and mapping:
   - **BLS:** one id per area and series, composed as `prefix` + `seasonal_adjustment` +
     the area code + `data_type` + `size` + `ownership` + the series code. Without a
     `series` list, each area gets the single id `prefix` + `seasonal_adjustment` + area
     code.
   - **ACS:** the series variables, the county codes of the table's areas, and the
     state code.
2. Fetches the latest data from the BLS or ACS API:
   - **BLS:** one `POST` per area to `https://api.bls.gov/publicAPI/v2/timeseries/data`
     with that area's series ids, the table's `start_year`/`end_year`, and the BLS
     registration key.
   - **ACS:** one `GET` per year from `start_year` to `end_year` to
     `https://api.census.gov/data/{year}/acs/{survey}/{kind}` (`survey` and `kind` come
     from the table), with `get=<variables>`, `for=county:<codes>`, and
     `in=state:<code>`. No Census API key is sent.
3. Transforms the responses into rows.
4. Batch-updates the destination Google Sheet via [gspread][gspread]. Each run fully
   replaces the sheet's contents; nothing is appended:
   - The table's sheet is opened by `destination_sheet_id` (or by `sheet_name`), and
     the data goes to its first worksheet (`sheet1`). No table sets `worksheet_name` or
     `worksheet_pos`.
   - The worksheet is cleared, the header row is inserted, and the data rows are
     written from row 2.
   - Rows are written in batches of `Config.CHUNK_SIZE` (1024) with `update_cells(...,
     value_input_option="USER_ENTERED")`, so Sheets parses each value as if typed
     (numbers and dates become typed cells).
   - When a batch would run past the end of the worksheet, the worksheet is resized to
     the batch's last row plus `Config.ADDITIONAL_ROWS` (2048).
   - When the Sheets API answers HTTP 429 (quota exceeded), the call waits 100 seconds
     and retries, with no retry limit. Any other API error stops the run.

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

### Output columns

The header row, and the order of the columns in every row, is built from the table's
config:

1. `category_name`, if set: the year of the request for ACS, the fetched area for BLS
   (only the ACS tables set it)
2. `area_name`, if set
3. each column in `meta`
4. each column in `process`
5. then either `series_name` followed by `value_name` (default `Value`), giving one row
   per series value, or, when `series_name` is not set, one column per entry in
   `series`

## Requirements

- Python 3.7
- A **BLS registration key**
- A **Google service account** with access to the destination Sheets

```bash
pip install -r requirements.txt
pip install pygogo pkutils
```

Dependencies: `Click`, `meza`, `gspread`, `oauth2client`, `pygogo`, `pkutils`
(`requests` is installed with `gspread`). `requirements.txt` lists only the first four;
`config.py` and `manage.py` also import `pygogo` and `pkutils`, so install those too.

## Configuration

Set the BLS key in the environment:

```text
BLS_REGISTRATION_KEY=your_bls_key
```

Loading it from a `.env` file is intended; nothing loads `.env` today. `config.py` reads
the variable with `getenv`, and `python-dotenv` is only in `dev-requirements.txt`.
Export the variable in your shell, or run the command under a dotenv runner.

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

`lint --strict` runs pylint with `tests/standard.rc`, and `check` runs
`helpers/check-stage`. Neither file is in the repo, so both fail today (see
[Known issues](#known-issues)).

Deploy helpers (`deploy`, `add_keys`) target Heroku remotes (intended for `deploy`).
`add_keys` adds your SSH key to a Heroku remote (`-r`, default `staging`). `deploy` runs
`git push origin features`, or `git push origin master` with `-r production`; today it
pushes a branch to `origin`, not to a Heroku remote.

## Known issues

- `./manage.py lint --strict` and `./manage.py check` fail: `tests/standard.rc`
  (manage.py:65) and `helpers/check-stage` (manage.py:43) are not in the repo.
- `.env` files are not loaded (config.py:220 reads `getenv` directly).
- `pygogo` and `pkutils` are imported (config.py:13,15; manage.py:9) but missing from
  `requirements.txt`.
- ACS rows always use the key `Value` (app/utils.py:221), while the header uses the
  table's `value_name` (app/utils.py:315). An ACS table that set `value_name` would stop
  with a `KeyError` when its rows are written (app/utils.py:255). No ACS table sets it.
- A 429 from the Sheets API is retried forever, 100 seconds apart (app/utils.py:59-63).
