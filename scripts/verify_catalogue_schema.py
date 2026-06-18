"""
One-off verification of the value-stream catalogue schema and relationships.

Run this directly (python scripts/verify_catalogue_schema.py) or paste into a notebook cell.
It connects straight to the database (no HTTP gateway) and answers, against live data:

  1. Does the junction's capability_id point at L3 or L2?  (the one open assumption)
  2. Does the full vs -> vss -> l3 -> l2 chain join end to end?
  3. Does the stage table really have no value_stream_id (so the junction is the only link)?
  4. Row counts per table (sanity).

Fill in CONNECTION below with the SAME driver/URL your
infrastructure/database/connection.py uses (sync form). Do not commit real credentials.
"""

from sqlalchemy import create_engine, text

# --------------------------------------------------------------------------- #
# CONNECTION — fill these in (use the same backend as connection.py)          #
# --------------------------------------------------------------------------- #
# Easiest: paste a full SQLAlchemy URL here and leave the discrete params blank.
SQLALCHEMY_URL = ""

# ...or fill these and the URL is built for you (Azure SQL / MSSQL via pyodbc).
SERVER = "your-server.database.windows.net"
DATABASE = "your-database"
USERNAME = "your-username"
PASSWORD = "your-password"
PORT = 1433
ODBC_DRIVER = "ODBC Driver 18 for SQL Server"

SCHEMA = "idp_impact_analyis"  # note: this is the real (misspelled) schema name

# Example URLs for other backends, if that's what connection.py uses:
#   pymssql:    mssql+pymssql://USER:PASS@SERVER:1433/DATABASE
#   databricks: databricks://token:<token>@<host>?http_path=<path>&catalog=<cat>&schema=<schema>
# --------------------------------------------------------------------------- #


def build_url() -> str:
    if SQLALCHEMY_URL:
        return SQLALCHEMY_URL
    from urllib.parse import quote_plus

    odbc = (
        f"DRIVER={{{ODBC_DRIVER}}};SERVER={SERVER},{PORT};DATABASE={DATABASE};"
        f"UID={USERNAME};PWD={PASSWORD};Encrypt=yes;TrustServerCertificate=no;"
        f"Connection Timeout=30;"
    )
    return f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}"


def show(engine, label: str, sql: str) -> None:
    """Run one query and print its columns and rows."""
    print("\n" + "=" * 90)
    print(label)
    print("-" * 90)
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        cols = list(result.keys())
        rows = result.fetchall()
    print(" | ".join(cols))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    print(f"({len(rows)} row(s))")


def main() -> None:
    engine = create_engine(build_url())

    # 1. Is the junction's capability_id an L3 id or an L2 id?
    show(
        engine,
        "1. capability_id -> L3 or L2?  (matches_l3 ~ total_rows means it's L3)",
        f"""
        SELECT
          COUNT(*) AS total_rows,
          SUM(CASE WHEN capability_id IN
                (SELECT l3_capability_id FROM {SCHEMA}.idp_sightline_l3_capabilities)
              THEN 1 ELSE 0 END) AS matches_l3,
          SUM(CASE WHEN capability_id IN
                (SELECT l2_capability_id FROM {SCHEMA}.idp_sightline_l2_capabilities)
              THEN 1 ELSE 0 END) AS matches_l2
        FROM {SCHEMA}.idp_sightline_value_stream_capability
        """,
    )

    # 2. Full chain: junction -> L3 (on capability_id) -> L2 (on L3.parent_capability_id).
    #    If this returns rows, capability_id->L3 and L3->L2 both hold.
    show(
        engine,
        "2. Live vs -> stage -> L3 -> L2 chain (sample)",
        f"""
        SELECT TOP 20
          j.value_stream_id,
          j.value_stream_stage_id,
          l3.l3_capability_id,
          l3.capability_name        AS l3_name,
          l3.parent_capability_id   AS l2_id,
          l2.capability_name        AS l2_name
        FROM {SCHEMA}.idp_sightline_value_stream_capability j
        JOIN {SCHEMA}.idp_sightline_l3_capabilities l3
          ON l3.l3_capability_id = j.capability_id
        LEFT JOIN {SCHEMA}.idp_sightline_l2_capabilities l2
          ON l2.l2_capability_id = l3.parent_capability_id
        ORDER BY j.value_stream_id, j.value_stream_stage_id
        """,
    )

    # 3. Stage join + criteria: junction -> stage table (entrance/exit).
    show(
        engine,
        "3. Stages joined from the junction (entrance/exit criteria present?)",
        f"""
        SELECT TOP 20 DISTINCT
          j.value_stream_id,
          s.value_stream_stage_id,
          s.value_stream_stage_name,
          s.value_stream_stage_entrance_criteria,
          s.value_stream_stage_exit_criteria
        FROM {SCHEMA}.idp_sightline_value_stream_capability j
        JOIN {SCHEMA}.idp_sightline_value_stream_stage s
          ON s.value_stream_stage_id = j.value_stream_stage_id
        ORDER BY j.value_stream_id
        """,
    )

    # 4. Does the stage table have a value_stream_id column? (expect: no row -> junction is the only link)
    show(
        engine,
        "4. Stage table columns containing 'value_stream_id' (expect none)",
        f"""
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = '{SCHEMA}'
          AND TABLE_NAME = 'idp_sightline_value_stream_stage'
          AND COLUMN_NAME = 'value_stream_id'
        """,
    )

    # 5. Row counts (sanity).
    for table in (
        "idp_sightline_value_stream",
        "idp_sightline_value_stream_stage",
        "idp_sightline_value_stream_capability",
        "idp_sightline_l3_capabilities",
        "idp_sightline_l2_capabilities",
    ):
        show(engine, f"5. Row count: {table}", f"SELECT COUNT(*) AS n FROM {SCHEMA}.{table}")


if __name__ == "__main__":
    main()
