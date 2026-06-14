from decimal import Decimal
from functions.helpers import log, dec, tva_rate, ZERO, MILLIME, is_avoir
from data.config import SKIP_RE, ACC_ROUND, LBL_ROUND, LBL_CLIENT, LBL_TVA, LBL_HT_19, LBL_HT_7, LBL_CAISSE
from data.db import match_formula

def parse_csv_with_mapping(mapping, raw_data, doc_type):
    normalized_rows = []
    for row in raw_data:
        norm_row = {mapping[col]: (tva_rate(val) if mapping[col] == "tva_rate" else 
                    dec(val) if mapping[col] in ("ttc", "net_ht", "tva_amt") else 
                    str(val).strip()) for col, val in row.items() if col in mapping}
        normalized_rows.append(norm_row)

    groups = {}
    for r in normalized_rows:
        ref = r.get("ref", "").strip()
        if not ref or SKIP_RE.search(ref): continue
        groups.setdefault(ref, []).append(r)

    entries = []
    for ref, rows in groups.items():
        first = rows[0]
        formula = match_formula(first.get("client", ""))
        
        is_av = is_avoir(first.get("operation", ""))
        ttc = abs(first.get("ttc", ZERO))
        journal_to_use = "CA" if formula.get("use_cash") else "VT"
        
        lines = []
        # 1. Main Client Line
        lines.append({
            "account": formula.get("compte_client", "411000"), 
            "label": LBL_CLIENT, 
            "debit": ZERO if is_av else ttc, 
            "credit": ttc if is_av else ZERO
        })

        # 2. Timbre
        if formula.get("use_timbre") and ttc > ZERO:
            timbre_amt = dec(formula.get("timbre_amount", "1.000"))
            lines.append({
                "account": formula.get("compte_timbre", "437000"), 
                "label": "TIMBRE FISCAL", 
                "debit": timbre_amt if is_av else ZERO, 
                "credit": ZERO if is_av else timbre_amt
            })

        # 3. Splits
        for r in rows:
            rate = r.get("tva_rate", Decimal("19"))
            tva = abs(r.get("tva_amt", ZERO))
            ht = abs(r.get("net_ht", ZERO))
            if tva > ZERO:
                acc = formula.get("compte_tva_7") if rate < 10 else formula.get("compte_tva_19")
                lines.append({"account": acc, "label": f"{LBL_TVA} {rate}%", "debit": tva if is_av else ZERO, "credit": ZERO if is_av else tva})
            if ht > ZERO:
                acc = formula.get("compte_ht_7") if rate < 10 else formula.get("compte_ht_19")
                lines.append({"account": acc, "label": LBL_HT_19 if rate > 10 else LBL_HT_7, "debit": ht if is_av else ZERO, "credit": ZERO if is_av else ht})

        # 4. Cash Rule (Extra 2 lines for PASSAGER)
        if formula.get("use_cash"):
            # Move from Client to Caisse
            lines.append({
                "account": formula.get("compte_client", "411000"), 
                "label": LBL_CLIENT, 
                "debit": ttc if is_av else ZERO, 
                "credit": ZERO if is_av else ttc
            })
            lines.append({
                "account": formula.get("compte_caisse", "541100"), 
                "label": LBL_CAISSE, 
                "debit": ZERO if is_av else ttc, 
                "credit": ttc if is_av else ZERO
            })

        # 5. Balance Check
        total_debit = sum(l["debit"] for l in lines)
        total_credit = sum(l["credit"] for l in lines)
        diff = total_debit - total_credit
        is_balanced = abs(diff) < MILLIME
        
        # Rounding Patch
        if abs(diff) == MILLIME:
            lines.append({"account": ACC_ROUND, "label": LBL_ROUND, "debit": MILLIME if diff < 0 else ZERO, "credit": ZERO if diff < 0 else MILLIME})
            is_balanced = True

        entries.append({
            "docRef": ref, "date": first.get("date", ""), "journal": journal_to_use,
            "piece": ref, "libelle": (first.get("client") or ref).upper(), "lines": lines,
            "balanced": is_balanced
        })
    return entries
    