import sqlite3
from pathlib import Path

DB_FILE = Path(__file__).parent / "formulas.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS formulas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT    NOT NULL DEFAULT '',
    client_match    TEXT    NOT NULL DEFAULT '',
    is_default      INTEGER NOT NULL DEFAULT 0,
    compte_client   TEXT    NOT NULL DEFAULT '411000',
    compte_tva_19   TEXT    NOT NULL DEFAULT '436719',
    compte_ht_19    TEXT    NOT NULL DEFAULT '707019',
    use_timbre      INTEGER NOT NULL DEFAULT 1,
    compte_timbre   TEXT    NOT NULL DEFAULT '437000',
    use_7_percent   INTEGER NOT NULL DEFAULT 0,
    compte_tva_7    TEXT    NOT NULL DEFAULT '436707',
    compte_ht_7     TEXT    NOT NULL DEFAULT '707019',
    use_cash        INTEGER NOT NULL DEFAULT 0,
    compte_caisse   TEXT    NOT NULL DEFAULT '541100'
);
"""

def get_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn

def list_formulas():
    with get_connection() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM formulas ORDER BY is_default DESC, id ASC").fetchall()]

def get_default_formula():
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM formulas WHERE is_default=1 LIMIT 1").fetchone()
        if row: return dict(row)
        # Fallback if no default marked
        row = conn.execute("SELECT * FROM formulas LIMIT 1").fetchone()
        return dict(row) if row else {}

def match_formula(client_name: str):
    name_only = (client_name or "").upper().split("|")[-1].strip()
    formulas = list_formulas()
    for f in formulas:
        cm = (f.get("client_match") or "").strip().upper()
        if cm and (cm == name_only or cm in (client_name or "").upper()):
            return f
    return get_default_formula()

def delete_formula(f_id):
    with get_connection() as conn:
        conn.execute("DELETE FROM formulas WHERE id=?", (f_id,))

def save_formula(formula: dict) -> int:
    """Insert or update a formula. Handles the 'Default' toggle safely."""
    fields = [
        "name", "client_match", "is_default", "compte_client", "compte_tva_19",
        "compte_ht_19", "use_timbre", "compte_timbre", "use_7_percent",
        "compte_tva_7", "compte_ht_7", "use_cash", "compte_caisse",
    ]
    values = [formula.get(f, "") for f in fields]

    with get_connection() as conn:
        cursor = conn.cursor()
        if formula.get("is_default"):
            cursor.execute("UPDATE formulas SET is_default = 0")

        if formula.get("id"):
            placeholders = ", ".join([f"{f}=?" for f in fields])
            cursor.execute(f"UPDATE formulas SET {placeholders} WHERE id=?", (*values, formula["id"]))
            new_id = formula["id"]
        else:
            qs = ", ".join(["?"] * len(fields))
            cursor.execute(f"INSERT INTO formulas ({', '.join(fields)}) VALUES ({qs})", values)
            new_id = cursor.lastrowid
        conn.commit()
        return new_id
        