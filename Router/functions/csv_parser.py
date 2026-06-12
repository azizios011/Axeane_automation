from decimal import Decimal, ROUND_HALF_UP
from functions.helpers import log, dec, tva_rate, is_cash as is_cash_client, is_avoir, ZERO, MILLIME
from data.config import SKIP_RE, ACC_ROUND, LBL_ROUND
from data.db import match_formula as get_formula


def parse_csv_with_mapping(mapping: dict, raw_data: list[dict], doc_type: str) -> list[dict]:
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
        cash_client = is_cash_client(first.get("client", ""))
        ttc = abs(first.get("ttc", ZERO))

        formula = get_formula(first.get("client", ""))
        is_cash_entry = formula.get("use_cash", False) or cash_client

        # ── 7%_Rate_Formula: group rows sharing the same ref by TVA rate ──
        # If a ref appears twice with different TVA% (e.g. 19% and 7%),
        # both rates' HT/TVA amounts end up here and get their own lines.
        ht_by_rate: dict[Decimal, Decimal] = {}
        tva_by_rate: dict[Decimal, Decimal] = {}
        for r in rows:
            rate = r.get("tva_rate", Decimal("19"))
            ht_by_rate[rate] = ht_by_rate.get(rate, ZERO) + abs(r.get("net_ht", ZERO))
            tva_by_rate[rate] = tva_by_rate.get(rate, ZERO) + abs(r.get("tva_amt", ZERO))

        lines = []

        if not avoir:
            # ── Facture_Formula (also the Default_Formula template) ──────
            lines.append({"account": formula["compte_client"], "label": "CLIENTS", "debit": ttc, "credit": ZERO})

            if formula.get("use_timbre"):
                lines.append({"account": formula["compte_timbre"], "label": "TIMBRE", "debit": ZERO, "credit": Decimal("1.000")})

            for rate, ht in ht_by_rate.items():
                if rate == Decimal("7") and formula.get("use_7_percent"):
                    lines.append({"account": formula["compte_ht_7"], "label": "HT 7%", "debit": ZERO, "credit": ht})
                else:
                    lines.append({"account": formula["compte_ht_19"], "label": "HT 19%", "debit": ZERO, "credit": ht})

            for rate, tva in tva_by_rate.items():
                if tva > ZERO:
                    if rate == Decimal("7") and formula.get("use_7_percent"):
                        lines.append({"account": formula["compte_tva_7"], "label": "TVA 7%", "debit": ZERO, "credit": tva})
                    else:
                        lines.append({"account": formula["compte_tva_19"], "label": "TVA 19%", "debit": ZERO, "credit": tva})

            # ── Cash_Fomula: append CAISSE + a duplicate CLIENTS/TTC row ──
            # The base CLIENTS row above is untouched; these two extra rows
            # balance each other (CAISSE debit TTC / CLIENTS credit TTC).
            if is_cash_entry:
                lines.append({"account": formula["compte_client"], "label": "CLIENTS", "debit": ZERO, "credit": ttc})
                lines.append({"account": formula["compte_caisse"], "label": "CAISSE", "debit": ttc, "credit": ZERO})
        else:
            # ── Avoir_Formula (exact opposite of Facture) ─────────────────
            lines.append({"account": formula["compte_client"], "label": "CLIENTS", "debit": ZERO, "credit": ttc})

            if formula.get("use_timbre"):
                lines.append({"account": formula["compte_timbre"], "label": "TIMBRE", "debit": Decimal("1.000"), "credit": ZERO})

            for rate, ht in ht_by_rate.items():
                if rate == Decimal("7") and formula.get("use_7_percent"):
                    lines.append({"account": formula["compte_ht_7"], "label": "HT 7%", "debit": ht, "credit": ZERO})
                else:
                    lines.append({"account": formula["compte_ht_19"], "label": "HT 19%", "debit": ht, "credit": ZERO})

            for rate, tva in tva_by_rate.items():
                if tva > ZERO:
                    if rate == Decimal("7") and formula.get("use_7_percent"):
                        lines.append({"account": formula["compte_tva_7"], "label": "TVA 7%", "debit": tva, "credit": ZERO})
                    else:
                        lines.append({"account": formula["compte_tva_19"], "label": "TVA 19%", "debit": tva, "credit": ZERO})

            # ── Cash_Fomula: append CAISSE + a duplicate CLIENTS/TTC row ──
            if is_cash_entry:
                lines.append({"account": formula["compte_client"], "label": "CLIENTS", "debit": ttc, "credit": ZERO})
                lines.append({"account": formula["compte_caisse"], "label": "CAISSE", "debit": ZERO, "credit": ttc})

        # ── 0.001_Formula: Solde KPI check ───────────────────────────────
        # 0.000 -> entry is correct, no change.
        # 0.001 (either direction) -> Axeane's rounding quirk, patch with
        #     the dedicated 736 (AJUST ARRONDI) compte.
        # anything else -> the entry was entered wrong upstream; flag it
        #     as unbalanced/error instead of silently "fixing" it.
        total_d = sum(l["debit"] for l in lines)
        total_c = sum(l["credit"] for l in lines)
        diff = (total_d - total_c).quantize(MILLIME, rounding=ROUND_HALF_UP)

        error_reason = None
        if diff == ZERO:
            balanced = True
        elif abs(diff) == MILLIME:
            if diff > ZERO:
                lines.append({"account": ACC_ROUND, "label": LBL_ROUND, "debit": ZERO, "credit": abs(diff)})
            else:
                lines.append({"account": ACC_ROUND, "label": LBL_ROUND, "debit": abs(diff), "credit": ZERO})
            balanced = True
        else:
            balanced = False
            error_reason = f"Solde anormal: {diff} (attendu 0.000 ou 0.001)"

        client_raw = first.get("client", "")
        libelle = client_raw.split("|", 1)[-1].strip().upper() if "|" in client_raw else client_raw.strip().upper()
        piece = ref.split("/")[0].strip() if "/" in ref else ref.strip()

        # Determine Journal: CA if cash, else VT for Vente, AC for Achat
        journal_code = "CA" if is_cash_entry else ("VT" if doc_type == "Vente" else "AC")

        entries.append({
            "docRef": ref,
            "date": first.get("date", ""),
            "journal": journal_code,
            "libelle": libelle,
            "piece": piece,
            "balanced": balanced,
            "error_reason": error_reason,
            "lines": lines,
            "is_cash": is_cash_entry  # Flag for UI automation
        })

    n_unbalanced = sum(1 for e in entries if not e["balanced"])
    log(f"Parsed {len(entries)} entries from CSV ({n_unbalanced} unbalanced)")
    for e in entries:
        if not e["balanced"]:
            log(f"  ⚠️ {e['docRef']}: {e['error_reason']}")
    return entries
    