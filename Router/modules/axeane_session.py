import asyncio
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

SCOPE_ROOT_SELECTOR = ".td-root"


async def wait(page: Page, ms: int = None) -> None:
    delay = ms if ms is not None else SETTINGS.get("slow_mo", 300)
    await page.wait_for_timeout(delay)


async def wait_for_spinner(page: Page, timeout: int = 60000) -> None:
    try:
        await page.wait_for_function(
            """() => {
                const spinners = document.querySelectorAll('.nx-modern-spinner-modal, .modal.in, [uib-modal-window], .loading-spinner');
                for (const el of spinners) {
                    if (el.offsetParent !== null) return false;
                }
                return true;
            }""",
            timeout=timeout,
        )
    except PWTimeout:
        pass


async def eval_scope(page: Page, body: str, args: list = None) -> dict:
    """
    JS-Hook core: resolves the EcritureMainControllerModel2 $scope from
    `.td-root` and runs `body` as the body of function(scope, a0, a1, ...).
    Auto $apply()s if a digest isn't already running.

    Returns {"ok": bool, "result": ..., "error": ...}
    """
    arg_names = ["a0", "a1", "a2", "a3", "a4"]
    n_args = len(args) if args else 0
    fn_args = ", ".join(arg_names[:n_args])

    js = f"""([{fn_args}]) => {{
        const root = document.querySelector('{SCOPE_ROOT_SELECTOR}');
        if (!root) return {{ ok: false, error: 'root-not-found' }};
        const scope = angular.element(root).scope();
        if (!scope) return {{ ok: false, error: 'scope-not-found' }};
        let result;
        try {{
            result = (function(scope, {fn_args}) {{
                {body}
            }})(scope, {fn_args});
        }} catch (e) {{
            return {{ ok: false, error: String(e) }};
        }}
        if (!scope.$root.$$phase) scope.$apply();
        return {{ ok: true, result: result }};
    }}"""

    return await page.evaluate(js, args or [])


async def reset_form(page: Page) -> None:
    """JS-Hook: Wipes the Angular Model clean."""
    log("  🧹 JS: Resetting form state...")
    await eval_scope(page, """
        if (scope.resetEcritures) scope.resetEcritures();
        if (scope.unsetModele) scope.unsetModele();
    """)
    await page.keyboard.press("Escape")
    await wait_for_spinner(page)


async def select_journal(page: Page, journal_code: str) -> bool:
    """JS-Hook: Picks the journal object from the model and runs its ng-change side effects."""
    res = await eval_scope(page, """
        const entrepriseId = scope.contextComptable.currentEntreprise.entrepriseId;
        const journaux = scope.mapCodeJournauxEntreprise[entrepriseId] || [];
        const needle = String(a0).trim().toUpperCase();
        const match = journaux.find(j => String(j.code || '').trim().toUpperCase() === needle);
        if (!match) return false;

        scope.ecritureGrouping.journal = match;
        if (scope.JournalCodeChanges) scope.JournalCodeChanges();
        if (scope.showMvtManuelCheckBox) scope.showMvtManuelCheckBox();
        return true;
    """, [journal_code])

    ok = bool(res.get("ok") and res.get("result"))
    if not ok:
        log(f"    ⚠️ JS: Journal '{journal_code}' not found ({res.get('error')})")
    await wait(page, 200)
    return ok


async def select_devise(page: Page, devise_code: str) -> bool:
    """JS-Hook: Picks the devise object from the model and runs its ng-change side effects."""
    res = await eval_scope(page, """
        const devises = scope.listDevises || [];
        const needle = String(a0).trim().toUpperCase();
        const match = devises.find(d => String(d.code || '').trim().toUpperCase() === needle);
        if (!match) return false;

        scope.ecritureGrouping.deviseObj = match;
        if (scope.deviseCodeChanges) scope.deviseCodeChanges(match);
        if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, null);
        if (scope.calculateTotalDebit) scope.calculateTotalDebit(true, null);
        return true;
    """, [devise_code])

    ok = bool(res.get("ok") and res.get("result"))
    if not ok:
        log(f"    ⚠️ JS: Devise '{devise_code}' not found ({res.get('error')})")
    return ok


