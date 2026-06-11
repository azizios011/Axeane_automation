import json
from pathlib import Path

FORMULAS_FILE = Path(__file__).parent / "formulas.json"

DEFAULT_FORMULAS = [
    {
        "client_match": "PASSAGER",
        "compte_client": "411000",
        "compte_tva_19": "436710",
        "compte_ht_19": "707019",
        "use_timbre": True,
        "compte_timbre": "736000",
        "use_7_percent": False,
        "compte_tva_7": "436707",
        "compte_ht_7": "707007",
        "use_cash": False,
        "compte_caisse": "541100"
    },
    {
        "client_match": "COMPTANT",
        "compte_client": "411000",
        "compte_tva_19": "436710",
        "compte_ht_19": "707019",
        "use_timbre": True,
        "compte_timbre": "736000",
        "use_7_percent": True,
        "compte_tva_7": "436707",
        "compte_ht_7": "707007",
        "use_cash": True,
        "compte_caisse": "541100"
    }
]

def load_formulas() -> list:
    if FORMULAS_FILE.exists():
        try:
            with open(FORMULAS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_FORMULAS.copy()

def save_formulas(formulas: list):
    with open(FORMULAS_FILE, "w", encoding="utf-8") as f:
        json.dump(formulas, f, indent=4)

FORMULAS = load_formulas()
