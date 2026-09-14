# AMS

**A**lert **M**onitoring **S**ystem — a command-line tool to download OECD economic
indicators for the BRICS countries, monitor them against thresholds, and fire
desktop notifications when an indicator crosses a level you care about.

Data is pulled from the [OECD Main Economic Indicators (MEI) archive][mei] via its
SDMX-JSON API. Notifications are delivered through [Growl][growl] on macOS.

[mei]: http://stats.oecd.org/SDMX-JSON/data/MEI_ARCHIVE
[growl]: http://growl.info/

## Requirements

- macOS (notifications use AppleScript + Growl via PyObjC)
- Python 3
- [Growl](http://growl.info/) running for desktop notifications

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

| Name           | Description                              | Frequencies         |
| -------------- | ---------------------------------------- | ------------------- |
| `balance`      | Current Account Balance                  | quarterly           |
| `CPI`          | Consumer Price Index                     | monthly             |
| `GDP`          | GDP Total, constant prices               | quarterly           |
| `industry`     | Industrial Production                    | monthly, quarterly  |
| `exports`      | International Trade in Goods — Exports    | monthly             |
| `imports`      | International Trade in Goods — Imports    | monthly             |
| `construction` | Production in Construction               | monthly, quarterly  |
| `retail`       | Retail Trade Volume                      | monthly, quarterly  |

## Usage

```bash
ams <command> [options]
```

### `download` — fetch indicator data

Downloads data for a country/indicator and prints it. Each download also checks
your active alerts and notifies you if a threshold has been crossed.

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

**Date formats** for `--start` / `--end` accept natural phrases as well as explicit
dates:

- `this month`, `last month`, `next month`, `this year`, `next year`
- `6 months ago`, `3 years ago`
- `5/4/82` (any parseable date)

**Editions** — the OECD releases the previous month's edition on the 15th. `recent`
automatically resolves to last month's edition on or after the 15th, otherwise the
month before.

### `add` — create an alert

Fires a notification (on the next matching `download`) when an indicator rises above
or falls below a threshold.

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

### `view` — list active alerts

```bash
ams view
```

### `remove` — remove an alert

```bash
ams remove <alert-id>
```

### `restore` — restore a removed alert

```bash
ams restore <alert-id>
```

### `status` — show sent notifications

Lists each alert that has fired and the timestamps (UTC) it fired on.

```bash
ams status
```

## How alerts work

Alerts are stored in `~/ams_alerts.pickle`. Removing an alert hides it rather than
deleting it, so it can be restored later. Alerts are evaluated every time you run
`ams download` — when the most recent observed value crosses a threshold, AMS posts a
Growl notification titled "AMS Notification" and records the timestamp (viewable via
`ams status`).

## License

See repository for license details.
