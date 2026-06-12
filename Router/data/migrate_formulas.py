"""
One-time migration: reads the legacy formulas.json (if present) and inserts
each entry into the new SQLite-backed formulas.db.

Run once with:  python -m data.migrate_formulas
"""
import json
from pathlib import Path

from data.db import get_connection

JSON_FILE = Path(__file__).parent / "formulas.json"


def migrate() -> None:
    if not JSON_FILE.exists():
        print("No formulas.json found — nothing to migrate.")
        return

    with open(JSON_FILE, "r", encoding="utf-8") as f:
        formulas = json.load(f)

    if not formulas:
        print("formulas.json is empty — nothing to migrate.")
        return

    with get_connection() as conn:
        existing = conn.execute("SELECT COUNT(*) FROM formulas").fetchone()[0]
        if existing:
            print(f"formulas.db already has {existing} formula(s) — skipping migration "
                  f"to avoid duplicates. Delete formulas.db first if you want a clean import.")
            return

        for i, f in enumerate(formulas):
            name = f.get("client_match") or f"Formula {i + 1}"
            conn.execute(
                """
                INSERT INTO formulas (
                    name, client_match, is_default, compte_client, compte_tva_19,
                    compte_ht_19, use_timbre, compte_timbre, use_7_percent,
                    compte_tva_7, compte_ht_7, use_cash, compte_caisse
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    name,
                    f.get("client_match", ""),
                    1 if i == 0 else 0,  # first formula becomes the Default
                    f.get("compte_client", "411000"),
                    f.get("compte_tva_19", "436719"),
                    f.get("compte_ht_19", "707019"),
                    int(f.get("use_timbre", False)),
                    f.get("compte_timbre", "437000"),
                    int(f.get("use_7_percent", False)),
                    f.get("compte_tva_7", "436707"),
                    f.get("compte_ht_7", "707019"),
                    int(f.get("use_cash", False)),
                    f.get("compte_caisse", "541100"),
                ),
            )
        conn.commit()

    print(f"Migrated {len(formulas)} formula(s) into formulas.db. "
          f"'{formulas[0].get('client_match') or 'Formula 1'}' marked as Default.")


if __name__ == "__main__":
    migrate()
    