async def fill_header(page: Page, entry: dict) -> None:
    """JS-Hook: Injects Journal, Devise, Jour, Mois, Ref and Libelle directly into the Angular model."""
    await wait_for_spinner(page)

    await select_journal(page, entry["journal"])
    if entry.get("devise"):
        await select_devise(page, entry["devise"])

    parts = entry["date"].split("/")
    jour = parts[0]
    month_idx = int(parts[1])  # 01=Jan in CSV -> moisList[0]

    res = await eval_scope(page, """
        scope.items.jourDocComptable = a0;
        scope.items.selectedMoisDocComptable = scope.moisList[a1 - 1];
        scope.ecritureGrouping.piece = a2;
        scope.ecritureGrouping.libelle = a3;

        if (scope.checkMoisCloture) scope.checkMoisCloture();
        if (scope.deviseCodeChanges) scope.deviseCodeChanges(scope.ecritureGrouping.deviseObj);
        if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, null);
        if (scope.calculateTotalDebit) scope.calculateTotalDebit(true, null);
        if (scope.updateLibelleEc) scope.updateLibelleEc();
        return true;
    """, [jour, month_idx, entry["piece"], entry["libelle"]])

    if not res.get("ok"):
        log(f"    ⚠️ JS: Header injection error: {res.get('error')}")

    log(f"  ✅ JS: Header Injected ({jour} / {month_idx})")
    await wait_for_spinner(page)


async def fill_line(page: Page, idx: int, line: dict) -> None:
    """JS-Hook: Adds a row and populates compte/libelle/debit/credit via the model + scope handlers."""

    # 1. Add row
    add_res = await eval_scope(page, """
        scope.ajouterEcriture();
        return scope.ecritureGrouping.ecritureComptables.length - 1;
    """)
    if not add_res.get("ok"):
        log(f"    ⚠️ JS: Could not add row: {add_res.get('error')}")
        return
    row_index = add_res["result"]

    # 2. Resolve compte from the same source array the typeahead uses, then
    #    replay the typeahead-on-select handler + amount/tax recalculation.
    res = await eval_scope(page, """
        const entrepriseId = scope.contextComptable.currentEntreprise.entrepriseId;
        const comptes = (scope.model && scope.model.mapComptesComptableEntreprise[entrepriseId]) || [];
        const needle = String(a1).trim().toUpperCase();

        const match = comptes.find(c => {
            const code = String(c.compteComptable || c.numCompte || c.code || '').trim().toUpperCase();
            const lib = String(c.dernierCompteLibelle || '').trim().toUpperCase();
            return code === needle || code.startsWith(needle) || lib.startsWith(needle);
        });

        const row = scope.ecritureGrouping.ecritureComptables[a0];
        if (!row) return { found: false, reason: 'row-missing' };

        row.extraLibelle = a2;
        row.debit = a3;
        row.credit = a4;

        if (!match) return { found: false, reason: 'account-not-found' };

        if (scope.onSelectCompteComptable) {
            scope.onSelectCompteComptable(match, match.dernierCompteLibelle, null, a0, row);
        } else {
            row.comptesComptable = match;
        }
        if (scope.noNeedTreasuryOperation) scope.noNeedTreasuryOperation(row, a0);

        if (scope.calculateTotalDebit) scope.calculateTotalDebit(true, row, false);
        if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, row, false);
        if (scope.calculTauxTax) scope.calculTauxTax(row);

        return { found: true };
    """, [row_index, line["account"], line["label"], str(line["debit"]), str(line["credit"])])

    if not res.get("ok"):
        log(f"    ⚠️ JS: fill_line error: {res.get('error')}")
        return

    if not res["result"].get("found"):
        log(f"    ⚠️ JS: Compte '{line['account']}' not found in mapComptesComptableEntreprise — left as text only")

    await wait_for_spinner(page)


