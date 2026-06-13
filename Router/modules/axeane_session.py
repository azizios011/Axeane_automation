import asyncio
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

SCOPE_ROOT_SELECTOR = ".td-root"

# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

async def wait_for_spinner(page: Page, timeout: int = 60000) -> None:
    try:
        await page.wait_for_function(
            """() => {
                const spinners = document.querySelectorAll('.nx-modern-spinner-modal, .modal.in, [uib-modal-window], .loading-spinner');
                for (const el of spinners) { if (el.offsetParent !== null) return false; }
                return true;
            }""",
            timeout=timeout,
        )
    except: pass

async def eval_scope(page: Page, body: str, args: list = None) -> dict:
    if args is None: args = []
    while len(args) < 5: args.append(None)
    js = f"""(args) => {{
        const [a0, a1, a2, a3, a4] = args;
        const root = document.querySelector('{SCOPE_ROOT_SELECTOR}');
        const scope = angular.element(root).scope();
        try {{
            const result = (function(scope, a0, a1, a2, a3, a4) {{ {body} }})(scope, a0, a1, a2, a3, a4);
            if (!scope.$root.$$phase) scope.$apply();
            return {{ ok: true, result: result }};
        }} catch (e) {{ return {{ ok: false, error: e.message }}; }}
    }}"""
    return await page.evaluate(js, args)

# ─────────────────────────────────────────────────────────────────────────
# Context & Navigation
# ─────────────────────────────────────────────────────────────────────────

async def select_context(page: Page):
    entreprise = SETTINGS.get("axeane_entreprise", "CPR")
    exercice = SETTINGS.get("axeane_exercice", "EX 2026")
    log(f"Setting Context: {entreprise} / {exercice}")
    
    # Force close blockers
    await page.evaluate("document.querySelectorAll('.modal-backdrop, .nx-modern-spinner-modal').forEach(el => el.remove())")
    
    if not await page.evaluate("$('.axe-sidebar').hasClass('nax-side-bar-menu-active')"):
        await page.evaluate("document.getElementById('menuBtn').click()")
        await page.wait_for_selector(".axe-sidebar.nax-side-bar-menu-active")

    # Select via JS Injection to the Sidebar Search
    for id, val in [("entreprise", entreprise), ("exercice", exercice)]:
        btn = f".axe-sidebar #{id} button"
        inp = f".axe-sidebar #{id} .bs-searchbox input"
        await page.click(btn)
        await page.locator(inp).fill(val)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await wait_for_spinner(page)
        await asyncio.sleep(1)

    await page.evaluate("document.getElementById('menuBtn').click()")

# ─────────────────────────────────────────────────────────────────────────
# Entry Filling
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
    """, [entry["journal"], parts[0], parts[1], piece, libelle])
    log(f"  ✅ Header: {piece} | {libelle}")

async def fill_line(page: Page, idx: int, line: dict):
    # 1. Use JS to prepare the row and fill amounts/labels
    await eval_scope(page, """
        let row = scope.ecritureGrouping.ecritureComptables[a4];
        if (!row) { scope.ajouterEcriture(); row = scope.ecritureGrouping.ecritureComptables[a4]; }
        row.debit = parseFloat(a1) || 0;
        row.credit = parseFloat(a2) || 0;
        row.extraLibelle = a3;
    """, [None, str(line["debit"]), str(line["credit"]), line["label"], idx])

    # 2. Use Keyboard to type account and select it
    # The ID format in Axeane is usually cc_{index}_3
    selector = f"input#cc_{idx}_3"
    try:
        await page.wait_for_selector(selector, timeout=5000)
        await page.click(selector)
        # Clear field
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        # Type account
        await page.keyboard.type(str(line["account"]), delay=50)
        await asyncio.sleep(0.7) # Wait for autocomplete to appear
        # Press Enter to select the top result
        await page.keyboard.press("Enter")
        await wait_for_spinner(page)
    except:
        log(f"    ⚠️ Failed interactive selection for account {line['account']}")

async def verify_and_save(page: Page, ref: str, callback) -> bool:
    kpis = await page.evaluate("""() => {
        const s = document.querySelector('.ax-badge-kpi.ax-badge-purple .ax-badge-kpi-value');
        const d = document.querySelector('.ax-badge-kpi.ax-badge-green .ax-badge-kpi-value');
        return { solde: s ? s.textContent.trim() : "999", d: d ? d.textContent.trim() : "0" };
    }""")
    
    is_bal = "0,000" in kpis['solde'] and kpis['d'] != "0,000"
    log(f"  📊 Balanced: {is_bal} (Solde: {kpis['solde']})")
    
    if callback: callback(ref, 'success' if is_bal else 'error')
    
    if is_bal:
        await eval_scope(page, "scope.saveEcriture();")
        await wait_for_spinner(page)
        await asyncio.sleep(0.5)
        return True
    return False

# ─────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None):
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(SETTINGS.get("cdp_url"))
        page = next(p for ctx in browser.contexts for p in ctx.pages if "kompta" in p.url.lower())
        await page.bring_to_front()
        
        await select_context(page)
        
        # Open main menu logic
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
        