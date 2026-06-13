import json
from pathlib import Path

FORMULAS_FILE = Path(__file__).parent / "formulas.json"

def list_formulas():
    if not FORMULAS_FILE.exists(): return []
    with open(FORMULAS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def get_default_formula():
    formulas = list_formulas()
    for f in formulas:
        if f.get("is_default"): return f
    return formulas[0] if formulas else {}

def match_formula(client_name: str):
    client_name = (client_name or "").upper().strip()
    formulas = list_formulas()
    
    # Try exact or keyword match
    for f in formulas:
        cm = (f.get("client_match") or "").strip().upper()
        if cm and cm in client_name:
            return f
            
    return get_default_formula()

# Dummies to satisfy UI imports
def save_formula(f): pass
def delete_formula(id): pass
