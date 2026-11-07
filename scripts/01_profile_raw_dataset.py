"""
Phase 2 - Memory-efficient profiling of the raw EnMoDS export.

Reads data/raw/this_yr.csv with DuckDB (read-only; the raw file is never
modified or loaded into pandas). Only the columns needed for profiling are
pulled into a slim in-memory DuckDB table in a single streaming pass, and
all profiling queries run against that table.

Outputs (small CSVs) are written to outputs/profiling/.

Run from the project root:
    python scripts/01_profile_raw_dataset.py
"""

from pathlib import Path
import tempfile
import time

import duckdb
import pandas as pd

RAW_CSV = Path("data/raw/this_yr.csv")
OUT_DIR = Path("outputs/profiling")
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Candidate field/water-quality parameters (matched on the readable parameter
# name, case-insensitive). Printed names are reviewed before any selection.
CANDIDATE_REGEX = (
    r"^ph\b|^ph-field|specific conductance|conductivity|temperature|oxygen|"
    r"turbidity|nitrate|phosphorus"
)
# Names that match the pattern above but are not ambient water-quality
# field/lab parameters of interest (oxygen demand, air temperature, soil
# leachates, % saturation, solid-phase concentrations, TCLP extraction fluid).
EXCLUDE_REGEX = (
    r"oxygen demand|\(air\)|leachable|mass conc|extraction fluid|\(ratio\)"
)
AMBIENT_TYPES = "('River, Stream, or Creek', 'Lake or Pond')"

pd.set_option("display.width", 250)
pd.set_option("display.max_columns", None)
pd.set_option("display.max_colwidth", 45)

con = duckdb.connect()  # in-memory database; nothing written next to the raw file
# Cap RAM use and let DuckDB spill to the system temp folder (outside the repo)
# so the script also works on a laptop with limited memory.
con.execute("SET memory_limit = '1500MB'")
con.execute(f"SET temp_directory = '{Path(tempfile.gettempdir(), 'duckdb_spill').as_posix()}'")
con.execute("SET preserve_insertion_order = false")

t0 = time.time()
# all_varchar avoids type-inference failures on a heterogeneous 67-column export;
# numeric/date casts are done explicitly with TRY_CAST so bad values become NULL
# (and can be counted) instead of stopping the scan.
con.execute(f"""
    CREATE TABLE obs AS
    SELECT
        Location_ID,
        Location_Name,
        Location_Type,
        Medium,
        Sampling_Agency,
        Observed_Property_ID                          AS parameter_name,
        Observed_Property_Name                        AS parameter_code,
        Fraction,
        Result_Value                                  AS result_raw,
        TRY_CAST(Result_Value AS DOUBLE)              AS result_value,
        Result_Unit,
        Detection_Condition,
        Data_Classification,
        Composite_Stat,
        Collection_Method,
        QC_Type,
        Result_Status,
        Observed_Date_Time,
        TRY_CAST(substr(Observed_Date_Time, 1, 10) AS DATE) AS sample_date
    FROM read_csv('{RAW_CSV.as_posix()}', header = true, all_varchar = true)
""")
print(f"Slim table built in {time.time() - t0:.0f} s")


def q(sql):
    return con.execute(sql).df()


def show(title, df, n=None):
    print(f"\n=== {title} ===")
    print((df if n is None else df.head(n)).to_string(index=False))


# ---------------------------------------------------------------- overview
overview = q("""
    SELECT COUNT(*)                                        AS total_rows,
           COUNT(DISTINCT Location_ID)                     AS locations,
           COUNT(DISTINCT parameter_name)                  AS parameters,
           MIN(sample_date)                                AS first_sample_date,
           MAX(sample_date)                                AS last_sample_date,
           SUM(CASE WHEN Observed_Date_Time IS NULL THEN 1 ELSE 0 END) AS missing_dates,
           SUM(CASE WHEN Observed_Date_Time IS NOT NULL AND sample_date IS NULL
                    THEN 1 ELSE 0 END)                     AS unparseable_dates,
           SUM(CASE WHEN result_raw IS NULL THEN 1 ELSE 0 END) AS missing_results,
           SUM(CASE WHEN result_raw IS NOT NULL AND result_value IS NULL
                    THEN 1 ELSE 0 END)                     AS non_numeric_results
    FROM obs
""")
show("Overview", overview)
overview.to_csv(OUT_DIR / "00_overview.csv", index=False)

by_year = q("""SELECT year(sample_date) AS year, COUNT(*) AS n
               FROM obs GROUP BY 1 ORDER BY 1""")
show("Rows by sample year", by_year)

# ---------------------------------------------------------- categorical counts
for col in ["Medium", "Data_Classification", "QC_Type",
            "Result_Status", "Detection_Condition"]:
    df = q(f"""SELECT {col}, COUNT(*) AS n,
                      ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct
               FROM obs GROUP BY 1 ORDER BY n DESC""")
    show(f"Counts by {col}", df)
    df.to_csv(OUT_DIR / f"01_counts_by_{col.lower()}.csv", index=False)

# ------------------------------------------------------------ top parameters
def top_params(where="TRUE", n=25):
    return q(f"""
        SELECT parameter_name, parameter_code,
               COUNT(*)                     AS n_obs,
               COUNT(DISTINCT Location_ID)  AS n_locations,
               string_agg(DISTINCT Result_Unit, ' | ') AS units
        FROM obs WHERE {where}
        GROUP BY 1, 2 ORDER BY n_obs DESC LIMIT {n}
    """)

for label, where in [("overall", "TRUE"),
                     ("water_fresh", "Medium = 'Water - Fresh'"),
                     ("water_waste", "Medium = 'Water - Waste'")]:
    df = top_params(where)
    show(f"Top parameters - {label}", df)
    df.to_csv(OUT_DIR / f"02_top_parameters_{label}.csv", index=False)

cand_names = q(f"""
    SELECT Medium, parameter_name, parameter_code, COUNT(*) AS n_obs,
           string_agg(DISTINCT Result_Unit, ' | ') AS units
    FROM obs
    WHERE Medium IN ('Water - Fresh', 'Water - Waste')
      AND regexp_matches(lower(parameter_name), '{CANDIDATE_REGEX}')
    GROUP BY 1, 2, 3 ORDER BY 1, n_obs DESC
""")
show("Candidate parameter names found (fresh & waste water)", cand_names)
cand_names.to_csv(OUT_DIR / "03_candidate_parameter_names.csv", index=False)

# --------------------------------------------------- site x parameter profile
site_param = q(f"""
    SELECT
        CASE WHEN Medium = 'Water - Waste' THEN 'Wastewater / effluent'
             WHEN Location_Type IN {AMBIENT_TYPES} THEN 'Ambient freshwater (river / lake)'
             ELSE 'Other freshwater (in-plant, storage, etc.)' END AS candidate_group,
        Location_ID,
        any_value(Location_Name)                          AS Location_Name,
        any_value(Location_Type)                          AS Location_Type,
        mode(Sampling_Agency)                             AS main_sampling_agency,
        parameter_name,
        parameter_code,
        COUNT(*)                                          AS n_obs,
        COUNT(DISTINCT sample_date)                       AS n_distinct_dates,
        COUNT(DISTINCT date_trunc('month', sample_date))  AS n_distinct_months,
        MIN(sample_date)                                  AS first_date,
        MAX(sample_date)                                  AS last_date,
        date_diff('day', MIN(sample_date), MAX(sample_date)) AS span_days,
        string_agg(DISTINCT Result_Unit, ' | ')           AS result_units,
        COUNT(DISTINCT Result_Unit)                       AS n_units,
        ROUND(AVG(CASE WHEN Detection_Condition = 'NOT_DETECTED' THEN 1 ELSE 0 END), 3)
                                                          AS nondetect_share,
        ROUND(AVG(CASE WHEN result_value IS NULL THEN 1 ELSE 0 END), 3)
                                                          AS missing_result_share,
        string_agg(DISTINCT Data_Classification, ' | ')   AS data_classifications,
        mode(Data_Classification)                         AS main_classification,
        ROUND(AVG(CASE WHEN Data_Classification = 'FIELD_RESULT' THEN 1 ELSE 0 END), 3)
                                                          AS field_result_share,
        ROUND(AVG(CASE WHEN Data_Classification = 'LAB' THEN 1 ELSE 0 END), 3)
                                                          AS lab_share,
        ROUND(AVG(CASE WHEN QC_Type = 'NORMAL' THEN 1 ELSE 0 END), 3)
                                                          AS normal_qc_share,
        ROUND(AVG(CASE WHEN Composite_Stat IS NOT NULL THEN 1 ELSE 0 END), 3)
                                                          AS composite_stat_share,
        mode(Collection_Method)                           AS main_collection_method,
        ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT sample_date), 2) AS obs_per_date,
        ROUND(MIN(result_value), 4)                       AS min_value,
        ROUND(median(result_value), 4)                    AS median_value,
        ROUND(MAX(result_value), 4)                       AS max_value
    FROM obs
    WHERE Medium IN ('Water - Fresh', 'Water - Waste')
      AND regexp_matches(lower(parameter_name), '{CANDIDATE_REGEX}')
      AND NOT regexp_matches(lower(parameter_name), '{EXCLUDE_REGEX}')
    GROUP BY candidate_group, Location_ID, parameter_name, parameter_code
    HAVING COUNT(DISTINCT sample_date) >= 12
    ORDER BY candidate_group, n_distinct_dates DESC
""")
site_param["primary_source"] = site_param["field_result_share"].map(
    lambda s: "FIELD_RESULT" if s >= 0.5 else "LAB")
site_param.to_csv(OUT_DIR / "04_site_parameter_profile.csv", index=False)
print(f"\nSite x parameter pairs with >= 12 distinct dates: {len(site_param)}")

cols = ["Location_ID", "Location_Name", "Location_Type", "parameter_name",
        "parameter_code", "n_obs", "n_distinct_dates", "n_distinct_months",
        "first_date", "last_date", "result_units", "nondetect_share",
        "primary_source", "normal_qc_share", "median_value"]
for grp, df in site_param.groupby("candidate_group"):
    show(f"Top site x parameter pairs - {grp}", df[cols], n=40)

# --------------------------------------------------------------- shortlist
# Transparent screening rules for a clear single-site time series:
#   one reporting unit, <= 5 % non-detects, >= 95 % NORMAL (non-QC) samples,
#   >= 15 distinct sampling months, >= 50 distinct sampling dates.
screen = site_param[
    (site_param["n_units"] == 1)
    & (site_param["nondetect_share"] <= 0.05)
    & (site_param["normal_qc_share"] >= 0.95)
    & (site_param["n_distinct_months"] >= 15)
    & (site_param["n_distinct_dates"] >= 50)
].sort_values(["candidate_group", "n_distinct_dates"], ascending=[True, False])
screen.to_csv(OUT_DIR / "05_screened_candidates.csv", index=False)
cols2 = cols + ["obs_per_date", "composite_stat_share", "main_collection_method",
                "min_value", "max_value"]
for grp, df in screen.groupby("candidate_group"):
    show(f"Screened candidates - {grp} ({len(df)} pairs)", df[cols2], n=30)

print(f"\nDone in {time.time() - t0:.0f} s. CSVs written to {OUT_DIR}/")
