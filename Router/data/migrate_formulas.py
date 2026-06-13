import json
from pathlib import Path
from data.db import get_connection

JSON_FILE = Path(__file__).parent / "formulas.json"

def migrate():
    if not JSON_FILE.exists(): return
    with open(JSON_FILE, "r", encoding="utf-8") as f: formulas = json.load(f)
    with get_connection() as conn:
        if conn.execute("SELECT COUNT(*) FROM formulas").fetchone()[0]: return
        for i, f in enumerate(formulas):
            conn.execute("""INSERT INTO formulas (name, client_match, is_default, compte_client, compte_tva_19, compte_ht_19, use_timbre, compte_timbre, use_7_percent, compte_tva_7, compte_ht_7, use_cash, compte_caisse)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (f.get("client_match", f"Formula {i}"), f.get("client_match", ""), 1 if i==0 else 0,
                 f.get("compte_client", "411000"), f.get("compte_tva_19", "436719"), f.get("compte_ht_19", "707019"),
                 int(f.get("use_timbre", False)), f.get("compte_timbre", "437000"), int(f.get("use_7_percent", False)),
                 f.get("compte_tva_7", "436707"), f.get("compte_ht_7", "707019"), int(f.get("use_cash", False)), f.get("compte_caisse", "541100")))
        conn.commit()

if __name__ == "__main__": migrate()
