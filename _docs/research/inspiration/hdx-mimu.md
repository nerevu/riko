---
source: ../../../../HDX/mimu/README.md
---

# mimu

A Node CLI that downloads the MIMU Myanmar 3W dashboard data and writes it as CSV. Also
holds saved copies of the dashboard and data from July 2015.

## Install

There is no `package.json`. Install the modules that `mimu` loads with `require()`
(`http`, `vm` and `fs` are Node built-ins):

```bash
cd mimu
npm install commander concat-stream async math
```

## Usage

```bash
./mimu out.csv          # write CSV to out.csv
./mimu out.csv -t 100   # keep only the first 100 rows
./mimu                  # no file: print CSV to stdout
```

- `<file>`: output path. When given, the file is overwritten and
  `MIMU 3W saved to <file>!` is printed.
- `-t, --truncate <n>`: keep only the first `abs(n)` rows. This is applied after the
  expansion described below.

## What it does

1. Downloads `http://data.themimu.info/3w-dashboard/js/data_3w.js` and `.../data_ref.js`
   over plain HTTP and runs them with `vm.runInThisContext`. This defines the
   `data_3w_*` and `data_ref_*` globals.
2. "Decrypts" them the same way the dashboard does:
   - Each `data_3w_base` row is repeated `data_3w_multiply[z]` times, so identical rows
     are expected.
   - Index columns are looked up in `data_ref_orgniz`, `data_ref_sector`,
     `data_ref_status`, `data_ref_ts` and `data_ref_stareg`.
   - A row whose state/region is `Countrywide` becomes one row per entry of
     `data_ref_stareg` except the last, with `Township` left blank.
3. Writes the CSV header `Organization,SectorCluster,Status,Township,StateRegion`. Every
   value is wrapped in double quotes, and quotes inside values are not escaped.
   `Township` and `StateRegion` are MIMU pcodes (e.g. `MMR012017`, `MMR012`), not names.

## Other files

- `Myanmar 3w.csv`: quoted CSV in the CLI's format (109,542 lines).
- `Myanmar - 3W Dashboard.html` and `Myanmar - 3W Dashboard Orig.html`, each with its
  `_files/` folder: saved copies of the MIMU "Myanmar - 3W Dashboard" page. The page is
  built with jQuery, Bootstrap, d3, crossfilter and dc.js. Both copies contain charts by
  sector, status and state/region. The `Orig` copy also logs each asset load to the
  console (`onload` hooks). The bundled `data_3w.js`, `data_ref.js` and `data_cw.js` are
  the same in both folders.
- `Myanmar_data.html`: a browser prototype of the same decryption. It loads the saved
  `data_3w.js`/`data_ref.js` and prints the first 6 rows to the console, with extra
  debug logging for one organisation/sector.
- `data/`:
  - `Myanmar 3w.csv`: unquoted CSV with the same columns (109,628 lines). It differs
    from the top-level file.
  - `Myanmar 3w small.csv`: the same columns, with CR-only line endings.
  - `Myanmar_adm1.geojson`: 15 features (`ST`, `ST_PCODE`, ...).
  - `Myanmar_adm2.geojson`: 332 township features (`TS_PCODE`, `dt_pcode`, ...).
  - `BaselineData_MIMU_Jun2015.xlsm`: an Excel workbook.

## Known issues

- Fetch errors are ignored. If the MIMU URLs no longer serve these scripts, the CLI
  crashes instead of reporting the error.
