import asyncio
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

SCOPE_ROOT_SELECTOR = ".td-root"


# ─────────────────────────────────────────────────────────────────────────
# Generic helpers
# ─────────────────────────────────────────────────────────────────────────

async def wait(page: Page, ms: int = None) -> None:
    delay = ms if ms is not None else SETTINGS.get("slow_mo", 300)
    await page.wait_for_timeout(delay)


async def wait_for_spinner(page: Page, timeout: int = 60000) -> None:
    try:
        await wait(page, 300)
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
        await wait(page, 300)
    except PWTimeout:
        log("  ⚠️ Spinner timeout, proceeding anyway")


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


async def nya_select_by_js(page: Page, ol_id: str, option_text: str) -> None:
    """
    DOM-click based dropdown select — used ONLY for sidebar/login widgets
    (Entreprise/Exercice selector) that live outside EcritureMainControllerModel2,
    where eval_scope's .td-root lookup doesn't apply.
    """
    log(f"    Searching for '{option_text}' in dropdown #{ol_id}...")

    success = await page.evaluate("""([olId, text]) => {
        const ol = document.getElementById(olId);
        if (!ol) return false;

        const options = ol.querySelectorAll('li.nya-bs-option a');
        for (const a of options) {
            const itemText = a.textContent.trim().toLowerCase();
            const targetText = text.trim().toLowerCase();
            if (itemText.includes(targetText)) {
                a.click();
                const scope = angular.element(ol).scope();
                if (scope && !scope.$root.$$phase) scope.$apply();
                return true;
            }
        }
        return false;
    }""", [ol_id, option_text])

    if not success:
        log(f"    ⚠️ WARNING: Could not find '{option_text}' in #{ol_id}")
    await wait(page, 500)


# ─────────────────────────────────────────────────────────────────────────
# Login / navigation (restored from pre-JS-hook version)
# ─────────────────────────────────────────────────────────────────────────

async def get_current_context(page: Page) -> tuple[str, str]:
    """Reads the currently selected Entreprise and Exercice from the header chips."""
    try:
        await page.wait_for_selector(".ctx-chip-entreprise .ctx-chip-text", timeout=10000)
        context = await page.evaluate("""() => {
            const entEl = document.querySelector('.ctx-chip-entreprise .ctx-chip-text');
            const exeEl = document.querySelector('.ctx-chip-exercice .ctx-chip-text');
            return {
                entreprise: entEl ? entEl.textContent.trim() : 'Unknown',
                exercice: exeEl ? exeEl.textContent.trim() : 'Unknown'
            };
        }""")
        return context.get("entreprise", "Unknown"), context.get("exercice", "Unknown")
    except Exception as e:
        log(f"Warning: Could not detect context: {e}")
        return "Unknown", "Unknown"


async def do_login(page: Page) -> None:
    if await page.locator("#loginInput").count() == 0:
        log("Already logged in")
        return

    user = SETTINGS.get("axeane_user", "")
    password = SETTINGS.get("axeane_password", "")
    log(f"Logging in as {user}...")

    await page.locator("#loginInput").fill(user)
    await page.locator("#passwordInput").fill(password)

    try:
        await page.wait_for_function(
            "() => { const inp = document.querySelector('input[name=\"cf-turnstile-response\"]'); return inp && inp.value && inp.value.length > 10; }",
            timeout=20_000,
        )
        log("Turnstile resolved")
    except PWTimeout:
        log("WARNING: Turnstile timeout — attempting login anyway")

    await page.locator("button[aria-label='Connexion']").click()
    try:
        await page.wait_for_function(
            "() => { const m = document.getElementById('loginModal'); return !m || m.getAttribute('aria-hidden') === 'true'; }",
            timeout=30_000,
        )
        log("Login successful")
    except PWTimeout:
        raise RuntimeError("Login failed — check credentials")
    await wait(page, 1000)


