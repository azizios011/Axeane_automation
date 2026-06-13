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
        await wait(page, 400)
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
        await wait(page, 400)
    except PWTimeout:
        log("  ⚠️ Spinner timeout, proceeding anyway")

async def eval_scope(page: Page, body: str, args: list = None) -> dict:
    # Ensure args is always 5 elements to match the JS signature [a0, a1, a2, a3, a4]
    if args is None: args = []
    while len(args) < 5: args.append(None)

    js = f"""(args) => {{
        const [a0, a1, a2, a3, a4] = args;
        const root = document.querySelector('{SCOPE_ROOT_SELECTOR}');
        if (!root) return {{ ok: false, error: 'root-not-found' }};
        const scope = angular.element(root).scope();
        if (!scope) return {{ ok: false, error: 'scope-not-found' }};
        
        let result;
        try {{
            result = (function(scope, a0, a1, a2, a3, a4) {{
                {body}
            }})(scope, a0, a1, a2, a3, a4);
        }} catch (e) {{
            return {{ ok: false, error: e.message, stack: e.stack }};
        }}
        
        if (!scope.$root.$$phase) scope.$apply();
        return {{ ok: true, result: result }};
    }}"""

    return await page.evaluate(js, args)


# ─────────────────────────────────────────────────────────────────────────
# Navigation & Login
# ─────────────────────────────────────────────────────────────────────────

async def nya_select_by_js(page: Page, ol_id: str, option_text: str) -> None:
    success = await page.evaluate("""([olId, text]) => {
        const ol = document.getElementById(olId);
        if (!ol) return false;
        const options = ol.querySelectorAll('li.nya-bs-option a');
        for (const a of options) {
            if (a.textContent.trim().toLowerCase().includes(text.toLowerCase().trim())) {
                a.click();
                const scope = angular.element(ol).scope();
                if (scope && !scope.$root.$$phase) scope.$apply();
                return true;
            }
        }
        return false;
    }""", [ol_id, option_text])
    await wait(page, 500)

async def do_login(page: Page) -> None:
    if await page.locator("#loginInput").count() == 0: return
    log(f"Logging in as {SETTINGS.get('axeane_user')}...")
    await page.locator("#loginInput").fill(SETTINGS.get("axeane_user"))
    await page.locator("#passwordInput").fill(SETTINGS.get("axeane_password"))
    await page.locator("button[aria-label='Connexion']").click()
    await page.wait_for_selector(".nax-side-bar-menu", timeout=30000)

async def select_context(page: Page) -> None:
    entreprise = SETTINGS.get("axeane_entreprise", "CPR")
    exercice = SETTINGS.get("axeane_exercice", "EX 2026")
    log(f"Selecting context: {entreprise} / {exercice}")
    
    # Open sidebar if closed
    if not await page.evaluate("$('.nax-side-bar-menu').hasClass('nax-side-bar-menu-active')"):
        await page.evaluate("document.getElementById('menuBtn').click()")
        await wait(page, 800)

    await nya_select_by_js(page, "entreprise", entreprise)
    await wait(page, 800)
    await nya_select_by_js(page, "exercice", exercice)
    await wait(page, 800)

async def navigate_to_saisie(page: Page) -> None:
    log("Navigating to Saisie des écritures...")
    await page.evaluate("""() => {
        const items = document.querySelectorAll('.nax-main-menu-item span.ng-binding');
        for (const item of items) {
            if (item.textContent.trim() === 'Comptabilité générale') {
                item.closest('.nax-main-menu-item').click();
                return true;
            }
        }
    }""")
    await wait(page, 1000)
    await page.evaluate("document.querySelector(\".kc-dock-item[data-code='ECRITURE_AVANCEE']\").click()")
    await page.wait_for_selector(SCOPE_ROOT_SELECTOR, timeout=15000)

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

# ─────────────────────────────────────────────────────────────────────────
# Entry Logic
# ─────────────────────────────────────────────────────────────────────────

