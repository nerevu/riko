---
source: ../../../../carbone/README.md
---

# CROO Monthly Status Report Generator

A small data pipeline that pulls project data from [Airtable][airtable], transforms it,
and renders a formatted monthly status report (HTML + PDF) for the CROO Cannabis
Disparity Study.

The pipeline renders a Jinja/Markdown template to HTML and then to PDF with a headless
browser. The folder also holds `render_carbone.py`, an unfinished spike toward rendering
a `.docx` template with the [Carbone][carbone] SDK. It does not work: it raises
`NameError` on `getenv` before rendering, and it only ever renders a hardcoded
placeholder dict, never the pipeline's data (see [Known issues](#known-issues)).

[airtable]: https://airtable.com/
[carbone]: https://carbone.io/

## Pipeline overview

```text
Airtable ──► getProjectData.js  ──► data/projectData.json  ┐
         └─► getResourceData.js ──► data/resourceData.json ─┤
                                                            ▼
                                    parseData.js ──► data/parsedData.json
                                                            ▼
                          render_jinja.py (report.md + template.html)
                                                            ▼
                                          report.html ──► report.pdf
```

| Step | Script | Output |
| ---- | ------ | ------ |
| 1 | `getProjectData.js` | Fetches the project Airtable base (Tasks, Projects, Change Requests, Issues, Studies) → `data/projectData.json` |
| 2 | `getResourceData.js` | Fetches the resource Airtable base (Status Reports, Meetings, Data requests, Metrics, Organizations, Engagements, Assets) → `data/resourceData.json` |
| 3 | `parseData.js` | Filters, groups, and aggregates both sources into report-ready values → `data/parsedData.json` (see [Data](#data)) |
| 4 | `render_jinja.py` | Renders `report.md` through `template.html`, converts Markdown (with Mermaid diagrams) to `report.html`, then prints to `report.pdf` via Playwright |

Every stage overwrites one fixed file with `writeFileSync` / `open(..., 'w')`
(`getProjectData.js:58`, `getResourceData.js:60`, `parseData.js:142`,
`render_jinja.py:47-65`); nothing is appended or kept per month. Only the latest
snapshot exists, so a past month cannot be regenerated from stored data: re-running
the fetchers returns Airtable's current state. The archived
`CROO Monthly Status Report (YYYY-MM).pdf` files are copies of `report.pdf` renamed by
hand; no script writes them.

## Requirements

- Node.js (with `fetch`, i.e. Node 18+)
- Python 3
- [Playwright](https://playwright.dev/python/) with a Chromium browser installed

## Setup

```bash
# Node dependencies (also provides the Mermaid, Bootstrap and CSS files
# that template.html loads from ./node_modules)
npm install

# Python dependencies
pip install -r requirements.txt

# Not in requirements.txt, but imported by render_jinja.py
pip install beautifulsoup4 playwright

# Playwright browser (used to render the PDF)
playwright install chromium
```

`requirements.txt` lists only `carbone-sdk`, `requests`, `pymdown-extensions`,
`Jinja2` and `prettierfier`. `render_jinja.py` also imports `bs4` and `playwright`
(`render_jinja.py:10-11`), and `markdown` (`render_jinja.py:5`), which is not listed
directly. The `playwright` command exists only after the `playwright` package is
installed. `render_carbone.py` additionally imports `meza` (`render_carbone.py:10`),
which is also not listed.

Create a `.env` file in the project root with your Airtable personal access token:

```text
AIRTABLE_API_KEY=your_airtable_token_here
```

> **Security note:** the committed `.env` contains a real token. Rotate it and keep
> credentials out of version control. `render_carbone.py:4` also embeds a Carbone
> test token.

## Configuration

Only the Airtable token comes from the environment. Everything else is fixed in the
code.

| Setting | Value | Where |
| ------- | ----- | ----- |
| `AIRTABLE_API_KEY` | read from `.env` in the current directory | `getProjectData.js:1-8`, `getResourceData.js:1-8` |
| Project base ID | `app2GAJwBsEY4NVLK` | `getProjectData.js:7` |
| Project tables | Tasks, Projects, Change Requests, Issues, Studies | `getProjectData.js:11-17` |
| Resource base ID | `app5EOPEp9w8oFRkQ` | `getResourceData.js:7` |
| Resource tables | Status Reports, Meetings, Data requests, Metrics, Organizations, Engagements, Assets | `getResourceData.js:11-19` |
| Project record | `Name == "Cannabis Disparity Study"` | `parseData.js:67` |
| PDF preview URL | `http://localhost:8000/report.html` | `render_jinja.py:56` |
| Output paths | `data/projectData.json`, `data/resourceData.json`, `data/parsedData.json`, `report.html`, `report.pdf` | `getProjectData.js:9`, `getResourceData.js:9`, `parseData.js:6`, `render_jinja.py:16-18` |

All paths are relative, so run every script from the project root. The fetchers
follow Airtable's `offset` pagination until no offset is returned.

## Usage

Run the full pipeline from the project root:

```bash
./gen-report
```

This runs, in order:

```bash
node ./getProjectData.js    # fetch project base
node ./getResourceData.js   # fetch resource base
node ./parseData.js         # transform into parsedData.json
python ./render_jinja.py    # render report.html + report.pdf
```

`gen-report` does not stop on a failed step (it sets `-u` and `pipefail`, not `-e`),
so a later step can render whatever stale files the earlier steps left behind.

Individual steps can be run on their own during development (e.g. re-run
`render_jinja.py` after editing `report.md` or `template.html` without re-fetching from
Airtable).

### Rendering the Mermaid charts into the PDF

`template.html` draws the charts in the browser, importing Mermaid as an ES module from
`./node_modules/mermaid/...` (`template.html:30-31`). `render_jinja.py` first opens
`http://localhost:8000/report.html` and waits up to 5 seconds for an `svg` element
before printing (`render_jinja.py:56`, `:62`). Only if that request fails does it print
"No server running, opening file directly!" and load `report.html` from a `file://`
URL, printing the PDF without waiting for the charts (`render_jinja.py:57-60`).

To get the charts reliably, serve the project root on port 8000 in another terminal
before running `render_jinja.py`:

```bash
python3 -m http.server 8000
```

## Data

### Fields

`data/parsedData.json` is the contract between `parseData.js` and the render stage.
`report.md` and `template.html` read these keys (`parseData.js:94-139`):

| Key | Type | Value |
| --- | ---- | ----- |
| `statusReport` | object | The full Airtable `fields` of the latest Status Report (see below) |
| `meetings` | list | `Date`, `Status Report Notes` of the reporting month's meetings, sorted by `Date` |
| `totalDataSourceCount` | int | Number of Metrics records |
| `openDataRequests` | list | `Metric Name`, `Singular Owner`, `License Type Array`, `Status`, `Urgent`, `Notes` of open data requests |
| `openDataRequestCount` | int | Length of `openDataRequests` |
| `flaggedDataRequestCount` | int | Data requests with `Flagged Open Requests == 1` |
| `receivedDataCount` | int | Data requests with `Received Data == 1` |
| `dataRequestChartData` | object | Count of all data requests per `Status` |
| `interviewChartData` | object | Count of interviews per `Status` |
| `totalContactedCount` … `totalCodedCount` | int | Cumulative interview funnel (five keys: Contacted, Scheduled, Engaged, Transcribed, Coded) |
| `interviews` | list | `Contact Name`, `Stakeholder`, `Status`, sorted by `Contact Name` |
| `outreachChartData` | object | Count of stakeholders per `Status` |
| `stakeholders` | list | `Name`, `Type`, `Status` of stakeholders |
| `cases` | list | `Name`, `Author`, `Described`, `Reviewed`, `License Type Array` of litigation assets, sorted by `Name` |
| `totalCaseCount` | int | Number of litigation assets |
| `describedCaseCount` | int | Cases with `Described == 1` |
| `reviewedCaseCount` | int | Cases with `Reviewed == 1` |
| `taskPercentComplete` | string | Project `Percent Complete` × 100, as `"NN%"` |
| `taskPercentCompleteOrProgress` | string | Project `Percent Complete or In progress` × 100, as `"NN%"` |
| `remainingTaskCount` | int | Project `Unfinished Task Count` |
| `remainingWorkDays` | int | Project `Days Remaining` |
| `taskChartData` | list | `Study`, `Unfinshed Task Count` per Studies record |
| `issues` | list | `Name`, `Issue Type`, `Status` of every issue |
| `openIssueCount` | int | Issues with `Open == 1` |
| `changeRequests` | list | `Name`, `Description`, `License Type Array` of every change request |
| `openChangeRequestCount` | int | Project `Open Change Request Count` |

`Unfinshed Task Count` (sic) is the Studies field name as both `parseData.js:53` and
`report.md:48` spell it. `Metric Name`, `Singular Owner`, `Contact Name` and
`Stakeholder` are Airtable linked-record arrays; `report.md` shows their first element
(`report.md:118`, `:190`).

`statusReport` passes through every field of the Status Report record. The templates
read `Period Ending` (`template.html:26`); `Progress Towards Milestones`,
`Specific Activities Completed`, `Description of Tools Utilized` and `Ongoing Analysis`
(`report.md:17-29`); and `Data`, `Legal` and `Outreach` × `Outstanding` / `Noteworthy` /
`Next Steps` (`report.md:78-80`, `:130-132`, `:153-155`).

## Report content

`parseData.js` computes the sections that appear in the report, including:

- **Tasks** — percent complete, remaining tasks and work days, per-study progress
- **Data requests** — open / flagged / received counts and status breakdown
- **Interviews** — funnel counts (contacted → scheduled → engaged → transcribed → coded)
- **Stakeholders** — outreach status breakdown
- **Litigation** — case counts (described / reviewed)
- **Issues** and **Change requests** — open counts and details
- **Meetings** — status-report notes for the reporting month

The reporting month is derived from the most recent **Status Report** record's
"Period Ending" date.

### Derivation rules

All filters are equality tests on Airtable field values (`parseData.js:12-14`).

- **Project** — the first Projects record with `Name == "Cannabis Disparity Study"`;
  the name is hardcoded (`parseData.js:67`).
- **Status report** — the Status Reports record with the latest `Period Ending`
  (`parseData.js:68`).
- **Reporting month** — the year and month of that `Period Ending` in local time
  (`parseData.js:69-72`).
- **Meetings** — Meetings with `Has Status Report Notes == 1` whose `Date` falls in the
  reporting month (`parseData.js:65`, `:74-79`). Both dates are date-only strings that
  JavaScript parses as UTC midnight and then compares by local year/month, so west of
  UTC a meeting dated the 1st counts toward the previous month.
- **Open data requests** — Data requests with `Status == "2. Requested"`
  (`parseData.js:57`). Flagged and received counts come from the 0/1 fields
  `Flagged Open Requests` and `Received Data` (`parseData.js:102-103`).
- **Stakeholders** — Organizations with `Stakeholder == 1` (`parseData.js:58`).
- **Interviews** — Engagements with `Engagement == "Interview"` (`parseData.js:59`).
- **Interview funnel** — cumulative: each total includes every later stage, so
  contacted = contacted + scheduled + engaged + transcribed + coded. It keys on the
  exact status labels `"1. Contacted"`, `"2. Scheduled"`, `"3. Engaged"`,
  `"4. Transcribed"` and `"5. Coded"`; interviews with any other status appear in
  `interviewChartData` and `interviews` but not in the totals (`parseData.js:87-91`).
- **Litigation** — Assets with `Category == "Litigation"` (`parseData.js:63`);
  described/reviewed are `Described == 1` / `Reviewed == 1` (`parseData.js:122-123`).
- **Issues** — open issues are those with `Open == 1` (`parseData.js:134`).
- **Rollups** — task percentages, remaining tasks, remaining work days and open change
  requests are read from the project record's Airtable rollup fields, not computed
  (`parseData.js:81-82`, `:126-129`, `:138`).
- **Data sources** — `totalDataSourceCount` is the number of Metrics records
  (`parseData.js:97`).
- **Chart labels** — the data-request chart shows only the statuses `"1. Considering"`
  through `"6. Analyzed"`, and the interview chart only `"1. Contacted"` through
  `"5. Coded"`, each defaulting to 0 (`report.md:94-110`, `:170-183`).

## Files

| Path | Description |
| ---- | ----------- |
| `gen-report` | Entry-point script that runs the full pipeline |
| `getProjectData.js` / `getResourceData.js` | Airtable fetchers (paginated) |
| `parseData.js` | Data transformation / aggregation |
| `render_jinja.py` | Renderer (Jinja + Markdown → HTML → PDF) |
| `report.md` | Report template (Markdown + Jinja) |
| `template.html` | HTML wrapper / styling for the report |
| `render_carbone.py` | Non-working spike: would render a hardcoded placeholder dict (`render_carbone.py:26-31`) into `croo_template.docx` via the Carbone SDK; does not read `data/parsedData.json` and is not run by `gen-report`. Its Airtable `BASE_URL` (a different base) is never used |
| `croo_template.docx` | `.docx` template for `render_carbone.py` |
| `renderReport.js` | Experimental markdown-it/markvis renderer: renders `report.md` as plain Markdown, without Jinja or any data, and overwrites `report.html` (`renderReport.js:6-14`) |
| `test.js` | Stub that reads the two data files and logs `test` |
| `data/` | Generated JSON artifacts (overwritten on every run) |
| `assets/` | Static assets for the report |
| `CROO Monthly Status Report (YYYY-MM).pdf` | Archived monthly outputs (2023-03 to 2023-09), copied from `report.pdf` and renamed by hand |

## Known issues

- `render_carbone.py` raises `NameError: name 'getenv' is not defined` at import: line
  24 calls `BearerAuth(env="AIRTABLE_API_KEY")`, whose `__init__` calls `getenv`, which
  is never imported (`render_carbone.py:18`, `:24`).
- The fetchers never detect an Airtable error: they test `res.error`, which a `fetch`
  `Response` does not have (`getProjectData.js:36`, `getResourceData.js:38`). An error
  body has no `records`, so the table is saved as `[null]`, and `parseData.js` then
  raises `TypeError` reading `item.fields` (`parseData.js:13`).
- `gen-report` runs without `-e` (`gen-report:1`), so a failed fetch or parse does not
  stop `render_jinja.py` from rendering the previous run's data.
- With a server on port 8000, `render_jinja.py` raises an uncaught Playwright timeout
  if no `svg` appears within 5 seconds, and no PDF is written (`render_jinja.py:62`).
- With no server, the PDF is printed from `file://` without waiting for the Mermaid
  charts (`render_jinja.py:57-60`).
- `parseData.js` raises `TypeError` if no Projects record is named
  "Cannabis Disparity Study" (`parseData.js:67`, `:81`) or if Status Reports is empty
  (`parseData.js:68`).
- `node renderReport.js` overwrites `report.html` with output that has unrendered
  Jinja tags (`renderReport.js:14`).
