import asyncio
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

SCOPE_ROOT_SELECTOR = ".td-root"

# ─────────────────────────────────────────────────────────────────────────
# JS Bridge & Helpers
# ─────────────────────────────────────────────────────────────────────────

async def wait_for_spinner(page: Page, timeout: int = 60000) -> None:
    """Wait for Axeane loading spinners/modals to disappear."""
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
    except:
        pass

async def eval_scope(page: Page, body: str, args: list = None) -> dict:
    """Talks directly to the EcritureMainControllerModel2 scope."""
    if args is None: args = []
    while len(args) < 5: args.append(None)
    js = f"""(args) => {{
        const [a0, a1, a2, a3, a4] = args;
        const root = document.querySelector('{SCOPE_ROOT_SELECTOR}');
        if (!root) return {{ ok: false, error: 'root-not-found' }};
        const scope = angular.element(root).scope();
        if (!scope) return {{ ok: false, error: 'scope-not-found' }};
        try {{
            const result = (function(scope, a0, a1, a2, a3, a4) {{ {body} }})(scope, a0, a1, a2, a3, a4);
            if (!scope.$root.$$phase) scope.$apply();
            return {{ ok: true, result }};
        }} catch (e) {{ return {{ ok: false, error: e.message }}; }}
    }}"""
    return await page.evaluate(js, args)

# ─────────────────────────────────────────────────────────────────────────
# Sidebar & Context Selection
# ─────────────────────────────────────────────────────────────────────────

async def force_clean_ui(page: Page):
    """Removes blocking modals, backdrops, or shadows."""
    await page.evaluate("""() => {
        document.querySelectorAll('.modal-backdrop, .nx-modern-spinner-modal').forEach(el => el.remove());
        document.querySelectorAll('.modal.in').forEach(el => el.classList.remove('in'));
        document.body.classList.remove('modal-open');
    }""")

async def nya_select_sidebar(page: Page, ol_id: str, text: str):
    """Selects Entreprise/Exercice using the sidebar search box."""
    try:
        container = f".axe-sidebar #{ol_id}"
        button = f"{container} button.dropdown-toggle"
        search = f"{container} .bs-searchbox input"
        
        await page.wait_for_selector(button, timeout=5000)
        await page.evaluate(f"document.querySelector('{button}').click()")
        await asyncio.sleep(0.5)
        
        if await page.locator(search).is_visible():
            await page.locator(search).fill(text)
            await asyncio.sleep(0.5)
            await page.keyboard.press("Enter")
            await asyncio.sleep(0.5)

        # Check if dropdown is still open (Enter failed)
        is_open = await page.locator(f"{container} .dropdown-menu.open").count() > 0
        if is_open:
            log(f"    ⚠️ Enter key didn't close dropdown, forcing JS click...")
            await page.evaluate("""([id, val]) => {
                const options = document.querySelectorAll(`#${id} li.nya-bs-option:not(.ng-hide) a`);
                for (const a of options) {
                    if (a.textContent.trim().toUpperCase().includes(val.toUpperCase())) {
                        a.click(); return true;
                    }
                }
                if (options[0]) { options[0].click(); return true; }
                return false;
            }""", [ol_id, text])
        return True
    except: return False

async def select_context(page: Page):
    entreprise = SETTINGS.get("axeane_entreprise", "CPR")
    exercice = SETTINGS.get("axeane_exercice", "EX 2026")
    
    log(f"Setting Context: {entreprise} / {exercice}")
    await force_clean_ui(page)
    
    # Open sidebar
    is_open = await page.evaluate("$('.axe-sidebar').hasClass('nax-side-bar-menu-active')")
    if not is_open:
        await page.evaluate("document.getElementById('menuBtn').click()")
        await page.wait_for_selector(".axe-sidebar.nax-side-bar-menu-active")

    # Select Entreprise
    if await nya_select_sidebar(page, "entreprise", entreprise):
        log("    ✅ Entreprise selected.")
        await wait_for_spinner(page)
        await asyncio.sleep(1.5)
    
    # Select Exercice
    if await nya_select_sidebar(page, "exercice", exercice):
        log("    ✅ Exercice selected.")
        await wait_for_spinner(page)
        await asyncio.sleep(0.5)

    # Close sidebar
    await page.evaluate("document.getElementById('menuBtn').click()")

# ─────────────────────────────────────────────────────────────────────────
# Accounting Form Logic
# ─────────────────────────────────────────────────────────────────────────

