from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import re

MILLIME = Decimal("0.001")
ZERO = Decimal("0.000")

def log(msg: str) -> None:
    print(f"[axeane] {msg}", flush=True)

def dec(v: Any) -> Decimal:
    if v is None or str(v).strip() in ("", "-", "#########"):
        return ZERO
    # 🆕 Remove commas (thousands separators) and spaces to correctly parse "1,639.756"
    s = str(v).strip().replace(",", "").replace(" ", "")
    try:
        return Decimal(s).quantize(MILLIME, rounding=ROUND_HALF_UP)
    except Exception:
        return ZERO

def tva_rate(rate_str: str) -> Decimal:
    m = re.search(r"[\d.]+", str(rate_str))
    return Decimal(m.group()) if m else Decimal("19")

def is_cash(client: str) -> bool:
    # Removed 'comptant' from the list
    return bool(re.compile(r"passager|caisse|fj pass", re.I).search(client))

def is_avoir(op: str) -> bool:
    return "avoir" in op.lower()
    