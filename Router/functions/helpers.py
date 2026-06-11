from decimal import Decimal, ROUND_HALF_UP
from typing import Any
import re
from data.config import CASH_RE, SKIP_RE

MILLIME = Decimal("0.001")
ZERO = Decimal("0.000")

def log(msg: str) -> None:
    print(f"[axeane] {msg}", flush=True)

def dec(v: Any) -> Decimal:
    if v is None or str(v).strip() in ("", "-", "#########"):
        return ZERO
    s = str(v).strip().replace(",", ".").replace("  ", " ")
    try:
        return Decimal(s).quantize(MILLIME, rounding=ROUND_HALF_UP)
    except Exception:
        return ZERO

def tva_rate(rate_str: str) -> Decimal:
    m = re.search(r"[\d.]+", str(rate_str))
    return Decimal(m.group()) if m else Decimal("19")

def is_cash(client: str) -> bool:
    return bool(CASH_RE.search(client))

def is_avoir(op: str) -> bool:
    return "avoir" in op.lower()
    