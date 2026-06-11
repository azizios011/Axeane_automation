import json
import re
from pathlib import Path

# ── Dynamic Settings (Replaces .env) ─────────────────────────────────────────
SETTINGS_FILE = Path(__file__).parent / "settings.json"

DEFAULT_SETTINGS = {
    "cdp_url": "http://localhost:9222",
    "axeane_user": "RIHAB1",
    "axeane_password": "",
    "axeane_entreprise": "CPR",       # 🆕 Added
    "axeane_exercice": "EX 2026",     # 🆕 Added
    "slow_mo": 300
}

def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                return {**DEFAULT_SETTINGS, **saved}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=4)

SETTINGS = load_settings()

# ── PCT accounts ─────────────────────────────────────────────────────────────
ACC_CLIENT = "411000"
ACC_CAISSE = "541100"
ACC_HT_19 = "707019"
ACC_HT_7 = "707007"
ACC_TVA = "436710"
ACC_ROUND = "736000"

LBL_CLIENT = "CLIENTS"
LBL_CAISSE = "CAISSE"
LBL_HT_19 = "VT DE MARCHANDISE"
LBL_HT_7 = "HTVA 7%"
LBL_TVA = "TVA COLLECTEE"
LBL_ROUND = "AJUST ARRONDI"

# ── Regex & Constants ────────────────────────────────────────────────────────
CASH_RE = re.compile(r"passager|comptant|caisse|fj pass", re.I)
SKIP_RE = re.compile(r"total\s+pour|grand\s+total", re.I)
MONTH_FR = [
    "", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
    "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"
]
