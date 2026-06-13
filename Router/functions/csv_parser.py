from decimal import Decimal
from functions.helpers import log, dec, tva_rate, ZERO, MILLIME, is_avoir
from data.config import SKIP_RE, ACC_ROUND, LBL_ROUND, LBL_CLIENT, LBL_TVA, LBL_HT_19, LBL_HT_7, LBL_CAISSE
from data.db import match_formula

def parse_csv_with_mapping(mapping, raw_data, doc_type):
    """
    Core Parser:
    1. Normalizes CSV data based on user column mapping.
    2. Groups rows by Reference.
    3. Matches client names to formulas.json rules.
    4. Generates accounting lines (including taxes, timbre, and cash logic).
    5. Validates balance with the strict 0.001 rule.
    """
    normalized_rows = []
    for row in raw_data:
        norm_row = {mapping[col]: (tva_rate(val) if mapping[col] == "tva_rate" else 
                    dec(val) if mapping[col] in ("ttc", "net_ht", "tva_amt") else 
                    str(val).strip()) for col, val in row.items() if col in mapping}
        normalized_rows.append(norm_row)

    # Group by Reference (DocRef)
    groups = {}
    for r in normalized_rows:
        ref = r.get("ref", "").strip()
        if not ref or SKIP_RE.search(ref): continue
        groups.setdefault(ref, []).append(r)

    entries = []
    for ref, rows in groups.items():
        first = rows[0]
        
        # 1. Match the rule from formulas.json
        formula = match_formula(first.get("client", ""))
        
        # 2. Determine Entry Type
        is_av = is_avoir(first.get("operation", ""))
        ttc = abs(first.get("ttc", ZERO))
        
        # 3. Automation: Force Journal CA if it's a Cash Formula
        journal_to_use = "CA" if formula.get("use_cash") else "VT"
        
        lines = []
        
        # --- LINE GENERATION ---
        
        # A. MAIN CLIENT / TTC LINE
        lines.append({
            "account": formula.get("compte_client", "411000"), 
            "label": LBL_CLIENT, 
            "debit": ZERO if is_av else ttc, 
            "credit": ttc if is_av else ZERO
        })

        # B. TIMBRE FISCAL (Stamp Duty - 1.000 TND)
        if formula.get("use_timbre") and ttc > ZERO:
            timbre_val = Decimal("1.000")
            lines.append({
                "account": formula.get("compte_timbre", "437000"), 
                "label": "TIMBRE FISCAL", 
                "debit": timbre_val if is_av else ZERO, 
                "credit": ZERO if is_av else timbre_val
            })

        # C. HT & TVA SPLITS (Per Rate)
        for r in rows:
            rate = r.get("tva_rate", Decimal("19"))
            tva_amt = abs(r.get("tva_amt", ZERO))
            ht_amt = abs(r.get("net_ht", ZERO))
            
            # TVA Line
            if tva_amt > ZERO:
                acc_tva = formula.get("compte_tva_7") if rate < 10 else formula.get("compte_tva_19")
                lines.append({
                    "account": acc_tva, 
                    "label": f"{LBL_TVA} {rate}%", 
                    "debit": tva_amt if is_av else ZERO, 
                    "credit": ZERO if is_av else tva_amt
                })
            
            # HT Line (Revenue)
            if ht_amt > ZERO:
                acc_ht = formula.get("compte_ht_7") if rate < 10 else formula.get("compte_ht_19")
                lines.append({
                    "account": acc_ht, 
                    "label": f"{LBL_HT_19 if rate > 10 else LBL_HT_7}", 
                    "debit": ht_amt if is_av else ZERO, 
                    "credit": ZERO if is_av else ht_amt
                })

        # D. CASH LOGIC (Duplication for PASSAGER)
        if formula.get("use_cash"):
            # Counter-entry to close Client account
            lines.append({
                "account": formula.get("compte_client", "411000"), 
                "label": LBL_CLIENT, 
                "debit": ttc if is_av else ZERO, 
                "credit": ZERO if is_av else ttc
            })
            # Entry to Caisse
            lines.append({
                "account": formula.get("compte_caisse", "541100"), 
                "label": LBL_CAISSE, 
                "debit": ZERO if is_av else ttc, 
                "credit": ttc if is_av else ZERO
            })

        # --- FINAL VALIDATION ---
        
        total_debit = sum(l["debit"] for l in lines)
        total_credit = sum(l["credit"] for l in lines)
        diff = total_debit - total_credit
        
        error = ""
        is_balanced = False

        if abs(diff) < MILLIME:
            is_balanced = True
        elif abs(diff) == MILLIME:
            # Automatic Rounding Patch (0.001)
            lines.append({
                "account": ACC_ROUND, 
                "label": LBL_ROUND, 
                "debit": MILLIME if diff < 0 else ZERO, 
                "credit": ZERO if diff < 0 else MILLIME
            })
            is_balanced = True
        else:
            error = f"Unbalanced: {diff:.3f} (D:{total_debit:.3f} / C:{total_credit:.3f})"
            if len(entries) < 3: # Log first few errors
                log(f"⚠️ {ref} {error}")

        entries.append({
            "docRef": ref,
            "date": first.get("date", ""),
            "journal": journal_to_use,
            "piece": ref,
            "libelle": (first.get("client") or ref).upper(),
            "lines": lines,
            "balanced": is_balanced,
            "error_reason": error
        })
        
    return entries
    