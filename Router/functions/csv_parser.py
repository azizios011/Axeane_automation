from decimal import Decimal, ROUND_HALF_UP
from functions.helpers import log, dec, tva_rate, is_cash, is_avoir, ZERO, MILLIME
from data.config import (
    SKIP_RE, ACC_CLIENT, ACC_CAISSE, ACC_HT_19, ACC_HT_7, ACC_TVA, ACC_ROUND,
    LBL_CLIENT, LBL_CAISSE, LBL_HT_19, LBL_HT_7, LBL_TVA, LBL_ROUND
)

def parse_csv_with_mapping(mapping: dict, raw_data: list[dict]) -> list[dict]:
    """Parse CSV data using a dynamic column mapping provided by the UI."""
    
    # 1. Normalize raw data keys to internal keys based on user mapping
    normalized_rows = []
    for row in raw_data:
        norm_row = {}
        for csv_col, internal_key in mapping.items():
            val = row.get(csv_col, "")
            if internal_key == "tva_rate":
                norm_row[internal_key] = tva_rate(val)
            elif internal_key in ("ttc", "net_ht", "tva_amt"):
                norm_row[internal_key] = dec(val)
            else:
                norm_row[internal_key] = str(val).strip()
        normalized_rows.append(norm_row)

    # 2. Group by Reference (same logic as before)
    groups: dict[str, list] = {}
    for r in normalized_rows:
        ref = r.get("ref", "").strip()
        if SKIP_RE.search(r.get("client", "")) or SKIP_RE.search(ref) or not ref:
            continue
        groups.setdefault(ref, []).append(r)

    entries = []
    for ref, rows in groups.items():
        first = rows[0]
        avoir = is_avoir(first.get("operation", ""))
        cash = is_cash(first.get("client", ""))
        ttc = abs(first.get("ttc", ZERO))

        ht_by_rate: dict[Decimal, Decimal] = {}
        tva_by_rate: dict[Decimal, Decimal] = {}
        for r in rows:
            rate = r.get("tva_rate", Decimal("19"))
            ht_by_rate[rate] = ht_by_rate.get(rate, ZERO) + abs(r.get("net_ht", ZERO))
            tva_by_rate[rate] = tva_by_rate.get(rate, ZERO) + abs(r.get("tva_amt", ZERO))

        lines = []
        if not avoir:
            acc = ACC_CAISSE if cash else ACC_CLIENT
            lbl = LBL_CAISSE if cash else LBL_CLIENT
            lines.append({"account": acc, "label": lbl, "debit": ttc, "credit": ZERO})
            for rate, ht in ht_by_rate.items():
                a = ACC_HT_7 if rate == Decimal("7") else ACC_HT_19
                l = LBL_HT_7 if rate == Decimal("7") else LBL_HT_19
                lines.append({"account": a, "label": l, "debit": ZERO, "credit": ht})
            for rate, tva in tva_by_rate.items():
                if tva > ZERO:
                    lines.append({"account": ACC_TVA, "label": LBL_TVA, "debit": ZERO, "credit": tva})
        else:
            acc = ACC_CAISSE if cash else ACC_CLIENT
            lbl = LBL_CAISSE if cash else LBL_CLIENT
            lines.append({"account": acc, "label": lbl, "debit": ZERO, "credit": ttc})
            for rate, ht in ht_by_rate.items():
                a = ACC_HT_7 if rate == Decimal("7") else ACC_HT_19
                l = LBL_HT_7 if rate == Decimal("7") else LBL_HT_19
                lines.append({"account": a, "label": l, "debit": ht, "credit": ZERO})
            for rate, tva in tva_by_rate.items():
                if tva > ZERO:
                    lines.append({"account": ACC_TVA, "label": LBL_TVA, "debit": tva, "credit": ZERO})

        total_d = sum(l["debit"] for l in lines)
        total_c = sum(l["credit"] for l in lines)
        diff = (total_d - total_c).quantize(MILLIME, rounding=ROUND_HALF_UP)
        balanced = diff == ZERO

        if not balanced and abs(diff) == MILLIME:
            if diff > ZERO:
                lines.append({"account": ACC_ROUND, "label": LBL_ROUND, "debit": ZERO, "credit": MILLIME})
            else:
                lines.append({"account": ACC_ROUND, "label": LBL_ROUND, "debit": MILLIME, "credit": ZERO})
            balanced = True

        entries.append({
            "docRef": ref,
            "date": first.get("date", ""),
            "journal": "VT",
            "libelle": f"{first.get('operation', 'FACTURE').upper()} {ref}",
            "piece": ref,
            "balanced": balanced,
            "lines": lines,
        })

    log(f"Parsed {len(entries)} entries from CSV ({sum(1 for e in entries if not e['balanced'])} unbalanced)")
    return entries
    