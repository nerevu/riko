# CROO Monthly Status Report Generator

A small data pipeline that pulls project data from [Airtable][airtable], transforms it,
and renders a formatted monthly status report (HTML + PDF) for the CROO Cannabis
Disparity Study.

The primary pipeline renders a Jinja/Markdown template to HTML and then to PDF with a
headless browser. An alternative renderer using the [Carbone][carbone] SDK against a
`.docx` template is also included.

[airtable]: https://airtable.com/
[carbone]: https://carbone.io/

## Pipeline overview

```
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
| 3 | `parseData.js` | Filters, groups, and aggregates both sources into report-ready values → `data/parsedData.json` |
| 4 | `render_jinja.py` | Renders `report.md` through `template.html`, converts Markdown (with Mermaid diagrams) to `report.html`, then prints to `report.pdf` via Playwright |

## Requirements

- Node.js (with `fetch`, i.e. Node 18+)
- Python 3
- [Playwright](https://playwright.dev/python/) with a Chromium browser installed

## Setup

```bash
# Node dependencies
npm install

# Python dependencies
pip install -r requirements.txt

# Playwright browser (used to render the PDF)
playwright install chromium
```

Create a `.env` file in the project root with your Airtable personal access token:

```
AIRTABLE_API_KEY=your_airtable_token_here
```

> **Security note:** the committed `.env` contains a real token. Rotate it and keep
> credentials out of version control.

## Usage

Run the full pipeline:

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

Individual steps can be run on their own during development (e.g. re-run
`render_jinja.py` after editing `report.md` or `template.html` without re-fetching from
Airtable).

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

## Files

| Path | Description |
| ---- | ----------- |
| `gen-report` | Entry-point script that runs the full pipeline |
| `getProjectData.js` / `getResourceData.js` | Airtable fetchers (paginated) |
| `parseData.js` | Data transformation / aggregation |
| `render_jinja.py` | Primary renderer (Jinja + Markdown → HTML → PDF) |
| `report.md` | Report template (Markdown + Jinja) |
| `template.html` | HTML wrapper / styling for the report |
| `render_carbone.py` | Alternative renderer using the Carbone SDK + `croo_template.docx` |
| `renderReport.js` | Alternative Markdown → HTML renderer (markvis/d3) |
| `data/` | Generated JSON artifacts |
| `assets/` | Static assets for the report |
| `CROO Monthly Status Report (YYYY-MM).pdf` | Archived monthly outputs |