async def select_context(page: Page) -> None:
    entreprise = SETTINGS.get("axeane_entreprise", "CPR")
    exercice = SETTINGS.get("axeane_exercice", "EX 2026")

    if not entreprise or not exercice:
        log("⚠️ Enterprise or Exercice not defined in settings. Skipping automatic selection.")
        return

    log(f"Selecting context: {entreprise} / {exercice}")

    is_open = await page.evaluate("$('.nax-side-bar-menu').hasClass('nax-side-bar-menu-active')")
    if not is_open:
        log("  Sidebar is collapsed. Opening it via JS...")
        await page.evaluate("document.getElementById('menuBtn').click()")
        await wait(page, 800)

    await nya_select_by_js(page, "entreprise", entreprise)
    await wait(page, 800)
    await nya_select_by_js(page, "exercice", exercice)
    await wait(page, 800)

    is_open_after = await page.evaluate("$('.nax-side-bar-menu').hasClass('nax-side-bar-menu-active')")
    if is_open_after:
        await page.evaluate("document.getElementById('menuBtn').click()")
        await wait(page, 500)


async def navigate_to_saisie(page: Page) -> None:
    log("Navigating to Saisie des écritures...")

    sidebar = page.locator(".axe-sidebar.nax-side-bar-menu-active")
    if await sidebar.count() == 0:
        log("  Sidebar is collapsed. Opening it...")
        await page.evaluate("document.getElementById('menuBtn').click()")
        await wait(page, 800)

    log("  Clicking 'Comptabilité générale'...")
    clicked_menu = await page.evaluate("""() => {
        const items = document.querySelectorAll('.nax-main-menu-item span.ng-binding');
        for (const item of items) {
            if (item.textContent.trim() === 'Comptabilité générale') {
                item.closest('.nax-main-menu-item').click();
                return true;
            }
        }
        return false;
    }""")
    if not clicked_menu:
        log("  WARNING: Could not find 'Comptabilité générale' in sidebar.")
    await wait(page, 1000)

    log("  Clicking 'Saisie des écritures'...")
    clicked_saisie = await page.evaluate("""() => {
        const item = document.querySelector(".kc-dock-item[data-code='ECRITURE_AVANCEE']");
        if (item) {
            item.click();
            return true;
        }
        return false;
    }""")
    if not clicked_saisie:
        log("  WARNING: Could not find 'Saisie des écritures' in dock panel.")
    await wait(page, 1500)

    # Confirm .td-root actually exists now — this is what every eval_scope() call needs.
    try:
        await page.wait_for_selector(SCOPE_ROOT_SELECTOR, timeout=15000)
        log("✅ Saisie des écritures opened")
    except PWTimeout:
        log(f"  ❌ '{SCOPE_ROOT_SELECTOR}' still not found after navigation — automation will fail with root-not-found")


# ─────────────────────────────────────────────────────────────────────────
# Modal handling
# ─────────────────────────────────────────────────────────────────────────

async def close_blocking_modals(page: Page):
    """Detects and closes Axeane error/info popups that block the UI."""
    modals = page.locator(".modal.in, .swal2-container")
    if await modals.count() > 0:
        log("  ⚠️ Closing blocking modal...")
        close_btn = page.locator(".modal.in button.close, .modal.in button:has-text('Fermer'), .swal2-confirm, .swal2-close")
        if await close_btn.count() > 0:
            await close_btn.first.click()
            await page.wait_for_timeout(500)


# ─────────────────────────────────────────────────────────────────────────
# JS-Hook form filling (EcritureMainControllerModel2 $scope)
# ─────────────────────────────────────────────────────────────────────────