async def reset_form(page: Page) -> None:
    log("  🧹 Resetting form...")
    await eval_scope(page, "scope.resetEcritures(); scope.unsetModele();")
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
    parts = entry["date"].split("/")
    # Injects: Journal, Day, Month, Piece, Libelle
    res = await eval_scope(page, """
        const entId = scope.contextComptable.currentEntreprise.entrepriseId;
        const jour = scope.mapCodeJournauxEntreprise[entId].find(j => j.code === a0);
        if (jour) {
            scope.ecritureGrouping.journal = jour;
            scope.JournalCodeChanges();
        }
        scope.items.jourDocComptable = a1;
        scope.items.selectedMoisDocComptable = scope.moisList[parseInt(a2) - 1];
        scope.ecritureGrouping.piece = a3;
        scope.ecritureGrouping.libelle = a4;
        return true;
    """, [entry["journal"], parts[0], parts[1], entry["piece"], entry["libelle"]])
    log(f"  ✅ JS: Header Injected ({parts[0]}/{parts[1]})")
    await wait_for_spinner(page)

async def fill_line(page: Page, idx: int, line: dict) -> None:
    # Arguments: Account, Debit, Credit, Label, Index
    res = await eval_scope(page, """
        scope.ajouterEcriture();
        const row = scope.ecritureGrouping.ecritureComptables[scope.ecritureGrouping.ecritureComptables.length - 1];
        
        row.debit = parseFloat(a1) || 0;
        row.credit = parseFloat(a2) || 0;
        row.extraLibelle = a3;

        // Smart Account Matcher
        const entId = scope.contextComptable.currentEntreprise.entrepriseId;
        const list = scope.model.mapComptesComptableEntreprise[entId] || [];
        const match = list.find(c => (c.compteComptable || c.numCompte || '').startsWith(a0));

        if (match && scope.onSelectCompteComptable) {
            // Replicate exactly what Axeane does when you click an account
            scope.onSelectCompteComptable(match, match.dernierCompteLibelle || match.libelle, null, 0, row);
            if (scope.noNeedTreasuryOperation) scope.noNeedTreasuryOperation(row, 0);
            if (scope.calculateTotalDebit) scope.calculateTotalDebit(true, row, false);
            if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, row, false);
            return { found: true, code: a0 };
        }
        return { found: false, code: a0 };
    """, [line["account"], str(line["debit"]), str(line["credit"]), line["label"]])

    if not res.get("ok"):
        log(f"    ❌ JS Error in line {idx}: {res.get('error')}")
    elif not res.get("result", {}).get("found"):
        log(f"    ⚠️ Compte {line['account']} not found in Axeane list")

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
    res = await eval_scope(page, """
        return {
            debit: scope.ecritureGrouping.totalDebit || 0,
            credit: scope.ecritureGrouping.totalCredit || 0,
            solde: scope.ecritureGrouping.solde || 0
        };
    """)
    data = res.get("result", {"debit": 0, "credit": 0, "solde": 999})
    is_balanced = abs(data["solde"]) < 0.001
    log(f"  📊 Totals -> D: {data['debit']:.3f} | C: {data['credit']:.3f} | Solde: {data['solde']:.3f}")
    
    if update_ui_callback:
        update_ui_callback(entry['docRef'], 'success' if is_balanced else 'error')
    return is_balanced

async def save_entry(page: Page) -> str | None:
    await wait_for_spinner(page)
    res = await eval_scope(page, "if(scope.saveEcriture) scope.saveEcriture(); return true;")
    await wait(page, 1500)
    # Check for Axeane error modals
    return await page.evaluate("""() => {
        const modal = document.querySelector('.modal.in, .swal2-popup');
        if (modal && /erreur/i.test(modal.textContent)) return modal.textContent.trim();
        return null;
    }""")


# ─────────────────────────────────────────────────────────────────────────
# Main run loop
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None) -> None:
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(SETTINGS.get("cdp_url"))
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page = next((p for p in all_pages if "kompta" in p.url.lower()), all_pages[0])
        await page.bring_to_front()

        await do_login(page)
        await select_context(page)
        await navigate_to_saisie(page)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set(): break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")
            
            await reset_form(page)
            await fill_header(page, entry)
            
            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)

            if await verify_entry(page, entry, update_ui_callback):
                err = await save_entry(page)
                if err: log(f"  ❌ Save Error: {err}")
            else:
                log(f"  ❌ Skipping Save (Unbalanced)")
                