async def verify_entry(page: Page, entry: dict, update_ui_callback):
    """JS-Hook: Sums débit/crédit straight from the ecritureComptables model."""
    ref = entry['docRef']
    if update_ui_callback:
        update_ui_callback(ref, 'processing')

    res = await eval_scope(page, """
        const lines = scope.ecritureGrouping.ecritureComptables || [];
        let debit = 0, credit = 0;
        for (const l of lines) {
            debit += parseFloat(String(l.debit || '0').replace(',', '.')) || 0;
            credit += parseFloat(String(l.credit || '0').replace(',', '.')) || 0;
        }
        return { debit, credit, count: lines.length };
    """)

    if not res.get("ok"):
        log(f"  ⚠️ JS: verify_entry error: {res.get('error')}")
        if update_ui_callback:
            update_ui_callback(ref, 'error')
        return False

    totals = res["result"]
    is_balanced = abs(totals["debit"] - totals["credit"]) < 0.001 and totals["debit"] > 0
    log(f"  📊 Verification -> Débit: {totals['debit']:.3f} | Crédit: {totals['credit']:.3f} | Balanced: {is_balanced}")

    if update_ui_callback:
        update_ui_callback(ref, 'success' if is_balanced else 'error')
    return is_balanced


async def save_entry(page: Page) -> str | None:
    """JS-Hook: Calls saveEcriture() on the scope directly instead of clicking the button."""
    await wait_for_spinner(page)

    res = await eval_scope(page, """
        if (scope.disabledSaveEcriture) return { saved: false, reason: 'disabled' };
        if (!scope.saveEcriture) return { saved: false, reason: 'no-save-fn' };
        scope.saveEcriture();
        return { saved: true };
    """)

    if not res.get("ok") or not res["result"].get("saved"):
        reason = res.get("error") or res.get("result", {}).get("reason")
        log(f"  ⚠️ JS: saveEcriture() not triggered ({reason})")
        return f"save-not-triggered:{reason}"

    await wait(page, 1000)

    # Server-side validation errors still surface as a modal — reading its
    # text is just error reporting, not form scraping.
    return await page.evaluate("""() => {
        const modal = document.querySelector('.modal.in, .swal2-popup');
        if (modal && /erreur/i.test(modal.textContent)) {
            const btn = modal.querySelector('button');
            if (btn) btn.click();
            return modal.textContent.trim();
        }
        return null;
    }""")


async def debug_dump_compte_shape(page: Page, sample_size: int = 3) -> None:
    """
    One-off diagnostic: logs the shape of the first few entries in
    mapComptesComptableEntreprise so the account-matching heuristic in
    fill_line() can be tightened to the real field names.
    Enable via settings.json -> "debug_compte_shape": true
    """
    res = await eval_scope(page, """
        const entrepriseId = scope.contextComptable.currentEntreprise.entrepriseId;
        const comptes = (scope.model && scope.model.mapComptesComptableEntreprise[entrepriseId]) || [];
        return comptes.slice(0, a0);
    """, [sample_size])

    if not res.get("ok"):
        log(f"  ⚠️ JS: debug_dump_compte_shape error: {res.get('error')}")
        return

    log(f"  🔎 mapComptesComptableEntreprise sample ({len(res['result'])} items):")
    for i, item in enumerate(res["result"]):
        log(f"    [{i}] {item}")

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None) -> None:
    cdp_url = SETTINGS.get("cdp_url", "http://localhost:9222")
    async with async_playwright() as pw:
        log(f"Connecting to CDP at {cdp_url}...")
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page: Page = next((p for p in all_pages if "axeane" in p.url.lower() or "kompta" in p.url.lower()), all_pages[0])

        if browser_log_callback:
            page.on("console", lambda msg: browser_log_callback(f"🌐 BROWSER: {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda exc: browser_log_callback(f"💥 PAGE CRASH: {exc}"))

        await page.bring_to_front()

        if SETTINGS.get("debug_compte_shape"):
            await debug_dump_compte_shape(page)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set():
                break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")

            await reset_form(page)
            await fill_header(page, entry)

            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)

            if await verify_entry(page, entry, update_ui_callback):
                err = await save_entry(page)
                if err:
                    log(f"  ❌ Save Error: {err}")
            else:
                log("  ❌ Unbalanced in UI, skipping save.")
                