async def reset_form(page: Page) -> None:
    """JS-Hook: Wipes the Angular Model clean, plus closes any leftover modals."""
    log("  🧹 Resetting form for next entry...")
    await wait_for_spinner(page)
    await close_blocking_modals(page)

    res = await eval_scope(page, """
        if (scope.resetEcritures) scope.resetEcritures();
        if (scope.unsetModele) scope.unsetModele();
        return true;
    """)
    if not res.get("ok"):
        log(f"    ⚠️ JS: reset_form error: {res.get('error')}")

    await page.keyboard.press("Escape")
    await wait_for_spinner(page)
    log("  ✅ Form ready.")


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

    piece = entry.get("piece", entry.get("docRef", ""))
    libelle = entry.get("libelle", entry.get("docRef", ""))

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
    """, [jour, month_idx, piece, libelle])

    if not res.get("ok"):
        log(f"    ⚠️ JS: Header injection error: {res.get('error')}")

    log(f"  ✅ JS: Header Injected ({jour} / {month_idx})")
    await wait_for_spinner(page)


async def fill_line(page: Page, idx: int, line: dict) -> None:
    """JS-Hook: Adds a row and populates compte/libelle/debit/credit via the model + scope handlers."""

    add_res = await eval_scope(page, """
        scope.ajouterEcriture();
        return scope.ecritureGrouping.ecritureComptables.length - 1;
    """)
    if not add_res.get("ok"):
        log(f"    ⚠️ JS: Could not add row: {add_res.get('error')}")
        return
    row_index = add_res["result"]

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


async def cleanup_extra_rows(page: Page, needed: int) -> None:
    """JS-Hook: trims ecritureComptables down to `needed` rows (safety net)."""
    res = await eval_scope(page, """
        const lines = scope.ecritureGrouping.ecritureComptables || [];
        const removed = lines.length - a0;
        if (removed > 0) {
            lines.splice(a0, removed);
            if (scope.calculateTotalDebit) scope.calculateTotalDebit(true, null);
            if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, null);
        }
        return removed > 0 ? removed : 0;
    """, [needed])

    if res.get("ok") and res.get("result"):
        log(f"  🗑️ Trimmed {res['result']} leftover row(s)")


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

    await wait(page, 1500)
    await wait_for_spinner(page)

    return await page.evaluate("""() => {
        const candidates = document.querySelectorAll('.modal, .ax-modal, [role="alertdialog"], .swal2-popup');
        for (const el of candidates) {
            if (el.offsetParent === null) continue;
            const text = el.textContent || '';
            if (/erreur/i.test(text)) {
                const closeBtn = el.querySelector('.close, button[aria-label="Close"], .swal2-confirm, .swal2-close');
                if (closeBtn) closeBtn.click();
                return text.trim().replace(/\\s+/g, ' ');
            }
        }
        return null;
    }""")


# ─────────────────────────────────────────────────────────────────────────
# Main run loop
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None) -> None:
    cdp_url = SETTINGS.get("cdp_url", "http://localhost:9222")
    async with async_playwright() as pw:
        log(f"Connecting to CDP at {cdp_url}...")
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page: Page = next(
            (p for p in all_pages if "axeane" in p.url.lower() or "kompta" in p.url.lower()),
            all_pages[0] if all_pages else None,
        )
        if page is None:
            raise RuntimeError("No page found. Is Axeane Kompta open?")

        if browser_log_callback:
            page.on("console", lambda msg: browser_log_callback(f"🌐 BROWSER: {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda exc: browser_log_callback(f"💥 PAGE CRASH: {exc}"))

        log(f"Connected to: {page.url}")
        await page.bring_to_front()

        # ── Initial setup navigation ────────────────────────────────────
        await do_login(page)
        await select_context(page)
        ent, exe = await get_current_context(page)
        log(f"Context: {ent} / {exe}")
        await navigate_to_saisie(page)

        total = len(entries)
        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set():
                log("🛑 Automation stopped by user.")
                break

            if not entry.get("balanced", True):
                log(f"SKIP {entry['docRef']} — not balanced locally ({entry.get('error_reason')})")
                if update_ui_callback:
                    update_ui_callback(entry['docRef'], 'error')
                continue

            log(f"[{i+1}/{total}] {entry['docRef']} — {len(entry['lines'])} lines")

            await reset_form(page)
            await fill_header(page, entry)

            for j, line in enumerate(entry["lines"]):
                log(f"  line {j}: {line['account']} D:{line['debit']} C:{line['credit']}")
                await fill_line(page, j, line)

            await cleanup_extra_rows(page, len(entry["lines"]))

            if await verify_entry(page, entry, update_ui_callback):
                err = await save_entry(page)
                if err:
                    log(f"  ❌ Axeane rejected save for {entry['docRef']}: {err}")
                    if update_ui_callback:
                        update_ui_callback(entry['docRef'], 'error')
            else:
                log(f"  ❌ SKIPPING SAVE: Entry {entry['docRef']} is not balanced in Axeane UI!")

        log("Done — all entries processed.")
        