import json
from pathlib import Path

MAPPINGS_FILE = Path(__file__).parent / "user_mappings.json"

DEFAULT_MAPPINGS = {
    "Vente": {
        "Client": "client",
        "Operation": "operation",
        "Reference": "ref",
        "Date": "date",
        "TTC": "ttc",
        "Tot. Net. HT": "net_ht",
        "TVA %": "tva_rate",
        "Montant TVA": "tva_amt",
    },
    "Achat": {
        "Fournisseur": "fournisseur",
        "Reference": "ref",
        "Date": "date",
        "TTC": "ttc",
    },
    "Bank": {
        "Date": "date",
        "Libelle": "libelle",
        "Debit": "debit",
        "Credit": "credit",
    }
}

def load_user_mappings() -> dict:
    if MAPPINGS_FILE.exists():
        try:
            with open(MAPPINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return DEFAULT_MAPPINGS

def save_user_mappings(mappings: dict):
    with open(MAPPINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(mappings, f, indent=4)

# Load mappings on startup
MAPPINGS = load_user_mappings()
