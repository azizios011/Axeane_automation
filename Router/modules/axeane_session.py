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
    """Wait for Axeane loading spinners/modals to disappear."""
    try:
        await wait(page, 400)
        await page.wait_for_function(
            """() => !document.querySelector('.nx-modern-spinner-modal, .modal.in, .loading-spinner') || 
               [...document.querySelectorAll('.nx-modern-spinner-modal, .modal.in')].every(el => el.offsetParent === null)""",
            timeout=timeout,
        )
        await wait(page, 400)
    except PWTimeout:
        pass

async def eval_scope(page: Page, body: str, args: list = None) -> dict:
    """The bridge to communicate directly with Axeane's AngularJS brain."""
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
# Navigation & Context (Sidebar & Login)
# ─────────────────────────────────────────────────────────────────────────

async def nya_select_by_js(page: Page, ol_id: str, option_text: str) -> None:
    """Handles lazy-loaded dropdowns by clicking the button first."""
    try:
        container_selector = f"#{ol_id}"
        button_selector = f"{container_selector} button.dropdown-toggle"
        
        await page.wait_for_selector(button_selector, timeout=5000)
        await page.click(button_selector)
        await wait(page, 500) 

        success = await page.evaluate("""([id, text]) => {
            const container = document.getElementById(id);
            if (!container) return false;
            const options = container.querySelectorAll('li.nya-bs-option a');
            for (const a of options) {
                if (a.textContent.trim().toLowerCase().includes(text.toLowerCase().trim())) {
                    a.click();
                    return true;
                }
            }
            return false;
        }""", [ol_id, option_text])
        
        if not success:
            log(f"    ⚠️ Could not find '{option_text}' in #{ol_id}")
            await page.click(button_selector) # Close it
            
    except Exception as e:
        log(f"    ❌ Error selecting {ol_id}: {str(e)}")

async def do_login(page: Page) -> None:
    if await page.locator("#loginInput").count() == 0: return
    log(f"Logging in as {SETTINGS.get('axeane_user')}...")
    await page.locator("#loginInput").fill(SETTINGS.get("axeane_user"))
    await page.locator("#passwordInput").fill(SETTINGS.get("axeane_password"))
    await page.locator("button[aria-label='Connexion']").click()
    await page.wait_for_selector(".nax-side-bar-menu", timeout=30000)

async def select_context(page: Page) -> None:
    ent, exe = SETTINGS.get("axeane_entreprise", "CPR"), SETTINGS.get("axeane_exercice", "EX 2026")
    log(f"Selecting context: {ent} / {exe}")
    
    if not await page.evaluate("$('.nax-side-bar-menu').hasClass('nax-side-bar-menu-active')"):
        await page.evaluate("document.getElementById('menuBtn').click()")
        await wait(page, 800)

    await nya_select_by_js(page, "entreprise", ent)
    await wait_for_spinner(page) # Important: changing entreprise reloads exercice list
    await wait(page, 1000)

    await nya_select_by_js(page, "exercice", exe)
    await wait_for_spinner(page)
    await wait(page, 800)

async def navigate_to_saisie(page: Page) -> None:
    log("Navigating to Saisie...")
    await page.evaluate("""() => {
        const items = document.querySelectorAll('.nax-main-menu-item span.ng-binding');
        for (const i of items) if (i.textContent.trim() === 'Comptabilité générale') i.closest('.nax-main-menu-item').click();
    }""")
    await wait(page, 1000)
    await page.evaluate("document.querySelector(\".kc-dock-item[data-code='ECRITURE_AVANCEE']\").click()")
    await page.wait_for_selector(SCOPE_ROOT_SELECTOR, timeout=15000)

# ─────────────────────────────────────────────────────────────────────────
# Automation Logic (The Accounting Form)
# ─────────────────────────────────────────────────────────────────────────

async def reset_form(page: Page) -> None:
    log("  🧹 Resetting form...")
    await eval_scope(page, "scope.resetEcritures(); scope.unsetModele();")
    await wait_for_spinner(page)

async def fill_header(page: Page, entry: dict) -> None:
    parts = entry["date"].split("/")
    # Clean Piece (FC000763/2026 -> FC000763) and Libelle (C000120 | NAME -> NAME)
    clean_piece = entry["piece"].split("/")[0]
    clean_libelle = entry["libelle"].split("|")[-1].strip()

    await eval_scope(page, """
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
    """, [entry["journal"], parts[0], parts[1], clean_piece, clean_libelle])
    log(f"  ✅ JS: Header Injected: {clean_piece} | {clean_libelle}")

async def fill_line(page: Page, idx: int, line: dict) -> None:
    res = await eval_scope(page, """
        // Reuse existing row if it exists (Axeane starts with 1 empty row)
        let row;
        if (scope.ecritureGrouping.ecritureComptables.length > a4) {
            row = scope.ecritureGrouping.ecritureComptables[a4];
        } else {
            scope.ajouterEcriture();
            row = scope.ecritureGrouping.ecritureComptables[scope.ecritureGrouping.ecritureComptables.length - 1];
        }
        
        row.debit = parseFloat(a1) || 0;
        row.credit = parseFloat(a2) || 0;
        row.extraLibelle = a3;

        // Broad Account Lookup across the Angular memory
        const entId = scope.contextComptable.currentEntreprise.entrepriseId;
        const allMaps = scope.model.mapComptesComptableEntreprise;
        const list = allMaps[entId] || Object.values(allMaps)[0] || [];
        const match = list.find(c => (c.compteComptable || '').startsWith(a0));

        if (match && scope.onSelectCompteComptable) {
            scope.onSelectCompteComptable(match, match.dernierCompteLibelle || match.libelle, null, a4, row);
            return { found: true };
        }
        return { found: false };
    """, [line["account"], str(line["debit"]), str(line["credit"]), line["label"], idx])

    if not res.get("ok") or not res.get("result", {}).get("found"):
        log(f"    ⚠️ Compte {line['account']} not found in Axeane list")

async def verify_entry(page: Page, entry: dict, update_ui_callback) -> bool:
    res = await eval_scope(page, """
        return {
            solde: scope.ecritureGrouping.solde || 0,
            d: scope.ecritureGrouping.totalDebit || 0,
            c: scope.ecritureGrouping.totalCredit || 0
        };
    """)
    d = res.get("result", {})
    is_bal = abs(d.get("solde", 999)) < 0.001
    log(f"  📊 Totals -> D: {d.get('d'):.3f} | C: {d.get('c'):.3f} | Solde: {d.get('solde'):.3f}")
    if update_ui_callback:
        update_ui_callback(entry['docRef'], 'success' if is_bal else 'error')
    return is_bal

async def save_entry(page: Page) -> str | None:
    await wait_for_spinner(page)
    await eval_scope(page, "if(scope.saveEcriture) scope.saveEcriture();")
    await wait(page, 1500)
    return await page.evaluate("""() => {
        const modal = document.querySelector('.modal.in, .swal2-popup');
        if (modal && /erreur/i.test(modal.textContent)) return modal.textContent.trim();
        return null;
    }""")

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
            if stop_event and stop_event.is_set(): 
                log("🛑 Automation Stopped.")
                break
            
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")
            await reset_form(page)
            await fill_header(page, entry)
            
            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)
            
            if await verify_entry(page, entry, update_ui_callback):
                err = await save_entry(page)
                if err: log(f"  ❌ Save Error: {err}")
            else:
                log(f"  ❌ Entry Unbalanced. Skipping save.")
                