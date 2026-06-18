"""
One-off verification of the value-stream catalogue schema and relationships.

Run this directly (python scripts/verify_catalogue_schema.py) or paste into a notebook cell.
It connects straight to the database with pyodbc (no HTTP gateway, no SQLAlchemy) and answers,
against live data:

  1. Does the junction's capability_id point at L3 or L2?  (the one open assumption)
  2. Does the full vs -> vss -> l3 -> l2 chain join end to end?
  3. Does the stage table really have no value_stream_id (so the junction is the only link)?
  4. Row counts per table (sanity).

Fill in CONNECTION below (Azure AD account -> keep AUTHENTICATION). Do not commit real credentials.
"""

import pyodbc

# --------------------------------------------------------------------------- #
# CONNECTION — fill these in                                                   #
# --------------------------------------------------------------------------- #
SERVER = "your-server.database.windows.net"
DATABASE = "your-database"
USERNAME = "your-username"            # Azure AD account, e.g. Msazure_...@myfyi.onmicrosoft.com
PASSWORD = "your-password"
PORT = 1433
ODBC_DRIVER = "ODBC Driver 17 for SQL Server"
# Auth method. "ActiveDirectoryPassword" for Azure AD accounts (user@domain.onmicrosoft.com);
# set to "" for a plain SQL Server login.
AUTHENTICATION = "ActiveDirectoryPassword"

SCHEMA = "idp_impact_analyis"  # note: this is the real (misspelled) schema name
# --------------------------------------------------------------------------- #


def resolve_odbc_driver() -> str:
    """Use ODBC_DRIVER if it's installed, else fall back to any installed SQL Server driver."""
    installed = list(pyodbc.drivers())
    if ODBC_DRIVER in installed:
        driver = ODBC_DRIVER
    else:
        driver = next((d for d in installed if "SQL Server" in d), None)
    if driver is None:
        raise SystemExit(
            f"No SQL Server ODBC driver found. Installed drivers: {installed}\n"
            "Install an ODBC Driver for SQL Server or set ODBC_DRIVER to one of the above."
        )
    print(f"Using ODBC driver: {driver}")
    return driver


def connect() -> pyodbc.Connection:
    """Open a pyodbc connection using the same connection-string shape as the working notebook."""
    parts = [
        f"DRIVER={{{resolve_odbc_driver()}}}",
        f"SERVER={SERVER},{PORT}",
        f"DATABASE={DATABASE}",
        f"UID={USERNAME}",
        f"PWD={PASSWORD}",
        "Encrypt=yes",
        "TrustServerCertificate=no",
        "Connection Timeout=30",
    ]
    if AUTHENTICATION:
        parts.append(f"Authentication={AUTHENTICATION}")
    return pyodbc.connect(";".join(parts) + ";")


def show(cursor: pyodbc.Cursor, label: str, sql: str) -> None:
    """Run one query and print its columns and rows."""
    print("\n" + "=" * 90)
    print(label)
    print("-" * 90)
    cursor.execute(sql)
    cols = [c[0] for c in cursor.description]
    rows = cursor.fetchall()
    print(" | ".join(cols))
    for row in rows:
        print(" | ".join("" if v is None else str(v) for v in row))
    print(f"({len(rows)} row(s))")


def main() -> None:
    conn = connect()
    print("Connected successfully!")
    cursor = conn.cursor()

    # 1. Is the junction's capability_id an L3 id or an L2 id?
    show(
        cursor,
        "1. capability_id -> L3 or L2?  (matches_l3 ~ total_rows means it's L3)",
        f"""
        SELECT
          COUNT(*) AS total_rows,
          SUM(CASE WHEN l3.l3_capability_id IS NOT NULL THEN 1 ELSE 0 END) AS matches_l3,
          SUM(CASE WHEN l2.l2_capability_id IS NOT NULL THEN 1 ELSE 0 END) AS matches_l2
        FROM {SCHEMA}.idp_sightline_value_stream_capability j
        LEFT JOIN {SCHEMA}.idp_sightline_l3_capabilities l3
          ON l3.l3_capability_id = j.capability_id
        LEFT JOIN {SCHEMA}.idp_sightline_l2_capabilities l2
          ON l2.l2_capability_id = j.capability_id
        """,
    )

    # 2. Full chain: junction -> L3 (on capability_id) -> L2 (on L3.parent_capability_id).
    #    Rows here prove both capability_id->L3 and L3->L2.
    show(
        cursor,
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
        cursor,
        "3. Stages joined from the junction (entrance/exit criteria present?)",
        f"""
        SELECT TOP 20
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

    # 4. Does the stage table have a value_stream_id column? (expect none -> junction is the only link)
    show(
        cursor,
        "4. Stage table columns named 'value_stream_id' (expect 0 rows)",
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
        show(cursor, f"5. Row count: {table}", f"SELECT COUNT(*) AS n FROM {SCHEMA}.{table}")

    cursor.close()
    conn.close()


if __name__ == "__main__":
    main()
