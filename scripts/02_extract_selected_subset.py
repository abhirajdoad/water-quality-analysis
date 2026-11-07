"""
Phase 3 - Extract the analysis subset from the raw EnMoDS export.

Selected monitoring location : 0200097 - EVCC - ELKVIEW (PE425) ERICKSON CREEK AT MOUTH
Primary parameter            : Nitrate (NO3) Dissolved  (EMS code 1110)
Supporting parameter         : Temperature-Field        (EMS code TEMF)

DuckDB streams data/raw/this_yr.csv (read-only) and writes only the matching
rows to data/selected_monitoring_data.csv. Every original column is kept
unchanged (read as text so nothing is re-formatted), and a
`source_row_number` column is added: the 1-based data-row position of the
record in the raw file (header excluded), so each extracted record can be
traced back to the source. The two columns that hold people's names
(Ministry_Contact, Field_Visit_Participants) are blanked; they are not used
in the analysis.

All QC types (NORMAL, REPLICATE, BLANK) and all media are kept on purpose:
deciding what to exclude or flag is a QA/QC decision made later, not here.

Run from the project root:
    python scripts/02_extract_selected_subset.py
"""

from pathlib import Path
import tempfile

import duckdb

RAW_CSV = Path("data/raw/this_yr.csv")
OUT_CSV = Path("data/selected_monitoring_data.csv")

LOCATION_ID = "0200097"
PARAMETER_CODES = ("1110", "TEMF")   # Observed_Property_Name holds the EMS code

con = duckdb.connect()
con.execute("SET memory_limit = '1500MB'")
con.execute(f"SET temp_directory = '{Path(tempfile.gettempdir(), 'duckdb_spill').as_posix()}'")
# Keep file order so row_number() matches the row's position in the raw CSV.
con.execute("SET preserve_insertion_order = true")

codes_sql = ", ".join(f"'{c}'" for c in PARAMETER_CODES)

con.execute(f"""
    COPY (
        WITH raw AS (
            SELECT row_number() OVER () AS source_row_number, *
            FROM read_csv('{RAW_CSV.as_posix()}', header = true, all_varchar = true)
        )
        -- Personal names are blanked before the subset is saved for publication.
        SELECT * REPLACE (NULL::VARCHAR AS Ministry_Contact,
                          NULL::VARCHAR AS Field_Visit_Participants)
        FROM raw
        WHERE Location_ID = '{LOCATION_ID}'
          AND Observed_Property_Name IN ({codes_sql})
        ORDER BY Observed_Property_Name, Observed_Date_Time, source_row_number
    ) TO '{OUT_CSV.as_posix()}' (HEADER, DELIMITER ',')
""")

n = con.execute(f"SELECT COUNT(*) FROM read_csv('{OUT_CSV.as_posix()}', all_varchar = true)").fetchone()[0]
print(f"Wrote {n} records to {OUT_CSV}")
