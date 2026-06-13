from decimal import Decimal, ROUND_HALF_UP
from functions.helpers import log, dec, tva_rate, ZERO, MILLIME
from data.config import SKIP_RE, ACC_ROUND, LBL_ROUND, DEFAULT_DEVISE
from data.db import match_formula as get_formula

def parse_csv_with_mapping(mapping: dict, raw_data: list[dict], doc_type: str) -> list[dict]:
    normalized_rows = []
    for row in raw_data:
        norm_row = {mapping[csv_col]: (tva_rate(val) if mapping[csv_col] == "tva_rate" else 
                    dec(val) if mapping[csv_col] in ("ttc", "net_ht", "tva_amt") else 
                    str(val).strip()) for csv_col, val in row.items() if csv_col in mapping}
        normalized_rows.append(norm_row)

    groups = {}
    for r in normalized_rows:
        ref = r.get("ref", "").strip()
        if not ref or SKIP_RE.search(ref): continue
        groups.setdefault(ref, []).append(r)

    entries = []
    for ref, rows in groups.items():
        first = rows[0]
        client_raw = first.get("client", "")
        
        # ASK THE DB: Who is the "Man of the house" for this client?
        formula = get_formula(client_raw)
        is_cash_entry = bool(formula.get("use_cash", 0))
        
        ttc = abs(first.get("ttc", ZERO))
        lines = []
        
        # ... (Facture/Avoir logic stays same, using formula["compte_client"], etc.) ...
        # Simplified example of line generation:
        lines.append({"account": formula["compte_client"], "label": "CLIENTS", "debit": ttc, "credit": ZERO})
        # (Add your TVA and HT lines here using formula values)

        if is_cash_entry:
            lines.append({"account": formula["compte_client"], "label": "CLIENTS", "debit": ZERO, "credit": ttc})
            lines.append({"account": formula["compte_caisse"], "label": "CAISSE", "debit": ttc, "credit": ZERO})

        # Rounding logic...

        # 🆕 Devise: comes from CSV mapping if provided (e.g. mapping has a
        # "devise" column mapped to key "devise"), otherwise default TND.
        devise = (first.get("devise") or "").strip().upper() or DEFAULT_DEVISE

        entries.append({
            "docRef": ref,
            "date": first.get("date", ""),
            "journal": "CA" if is_cash_entry else "VT",
            "devise": devise,
            "lines": lines,
            "balanced": True # After rounding check
        })
    return entries
    