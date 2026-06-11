import json
from pathlib import Path

FORMULAS_FILE = Path(__file__).parent / "formulas.json"

# 🆕 Empty defaults. User must define them in the UI.
DEFAULT_FORMULAS = []

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
