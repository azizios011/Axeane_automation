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
# Login & Navigation
# ─────────────────────────────────────────────────────────────────────────

async def do_login(page: Page) -> None:
    if await page.locator("#loginInput").count() > 0:
        log(f"Logging in as {SETTINGS.get('axeane_user')}...")
        await page.locator("#loginInput").fill(SETTINGS.get("axeane_user"))
        await page.locator("#passwordInput").fill(SETTINGS.get("axeane_password"))
        await page.click("button[aria-label='Connexion']")
        try:
            await page.wait_for_selector(".auth-modal-window", state="hidden", timeout=15000)
        except:
            await page.evaluate("document.querySelectorAll('.auth-modal-window, .modal-backdrop').forEach(el => el.remove())")

async def select_context(page: Page):
    entreprise = SETTINGS.get("axeane_entreprise", "CPR")
    exercice = SETTINGS.get("axeane_exercice", "EX 2026")
    log(f"Setting Context: {entreprise} / {exercice}")
    
    await page.evaluate("document.querySelectorAll('.modal-backdrop, .nx-modern-spinner-modal').forEach(el => el.remove())")
    
    if not await page.evaluate("$('.axe-sidebar').hasClass('nax-side-bar-menu-active')"):
        await page.evaluate("document.getElementById('menuBtn').click()")
        await page.wait_for_selector(".axe-sidebar.nax-side-bar-menu-active")

    for id, val in [("entreprise", entreprise), ("exercice", exercice)]:
        btn = f".axe-sidebar #{id} button"
        inp = f".axe-sidebar #{id} .bs-searchbox input"
        await page.locator(btn).first.click()
        await page.locator(inp).first.fill(val)
        await asyncio.sleep(0.5)
        await page.keyboard.press("Enter")
        await wait_for_spinner(page)
        await asyncio.sleep(1)

    await page.evaluate("document.getElementById('menuBtn').click()")

# ─────────────────────────────────────────────────────────────────────────
# The "Mvt" Fix Logic
# ─────────────────────────────────────────────────────────────────────────

async def fill_header(page: Page, entry: dict):
    parts = entry["date"].split("/")
    piece = entry["piece"].split("/")[0]
    libelle = entry["libelle"].split("|")[-1].strip()

    # We fill in steps to trigger the Mvt generation
    # Step 1: Set Journal & Month
    await eval_scope(page, """
        const entId = scope.contextComptable.currentEntreprise.entrepriseId;
        const jour = scope.mapCodeJournauxEntreprise[entId].find(j => j.code === a0);
        if (jour) { 
            scope.ecritureGrouping.journal = jour; 
            scope.JournalCodeChanges(); 
        }
        scope.items.selectedMoisDocComptable = scope.moisList[parseInt(a1) - 1];
    """, [entry["journal"], parts[1]])
    
    await asyncio.sleep(0.5)

    # Step 2: Set Day & Trigger Movement Calculation
    await eval_scope(page, """
        scope.items.jourDocComptable = a0;
        // This is the function Axeane calls to generate the Mvt number
        if(scope.checkMoisCloture) scope.checkMoisCloture();
    """, [parts[0]])
    
    await asyncio.sleep(0.8) # Wait for Axeane to generate Mvt

    # Step 3: Set Piece & Libelle
    await eval_scope(page, """
        scope.ecritureGrouping.piece = a0;
        scope.ecritureGrouping.libelle = a1;
    """, [piece, libelle])
    
    log(f"  ✅ Header & Mvt ready: {piece}")

async def fill_line(page: Page, idx: int, line: dict):
    # Setup row values via JS
    await eval_scope(page, """
        let row = scope.ecritureGrouping.ecritureComptables[a4];
        if (!row) { scope.ajouterEcriture(); row = scope.ecritureGrouping.ecritureComptables[a4]; }
        row.debit = parseFloat(a1) || 0;
        row.credit = parseFloat(a2) || 0;
        row.extraLibelle = a3;
    """, [None, str(line["debit"]), str(line["credit"]), line["label"], idx])

    # Interactive Account Selection
    selector = f"input#cc_{idx}_3"
    try:
        await page.wait_for_selector(selector, timeout=5000)
        await page.click(selector)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(str(line["account"]), delay=70)
        await asyncio.sleep(1.0) # Wait for dropdown
        await page.keyboard.press("Enter")
        await asyncio.sleep(0.3)
        await page.keyboard.press("Tab")
        await wait_for_spinner(page)
    except:
        log(f"    ⚠️ Account {line['account']} failed.")

async def verify_and_save(page: Page, ref: str, callback) -> bool:
    # Check the UI badges for real totals
    kpis = await page.evaluate("""() => {
        const s = document.querySelector('.ax-badge-kpi.ax-badge-purple .ax-badge-kpi-value');
        const d = document.querySelector('.ax-badge-kpi.ax-badge-green .ax-badge-kpi-value');
        const mvt = document.querySelector('input[ng-model="ecritureGrouping.mvt"]');
        return { 
            solde: s ? s.textContent.trim() : "999", 
            debit: d ? d.textContent.trim() : "0,000",
            mvt: mvt ? mvt.value : "" 
        };
    }""")
    
    # Validation: Balanced AND Debit > 0 AND Mvt is NOT empty
    is_bal = "0,000" in kpis['solde'] and kpis['debit'] != "0,000" and kpis['mvt'] != ""
    
    log(f"  📊 Verification -> Mvt: {kpis['mvt']} | Balanced: {is_bal}")
    
    if callback: callback(ref, 'success' if is_bal else 'error')
    
    if is_bal:
        await eval_scope(page, "scope.saveEcriture();")
        await wait_for_spinner(page)
        return True
    
    log("  ❌ Blocked: Mvt missing or Totals are zero.")
    return False

# ─────────────────────────────────────────────────────────────────────────
# Main Execution
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None):
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(SETTINGS.get("cdp_url"))
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page = next(p for ctx in browser.contexts for p in ctx.pages if "kompta" in p.url.lower())
        await page.bring_to_front()
        
        await do_login(page)
        await select_context(page)
        
        # Open main menu
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
            
            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)
            
            await verify_and_save(page, entry['docRef'], update_ui_callback)
            