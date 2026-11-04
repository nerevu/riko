---
source: ../../../../HDX/wfp/README.md
---

# WFP Geo

This repository contains code to modify the geographic files from the WFP VAM.
It also holds static page mockups and WFP VAM data exports for a food security
visualization.

## Contents

- `convert.sh`: converts the GAUL 2013 admin-boundary shapefiles to GeoJSON
  and simplifies them (see below).
- `data/ADM_00_gaul2013.json`, `data/ADM_01_gaul2013.json`,
  `data/ADM_02_gaul2013.json`: GeoJSON admin boundaries at levels 0
  (country), 1 and 2.
- `wfp_mockup_basic.html`, `wfp_mockup_dropdown.html`,
  `wfp_mockup_spinner.html`, `wfp_mockup_years.html`,
  `wfp_mockup_us_years.html`: static HTML mockups. Charts and maps are
  placeholder PNG images (`fcs.png`, `fcs_region.png`, `fcs_year.png`,
  `dh2014-world-dist-mod.png`, `us.png`). jQuery, Bootstrap JS and Font
  Awesome load from CDNs; styling comes from `wfp-theme.css`.
- `wfp-theme.less` / `wfp-theme.css`: Bootstrap 3.3.4 theme based on the
  Pingendo default theme, used by the mockups.
- `screenshots/`: PNG screenshots of each mockup.
- `wfp.numbers`: Apple Numbers workbook.
- `FCS_CSI_Viz_1.pdf`: one-page hand-drawn sketch of the planned Food
  Consumption Score (FCS) and reduced Coping Strategies Index (rCSI)
  visualizations.
- `dh2014-world-dist.png`: not referenced by any mockup.

### WFP VAM data exports

Each file starts with a header row. Location columns are `ADM0_NAME`,
`ADM1_NAME` and `ADM2_NAME`. The files are not UTF-8 encoded.

- `dbo_CopingStrategiesIndexes.csv` (Coping Strategies Index): `ADM0_NAME`,
  `ADM1_NAME`, `ADM2_NAME`, `CSI_rMean`, `CSI_rNoCoping`, `CSI_rLowCoping`,
  `CSI_rMediumCoping`, `CSI_rHighCoping`, `Target_Group`, `CSI_rMonth`,
  `CSI_rYear`, `Methodology`, `CSI_rLowMediumThreshold`,
  `CSI_rMediumHighThreshold`, `CSI_rDataSource`, `Indicator_Type`
- `dbo_FoodConsumptionScores.csv` (Food Consumption Scores): `ADM0_NAME`,
  `ADM1_NAME`, `ADM2_NAME`, `FCS_Mean`, `FCS_poor`, `FCS_Borderline`,
  `FCS_Acceptable`, `Target_Group`, `FCS_Month`, `FCS_Year`, `Methodology`,
  `FCS_LowerThreshold`, `FCS_UpperThreshold`, `FCS_DataSource`,
  `Indicator_Type`
- `dbo_Incomes.csv` (Incomes): `ADM0_NAME`, `ADM1_NAME`, `ADM2_NAME`,
  `Income_Category`, `Income_SubCategory`, `Income_Month`, `Income_Year`,
  `IncomeValue`, `Indicator_Type`, `Income_DataSource`

#### convert.sh

Requirements: GDAL (`ogr2ogr`) and [mapshaper](https://github.com/mbloch/mapshaper).

Inputs: `data/ADM_00_gaul2013.shp`, `data/ADM_01_gaul2013.shp` and
`data/ADM_02_gaul2013.shp`. These shapefiles are **not** in this repository;
`data/` holds only the converted `ADM_0*_gaul2013.json` files.

Run it from this directory, after creating the output directory:

```bash
mkdir -p data/geojson
bash convert.sh
```

The script does two separate things to each shapefile:

1. `ogr2ogr` reprojects it to `crs:84` (WGS 84 longitude/latitude) and
   writes `data/geojson/adm0.geojson`, `adm1.geojson` and `adm2.geojson`.
   `data/geojson/` must already exist.
2. `mapshaper` simplifies the original shapefile (not the `ogr2ogr` output)
   with `-simplify 0.1%` and writes GeoJSON. No output path is given, so
   mapshaper uses its default file name (the input name with a `.json`
   extension, e.g. `ADM_00_gaul2013.json`). The output does not go to
   `data/geojson/`.
