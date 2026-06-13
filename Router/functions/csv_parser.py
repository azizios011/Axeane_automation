from decimal import Decimal
from functions.helpers import log, dec, tva_rate, ZERO, MILLIME, is_avoir
from data.config import SKIP_RE, ACC_ROUND, LBL_ROUND, LBL_CLIENT, LBL_TVA, LBL_HT_19, LBL_HT_7, LBL_CAISSE
from data.db import match_formula

def parse_csv_with_mapping(mapping, raw_data, doc_type):
    norm_rows = []
    for row in raw_data:
        norm_row = {mapping[col]: (tva_rate(val) if mapping[col] == "tva_rate" else 
                    dec(val) if mapping[col] in ("ttc", "net_ht", "tva_amt") else 
                    str(val).strip()) for col, val in row.items() if col in mapping}
        norm_rows.append(norm_row)

    groups = {}
    for r in norm_rows:
        ref = r.get("ref", "").strip()
        if not ref or SKIP_RE.search(ref): continue
        groups.setdefault(ref, []).append(r)

    entries = []
    for ref, rows in groups.items():
        first = rows[0]
        formula = match_formula(first.get("client", ""))
        is_av = is_avoir(first.get("operation", ""))
        ttc = abs(first.get("ttc", ZERO))
        
        lines = []
        # 1. CLIENT / TTC Line
        lines.append({
            "account": formula["compte_client"], 
            "label": LBL_CLIENT, 
            "debit": ZERO if is_av else ttc, 
            "credit": ttc if is_av else ZERO
        })

        # 2. TIMBRE (Stamp Duty - usually 1.000 TND)
        if formula.get("use_timbre") and ttc > ZERO:
            timbre_val = Decimal("1.000")
            lines.append({
                "account": formula["compte_timbre"], 
                "label": "TIMBRE FISCAL", 
                "debit": timbre_val if is_av else ZERO, 
                "credit": ZERO if is_av else timbre_val
            })

        # 3. HT & TVA Lines
        for r in rows:
            rate = r.get("tva_rate", Decimal("19"))
            tva = abs(r.get("tva_amt", ZERO))
            ht = abs(r.get("net_ht", ZERO))
            
            if tva > ZERO:
                acc_tva = formula["compte_tva_7"] if rate < 10 else formula["compte_tva_19"]
                lines.append({
                    "account": acc_tva, 
                    "label": f"{LBL_TVA} {rate}%", 
                    "debit": tva if is_av else ZERO, 
                    "credit": ZERO if is_av else tva
                })
            if ht > ZERO:
                acc_ht = formula["compte_ht_7"] if rate < 10 else formula["compte_ht_19"]
                lines.append({
                    "account": acc_ht, 
                    "label": f"{LBL_HT_19 if rate > 10 else LBL_HT_7}", 
                    "debit": ht if is_av else ZERO, 
                    "credit": ZERO if is_av else ht
                })

        # 4. CASH Logic (Duplicate TTC)
        if formula.get("use_cash"):
            lines.append({"account": formula["compte_client"], "label": LBL_CLIENT, "debit": ttc if is_av else ZERO, "credit": ZERO if is_av else ttc})
            lines.append({"account": formula["compte_caisse"], "label": LBL_CAISSE, "debit": ZERO if is_av else ttc, "credit": ttc if is_av else ZERO})

        # 5. BALANCE CHECK
        total_debit = sum(l["debit"] for l in lines)
        total_credit = sum(l["credit"] for l in lines)
        diff = total_debit - total_credit
        
        error = ""
        is_balanced = False

        if abs(diff) < MILLIME:
            is_balanced = True
        elif abs(diff) == MILLIME:
            # Auto-patch 0.001 rounding
            lines.append({
                "account": ACC_ROUND, 
                "label": LBL_ROUND, 
                "debit": MILLIME if diff < 0 else ZERO, 
                "credit": ZERO if diff < 0 else MILLIME
            })
            is_balanced = True
        else:
            error = f"Diff: {diff:.3f} (D:{total_debit:.3f} / C:{total_credit:.3f})"
            # Log the first few errors to console for debugging
            if len(entries) < 5:
                log(f"⚠️ Unbalanced Entry {ref}: {error}")

        entries.append({
            "docRef": ref,
            "date": first.get("date", ""),
            "journal": "CA" if formula.get("use_cash") else "VT",
            "piece": ref,
            "libelle": (first.get("client") or ref).upper(),
            "lines": lines,
            "balanced": is_balanced,
            "error_reason": error
        })
    return entries
    