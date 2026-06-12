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

# Used only if the DB is completely empty (no rows at all yet).
HARD_FALLBACK = {
    "id": None,
    "name": "Fallback",
    "client_match": "",
    "is_default": 1,
    "compte_client": "411000",
    "compte_tva_19": "436719",
    "compte_ht_19": "707019",
    "use_timbre": 1,
    "compte_timbre": "437000",
    "use_7_percent": 0,
    "compte_tva_7": "436707",
    "compte_ht_7": "707019",
    "use_cash": 0,
    "compte_caisse": "541100",
}


def ensure_default_exists(conn) -> None:
    # 1. Check if there is a default formula with client_match = ''
    row = conn.execute("SELECT id FROM formulas WHERE is_default=1 AND client_match='' LIMIT 1").fetchone()
    if not row:
        # Check if there is any row with client_match = '' that we can make default
        row_empty = conn.execute("SELECT id FROM formulas WHERE client_match='' LIMIT 1").fetchone()
        if row_empty:
            conn.execute("UPDATE formulas SET is_default=1 WHERE id=?", (row_empty['id'],))
        else:
            # Create a brand new default formula!
            fields = [
                "name", "client_match", "is_default", "compte_client", "compte_tva_19",
                "compte_ht_19", "use_timbre", "compte_timbre", "use_7_percent",
                "compte_tva_7", "compte_ht_7", "use_cash", "compte_caisse"
            ]
            values = ["Default", "", 1, "411000", "436719", "707019", 1, "437000", 0, "436707", "707019", 0, "541100"]
            conn.execute(
                f"INSERT INTO formulas ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                values
            )
            
    # 2. Make sure no other rows are marked as default
    true_default = conn.execute("SELECT id FROM formulas WHERE is_default=1 AND client_match='' LIMIT 1").fetchone()
    if true_default:
        conn.execute("UPDATE formulas SET is_default=0 WHERE id != ?", (true_default['id'],))
    conn.commit()


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    ensure_default_exists(conn)
    return conn


def list_formulas() -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM formulas ORDER BY is_default DESC, id ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_default_formula() -> dict:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM formulas WHERE is_default=1 LIMIT 1").fetchone()
        if row:
            return dict(row)
        row = conn.execute("SELECT * FROM formulas ORDER BY id ASC LIMIT 1").fetchone()
        if row:
            return dict(row)
    return HARD_FALLBACK.copy()


def save_formula(formula: dict) -> int:
    """Insert (id is None/missing) or update (id present) a formula. Returns its id."""
    fields = [
        "name", "client_match", "is_default", "compte_client", "compte_tva_19",
        "compte_ht_19", "use_timbre", "compte_timbre", "use_7_percent",
        "compte_tva_7", "compte_ht_7", "use_cash", "compte_caisse",
    ]
    values = [formula.get(f, HARD_FALLBACK[f]) for f in fields]

    with get_connection() as conn:
        if formula.get("is_default"):
            conn.execute("UPDATE formulas SET is_default = 0")

        if formula.get("id"):
            conn.execute(
                f"UPDATE formulas SET {', '.join(f'{f}=?' for f in fields)} WHERE id=?",
                (*values, formula["id"]),
            )
            new_id = formula["id"]
        else:
            cur = conn.execute(
                f"INSERT INTO formulas ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
                values,
            )
            new_id = cur.lastrowid

        conn.commit()
        return new_id


def delete_formula(formula_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM formulas WHERE id=?", (formula_id,))
        conn.commit()


def set_default(formula_id: int) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE formulas SET is_default = 0")
        conn.execute("UPDATE formulas SET is_default = 1 WHERE id=?", (formula_id,))
        conn.commit()


def match_formula(client_name: str) -> dict:
    """Matches 'ID | NAME' against 'client_match' in formulas table."""
    client_name = (client_name or "").upper().strip()
    
    # 1. Clean name (Extract 'TUNISIE AUTOMOTIVE' from 'C000114 | TUNISIE AUTOMOTIVE')
    name_only = client_name.split("|")[-1].strip()
    
    formulas = list_formulas()
    
    # 2. Try Exact Match on Name
    for f in formulas:
        cm = (f.get("client_match") or "").strip().upper()
        if cm and cm == name_only: return f
        
    # 3. Try Partial Match
    for f in formulas:
        cm = (f.get("client_match") or "").strip().upper()
        if cm and cm in client_name: return f
            
    return get_default_formula()
    