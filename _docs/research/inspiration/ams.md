---
source: ../../../../ams/README.md
---

# AMS

**A**lert **M**onitoring **S**ystem — a command-line tool to download OECD economic
indicators for the BRICS countries, monitor them against thresholds, and fire
desktop notifications when an indicator crosses a level you care about (intended; today
it notifies whenever the latest value is past the level, see
[How alerts work](#how-alerts-work)).

Data is pulled from the [OECD Main Economic Indicators (MEI) archive][mei] via its
SDMX-JSON API (intended; as of 2026-11-04 that endpoint returns `404 Not Found`, so
every `ams download` exits with an error, see [Known issues](#known-issues)).
Notifications are delivered through [Growl][growl] on macOS.

[mei]: http://stats.oecd.org/SDMX-JSON/data/MEI_ARCHIVE
[growl]: http://growl.info/

## Requirements

- macOS (notifications use AppleScript + Growl via PyObjC)
- Python 3
- [Growl](http://growl.info/) running for desktop notifications

AMS runs Growl's registration AppleScript on every command, before the command
itself runs. If Growl isn't running, registration and notifications do nothing.

## Installation

```bash
pip install -r requirements.txt
chmod +x ams   # if needed
```

Run it directly with `./ams` or add it to your `PATH`.

## Coverage

**Countries** (BRICS)

| Code  | Country       | Currency |
| ----- | ------------- | -------- |
| `BRA` | Brazil        | BRL      |
| `RUS` | Russia        | RUB      |
| `IND` | India         | INR      |
| `CHN` | China         | CNY      |
| `ZAF` | South Africa  | ZAR      |

**Indicators**

| Name           | Description                              | Frequencies         | Unit     | OECD id |
| -------------- | ---------------------------------------- | ------------------- | -------- | ------- |
| `balance`      | Current Account Balance                  | quarterly           | currency | `701`   |
| `CPI`          | Consumer Price Index                     | monthly             | index    | `401`   |
| `GDP`          | GDP Total, constant prices               | quarterly           | currency | `101`   |
| `industry`     | Industrial Production                    | monthly, quarterly  | index    | `201`   |
| `exports`      | International Trade in Goods — Exports    | monthly             | currency | `703`   |
| `imports`      | International Trade in Goods — Imports    | monthly             | currency | `702`   |
| `construction` | Production in Construction               | monthly, quarterly  | index    | `203`   |
| `retail`       | Retail Trade Volume                      | monthly, quarterly  | index    | `202`   |

A `currency` unit is reported as the country's currency code (e.g. `ZAR`); an `index`
unit is reported as `index`.

## Usage

```bash
ams <command> [options]
```

### `download` — fetch indicator data

Downloads data for a country/indicator and prints it. After a successful download, AMS
checks your visible (not removed) alerts and notifies you if a threshold has been
crossed (intended; today it notifies for each alert whose threshold the latest value is
past, see
[How alerts work](#how-alerts-work)).

```bash
# CPI for South Africa over the last 6 months (defaults)
ams download

# GDP for Brazil, as JSON
ams download --country BRA --indicator GDP --format json

# Industrial production for China, quarterly, custom date range
ams download -c CHN -i industry -f quarterly -s "12 months ago" -e "this month"
```

| Option           | Flag | Default          | Description                                              |
| ---------------- | ---- | ---------------- | -------------------------------------------------------- |
| `--country`      | `-c` | `ZAF`            | Country code (see table above)                           |
| `--indicator`    | `-i` | `CPI`            | Indicator name (see table above)                         |
| `--start`        | `-s` | `6 months ago`   | Start of date range                                      |
| `--end`          | `-e` | `this month`     | End of date range                                        |
| `--frequency`    | `-f` | indicator's first supported | `monthly` or `quarterly`                      |
| `--edition`      | `-d` | `recent`         | Forecast edition (`YYYYMM`, or `recent`)                 |
| `--format`       | `-o` | `table`          | Output format: `csv`, `json`, or `table`                 |

Asking for a frequency the indicator doesn't support (e.g. `-i GDP -f monthly`) exits
with ``Frequency `monthly` not supported for ...`` and a non-zero status.

**Date formats** for `--start` / `--end` accept natural phrases as well as explicit
dates:

- `this month`, `last month`, `next month`, `this year`, `last year`, `next year`
- `6 months ago`, `3 years ago`
- `5/4/82` (any parseable date written without spaces, e.g. `1982-05-04`)

Dates are computed in UTC and snap to a period boundary:

- Month phrases give that month (`last month` → `2026-10` in November 2026).
- Year phrases give January of that year (`this year` → `2026-01`, `3 years ago` →
  `2023-01`), so `--end "this year"` stops at January.
- With `--frequency quarterly`, the result is the quarter containing that month
  (`this month` → `2026-Q4`).

Other phrases fail: a `week` unit (`last week`, `2 weeks ago`) raises `KeyError`, and a
two-word date such as `May 1982` raises `UnboundLocalError`.

**Editions** — the OECD releases the previous month's edition on the 15th. `recent`
automatically resolves to last month's edition on or after the 15th (UTC), otherwise
the month before.

#### Output

Every format has one record per period. The period column is `Month` (`YYYY-MM`) for
monthly data or `Quarter` (`YYYY-Qn`) for quarterly data.

| Field              | Description                                                     |
| ------------------ | --------------------------------------------------------------- |
| `Month`/`Quarter`  | Period id                                                       |
| `value`            | Observed value, as returned by the OECD                         |
| `unit`             | Currency code (e.g. `ZAR`) for currency indicators, else `index` |

- `json` prints a list of these records:
  `[{"Month": "<period>", "value": <number>, "unit": "<unit>"}, ...]`.
- `csv` prints the same records with a `Month|Quarter,value,unit` header.
- `table` prints a three-line title (indicator name, `<frequency> estimates for
  <location>`, `(as of <edition> ed.)`) and then a two-column table of period name and
  value, with values formatted as `,.1f`.

If the OECD request fails, AMS prints an error and exits with status 1. Alerts are not
checked. The error format follows `--format`:

- `json`: a Python dict, `{'data': None, 'message': '<message>'}` (not valid JSON).
- `csv`: a header `Month|Quarter,value,unit,message` and one row of the start period,
  `null`, the indicator's unit kind (`index` or `currency`), and the message.
- `table`: the message alone.

The message is `No results found.` when the OECD response says so, and the raw response
body otherwise.

### `add` — create an alert

Fires a notification on every matching `download` whose latest value is above (`max`)
or below (`min`) a threshold.

```bash
# Notify when South Africa's CPI rises above 110
ams add 110 --country ZAF --indicator CPI --type max

# Notify when any country's GDP falls below 0
ams add 0 -i GDP -t min
```

| Argument/Option | Flag | Default          | Description                                              |
| --------------- | ---- | ---------------- | -------------------------------------------------------- |
| `threshold`     | —    | *(required)*     | Threshold value                                          |
| `--type`        | `-t` | `max`            | `max` (alert if value rises above) or `min` (falls below)|
| `--country`     | `-c` | any country      | Country code to watch                                    |
| `--indicator`   | `-i` | any indicator    | Indicator to watch                                       |

An alert is identified by its sentence, which `add` prints on success:

```text
$ ams add 110 --country ZAF --indicator CPI --type max
Success! Will send a notification when, "South Africa's CPI rises above 110.0".
```

The sentence is `<country>'s | Any countries`, `<indicator> | any indicator`,
`rises above | falls below`, and the threshold rounded to one decimal place with
thousands separators (`1234.56` → `1,234.6`). Two thresholds that round to the same
value are the same alert: after the example above, `ams add 110.04 -c ZAF -i CPI`
exits with `Error! Alert: "South Africa's CPI rises above 110.0" already exists.` The
alert still compares against the exact threshold you first entered.

Adding an alert that was removed exits with an error that names the id to restore:

```text
Error! Alert: "South Africa's CPI rises above 110.0" was previously created and removed.
Type `ams restore 0` to restore this alert, and try again.
```

### `view` — list active alerts

```bash
ams view
```

Prints the visible alerts as `{id: sentence}`, or `No alerts set.`:

```text
{0: "South Africa's CPI rises above 110.0",
 1: 'Any countries GDP falls below 0.0',
 2: "Russia's any indicator rises above 5.0"}
```

The `<alert-id>` that `remove` and `restore` take is this number. It is the alert's
zero-based position among all stored alerts, removed ones included, so ids never shift,
and `view` shows gaps where alerts were removed.

### `remove` — remove an alert

```bash
ams remove <alert-id>
```

Takes the id of a visible alert; any other id exits with
`Error! Alert ID: "<id>" does not exist.` Removing an alert also clears its
notification history.

### `restore` — restore a removed alert

```bash
ams restore <alert-id>
```

Takes the id the alert had before removal (the one `view` showed). Restoring a visible
alert exits with `Error! Alert ID: "<id>" has not been removed.` The restored alert
starts with an empty notification history.

### `status` — show sent notifications

Lists each alert that has fired and the timestamps (UTC) it fired on, or
`No notifications sent.`

```bash
ams status
```

```text
South Africa's CPI rose above 110.0 on:
 - Wednesday, November 04, 2026 12:00:00 PM UTC
```

## How alerts work

Alerts are stored in `~/ams_alerts.pickle`. Removing an alert hides it rather than
deleting it, so it can be restored later, but its notification history is cleared and
does not come back on restore.

Alerts are evaluated every time `ams download` succeeds. An alert matches the download
when its country is the downloaded country or any country, and its indicator is the
downloaded indicator or any indicator. For each visible matching alert, AMS compares
the most recent observed value with the threshold: strictly greater for `max`, strictly
less for `min`. When it is past the threshold, AMS posts a Growl notification titled
"AMS Notification" (e.g. `South Africa's CPI rose above threshold of 110.0`) and
records the timestamp (viewable via `ams status`).

Intended: notify when the value crosses the threshold, once per crossing. Today the
check looks only at the latest value, not at whether it crossed the threshold since
the last run. Every download while the value stays past the threshold notifies again
and records another timestamp. The timestamp is recorded even when Growl isn't
running and no notification is shown.

## Known issues

- The OECD endpoint is gone. As of 2026-11-04,
  `http://stats.oecd.org/SDMX-JSON/data/MEI_ARCHIVE/...` redirects to https and returns
  `404 Not Found`, so every `download` exits with the 404 body in the chosen error
  format and no alert is ever evaluated (`ams:335-349`).
- The `json` error output is a Python dict repr, not JSON (`ams:341`, `ams:349`), and
  the `csv` error row doesn't quote the message, so a message containing commas breaks
  the row (`ams:345-347`).
- `--start`/`--end` crash on a `week` unit (`KeyError`, `ams:181`) and on any two-word
  phrase that doesn't start with `this`, `last` or `next` (`UnboundLocalError`,
  `ams:196-204`).
- The unsupported-frequency error prints the indicator's internal dict instead of its
  name (`ams:310-311`).
- Notifications for an any-country alert read `A countries ...` (e.g.
  `A countries GDP fell below threshold of 0.0`) (`ams:442`, `ams:402`).
- A firing is recorded even when Growl isn't running (`ams:135` vs `ams:405`).
- Growl registration uses `icon of application "euler.app"`, an app AMS doesn't ship
  (`ams:123`).
- `view` and `status` accept `--country`/`-c` and `--indicator`/`-i` (default `CPI`)
  but ignore them (`ams:520-533`, `ams:536-569`).

## License

See repository for license details.
