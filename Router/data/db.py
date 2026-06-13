import json
from pathlib import Path

FORMULAS_FILE = Path(__file__).parent / "formulas.json"

def list_formulas():
    if not FORMULAS_FILE.exists(): return []
    try:
        with open(FORMULAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except: return []

def get_default_formula():
    formulas = list_formulas()
    # Find the formula explicitly marked as default
    for f in formulas:
        if f.get("is_default") is True or f.get("client_match") == "":
            return f
    return formulas[0] if formulas else {}

def match_formula(client_name: str):
    # 1. Clean the input name
    raw_name = (client_name or "").strip().upper()
    formulas = list_formulas()
    
    # 2. Priority Search: Look for specific keywords first
    # We skip formulas that have no client_match (the default one)
    for f in formulas:
        keyword = (f.get("client_match") or "").strip().upper()
        if keyword and keyword in raw_name:
            return f
            
    # 3. Fallback: If no keywords matched, return the Default
    return get_default_formula()

# Dummies for UI compatibility
def save_formula(f): pass
def delete_formula(id): pass