async def fill_header(page: Page, entry: dict):
    parts = entry["date"].split("/")
    piece = entry["piece"].split("/")[0]
    libelle = entry["libelle"].split("|")[-1].strip()

    await eval_scope(page, """
        const entId = scope.contextComptable.currentEntreprise.entrepriseId;
        const jour = scope.mapCodeJournauxEntreprise[entId].find(j => j.code === a0);
        if (jour) { scope.ecritureGrouping.journal = jour; scope.JournalCodeChanges(); }
        scope.items.jourDocComptable = a1;
        scope.items.selectedMoisDocComptable = scope.moisList[parseInt(a2) - 1];
        scope.ecritureGrouping.piece = a3;
        scope.ecritureGrouping.libelle = a4;
        if(!scope.ecritureGrouping.deviseObj) {
            scope.ecritureGrouping.deviseObj = scope.listDevises.find(d => d.code === 'TND');
        }
    """, [entry["journal"], parts[0], parts[1], piece, libelle])
    log(f"  ✅ Header: {piece} | {libelle}")

async def fill_line(page: Page, idx: int, line: dict):
    res = await eval_scope(page, """
        let row = scope.ecritureGrouping.ecritureComptables[a4];
        if (!row) { scope.ajouterEcriture(); row = scope.ecritureGrouping.ecritureComptables[a4]; }
        row.debit = parseFloat(a1) || 0;
        row.credit = parseFloat(a2) || 0;
        row.extraLibelle = a3;
        const entId = scope.contextComptable.currentEntreprise.entrepriseId;
        const list = scope.model.mapComptesComptableEntreprise[entId] || [];
        const match = list.find(c => (c.compteComptable || '').startsWith(a0));
        if (match) {
            scope.onSelectCompteComptable(match, match.dernierCompteLibelle || match.libelle, null, a4, row);
            if (scope.calculateTotalDebit) scope.calculateTotalDebit(true, row, false);
            if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, row, false);
            return true;
        }
        return false;
    """, [line["account"], str(line["debit"]), str(line["credit"]), line["label"], idx])

    if not res.get("result"):
        log(f"    ⚠️ Account {line['account']} not found.")

async def verify_and_save(page: Page, ref: str, callback) -> bool:
    kpis = await page.evaluate("""() => {
        const solde = document.querySelector('.ax-badge-kpi.ax-badge-purple .ax-badge-kpi-value');
        const d = document.querySelector('.ax-badge-kpi.ax-badge-green .ax-badge-kpi-value');
        const c = document.querySelector('.ax-badge-kpi.ax-badge-red .ax-badge-kpi-value');
        return {
            solde: solde ? solde.textContent.trim() : "999",
            d: d ? d.textContent.trim() : "0",
            c: c ? c.textContent.trim() : "0"
        };
    }""")
    is_bal = "0,000" in kpis['solde']
    log(f"  📊 Balanced: {is_bal} (S:{kpis['solde']} D:{kpis['d']} C:{kpis['c']})")
    if callback: callback(ref, 'success' if is_bal else 'error')
    if is_bal:
        await eval_scope(page, "scope.saveEcriture();")
        await wait_for_spinner(page)
        await asyncio.sleep(1)
        return True
    return False

# ─────────────────────────────────────────────────────────────────────────
# Main Runner
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None):
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(SETTINGS.get("cdp_url"))
        page = next(p for ctx in browser.contexts for p in ctx.pages if "kompta" in p.url.lower())
        await page.bring_to_front()
        
        # Simple Login check
        if await page.locator("#loginInput").count() > 0:
            await page.locator("#loginInput").fill(SETTINGS.get("axeane_user"))
            await page.locator("#passwordInput").fill(SETTINGS.get("axeane_password"))
            await page.click("button[aria-label='Connexion']")
            await page.wait_for_selector(".nax-side-bar-menu")

        await select_context(page)
        
        # Navigate to form
        await page.evaluate("""() => {
            const m = [...document.querySelectorAll('.nax-main-menu-item span')].find(s => s.textContent.includes('Comptabilité'));
            if(m) m.click();
        }""")
        await asyncio.sleep(1)
        await page.click(".kc-dock-item[data-code='ECRITURE_AVANCEE']")
        await page.wait_for_selector(SCOPE_ROOT_SELECTOR)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set(): break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")
            await eval_scope(page, "scope.resetEcritures(); scope.unsetModele();")
            await fill_header(page, entry)
            for idx, line in enumerate(entry["lines"]):
                await fill_line(page, idx, line)
            await verify_and_save(page, entry['docRef'], update_ui_callback)
            