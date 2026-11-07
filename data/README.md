# Data

## Source

- **Dataset:** BC Environmental Monitoring Data System (EnMoDS) Results
- **Publisher:** Government of British Columbia (Environmental Monitoring and Analysis Branch)
- **Licence:** Open Government Licence – British Columbia
- **Catalogue page:** https://catalogue.data.gov.bc.ca/dataset/bc-environmental-monitoring-data-system-results
- **Content:** EnMoDS publishes laboratory and field results for water, air, waste discharge and ambient monitoring sites across BC, including permittee (industry) monitoring. Each row is one result for one parameter from one sample.

## The raw file (not in this repository)

| Item | Value |
|---|---|
| Local path | `data/raw/this_yr.csv` |
| Size | 1,883,073,291 bytes (about 1.9 GB) |
| Rows / columns | 3,092,148 result rows, 67 columns |
| Sample dates | 2024-12-31 to 2026-09-19 |
| Downloaded | September 2026 (file timestamp 2026-09-23) |

**The complete raw file is intentionally excluded from GitHub.** `data/raw/` is listed in `.gitignore`. The file is too large for a normal repository, and it is a frequently refreshed public export that anyone can download.

The raw file was only ever read. It was queried with DuckDB in read-only fashion and never opened in an editor, loaded whole into pandas, or modified. Its size and modification time were checked before and after every processing step.

## What this repository contains

### `selected_monitoring_data.csv` (567 records)

These are all records in the raw file for location `0200097` (EVCC - ELKVIEW (PE425) ERICKSON CREEK AT MOUTH) with one of these parameter codes:

| Code | Parameter | Records |
|---|---|---|
| `1110` | Nitrate (NO3) Dissolved | 138 lab results |
| `TEMF` | Temperature-Field | 159 grab readings and 270 continuous-monitor values |

- It was produced by `scripts/02_extract_selected_subset.py`.
- **Columns:** all 67 original columns, kept as text exactly as exported, plus `source_row_number`. The exception is `Ministry_Contact` and `Field_Visit_Participants`, which hold people's names. They are blanked in this copy and are not used in the analysis.
- **`source_row_number`** is the 1-based data-row position of each record in `this_yr.csv`, header excluded. Spot checks against the raw file matched exactly.
- **Nothing was filtered out at extraction.** QC types, media and collection methods are all kept; deciding what to exclude is a documented QA/QC step in the notebook.

### Column names to note

| Column | Holds |
|---|---|
| `Observed_Property_ID` | readable parameter name |
| `Observed_Property_Name` | EMS parameter code |
| `Observed_Date_Time` | sampling date and time, ISO 8601 with UTC offset (used as the sample date) |
| `Analyzed_Date_Time` | lab analysis date (not used for the time series) |
| `Detection_Condition`, `Method_Detection_Limit`, `Method_Reporting_Limit` | detection information |
| `QC_Type` | `NORMAL`, `REPLICATE` or `BLANK` |
| `Result_Status` / `Result_Grade` | validation status; here all `Preliminary` / `Ungraded` |

## How to obtain the source data

1. Open the catalogue page above.
2. Download the CSV resource for the **current year's results**. The file used here was saved locally as `this_yr.csv`. Resource names and the period they cover may change as the Province updates the dataset.
3. Save it as `data/raw/this_yr.csv`.
4. Run `scripts/01_profile_raw_dataset.py` and `scripts/02_extract_selected_subset.py` from the repository root.

**Results will differ if you download the export on a different date.** It is a rolling current-year file and results may be revised from `Preliminary` status. The committed `selected_monitoring_data.csv` is the exact subset analysed here.

Questions about the data: EnMoDSHelp@gov.bc.ca (Environmental Monitoring and Analysis Branch).
