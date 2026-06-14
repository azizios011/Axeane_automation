import asyncio
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS, MONTH_FR
from functions.helpers import log

# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────

async def wait(page: Page, ms: int = None):
    await page.wait_for_timeout(ms if ms else SETTINGS.get("slow_mo", 300))

async def wait_for_spinner(page: Page, timeout: int = 40000):
    try:
        await wait(page, 500)
        await page.wait_for_function(
            """() => ![...document.querySelectorAll('.nx-modern-spinner-modal, .modal.in, .loading-spinner')]
               .some(el => el.offsetParent !== null)""",
            timeout=timeout
        )
        await wait(page, 500)
    except: pass

async def select_dropdown_sidebar(page: Page, ol_id: str, text: str):
    """Specifically targets dropdowns inside the sidebar."""
    try:
        container = f".axe-sidebar #{ol_id}"
        button = f"{container} button.dropdown-toggle"
        await page.wait_for_selector(button, timeout=10000)
        await page.locator(button).first.dispatch_event("click")
        await wait(page, 600)
        
        success = await page.evaluate(f"""([id, val]) => {{
            const options = [...document.querySelectorAll(`.axe-sidebar #${{id}} li.nya-bs-option a`)];
            const match = options.find(a => a.textContent.trim().toUpperCase().includes(val.toUpperCase()));
            if (match) {{ match.click(); return true; }}
            return false;
        }}""", [ol_id, text])
        
        if not success: await page.keyboard.press("Enter")
        return True
    except: return False

async def select_nya_bs(page: Page, container_id: str, text: str):
    """General helper for form dropdowns (Journal, Mois)."""
    try:
        selector = f"#{container_id}"
        button = f"{selector} button.dropdown-toggle"
        await page.locator(button).first.click()
        await wait(page, 500)
        
        # Look for the option and click it directly
        success = await page.evaluate(f"""([id, val]) => {{
            const container = document.getElementById(id);
            const options = [...container.querySelectorAll('li.nya-bs-option a')];
            const match = options.find(a => a.textContent.trim().toUpperCase().includes(val.toUpperCase()));
            if (match) {{ match.click(); return true; }}
            return false;
        }}""", [container_id, text])
        
        if not success:
            # Fallback to typing if direct click fails
            search = f"{selector} .bs-searchbox input"
            if await page.locator(search).count() > 0:
                await page.locator(search).first.fill(text)
                await wait(page, 400)
                await page.keyboard.press("Enter")
    except Exception as e:
        log(f"    ⚠️ Error filling {container_id}: {str(e)}")

# ─────────────────────────────────────────────────────────────────────────
# Navigation & Login
# ─────────────────────────────────────────────────────────────────────────

async def do_login(page: Page):
    if await page.locator("#loginInput").count() > 0:
        log(f"Logging in as {SETTINGS.get('axeane_user')}...")
        await page.fill("#loginInput", SETTINGS.get("axeane_user"))
        await page.fill("#passwordInput", SETTINGS.get("axeane_password"))
        await page.click("button[aria-label='Connexion']")
        await wait_for_spinner(page)

async def select_context(page: Page):
    ent = SETTINGS.get("axeane_entreprise", "CPR")
    exe = SETTINGS.get("axeane_exercice", "EX 2026")
    log(f"Setting Context: {ent} / {exe}")
    await page.evaluate("document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())")

    is_open = await page.evaluate("$('.axe-sidebar').hasClass('nax-side-bar-menu-active')")
    if not is_open:
        await page.locator("#menuBtn").dispatch_event("click")
        await page.wait_for_selector(".axe-sidebar.nax-side-bar-menu-active", timeout=10000)
        await wait(page, 1000)

    await select_dropdown_sidebar(page, "entreprise", ent)
    await wait_for_spinner(page)
    await wait(page, 2000) 
    await select_dropdown_sidebar(page, "exercice", exe)
    await wait_for_spinner(page)
    await page.locator("#menuBtn").dispatch_event("click")

# ─────────────────────────────────────────────────────────────────────────
# Saisie Form Logic
# ─────────────────────────────────────────────────────────────────────────

async def fill_header(page: Page, entry: dict):
    parts = entry["date"].split("/") # parts[0]=Day, parts[1]=Month, parts[2]=Year
    piece = entry["piece"].split("/")[0]
    libelle = entry["libelle"].split("|")[-1].strip()

    # 1. Select Journal
    await select_nya_bs(page, "jo-eav", entry["journal"])
    await wait_for_spinner(page)

    # 2. Select Month (Map "03" -> "Mars")
    month_idx = int(parts[1])
    month_name = MONTH_FR[month_idx]
    log(f"    Setting Month: {month_name}")
    await select_nya_bs(page, "inputMoisIdEcriture", month_name)
    
    # 3. Type Day to trigger Mvt
    await page.click("#inputJourIdEcritureAv")
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(parts[0], delay=100)
    await page.keyboard.press("Tab")
    
    await wait(page, 1200) # Mvt generation delay
    
    await page.fill("#idDocumentInputMD2", piece)
    await page.fill("#inputLibelleIdMD2", libelle)
    await page.keyboard.press("Tab")
    log(f"  ✅ Header Ready: {piece}")

async def fill_line(page: Page, idx: int, line: dict):
    # 1. Add row if needed
    current_rows = await page.locator("tr.td-row").count()
    if idx >= current_rows:
        await page.locator(".td-cmd .fa-plus").first.click()
        await asyncio.sleep(0.4)

    # 2. Focus and Fill Account
    acc_field = f"input#cc_{idx}_3"
    await page.wait_for_selector(acc_field)
    await page.click(acc_field)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    
    # Type slowly to trigger search
    await page.keyboard.type(str(line["account"]), delay=70)
    await asyncio.sleep(1.2) # Wait for dropdown to be 100% visible
    
    # Selection Sequence: Down then Enter
    await page.keyboard.press("ArrowDown")
    await asyncio.sleep(0.2)
    await page.keyboard.press("Enter")
    await asyncio.sleep(0.4)
    
    # 3. Fill Label & Amounts
    # First write label via scope (no DOM input for extraLibelle)
    await page.evaluate("""([i, lbl]) => {
        const root = document.querySelector('.td-root');
        const scope = angular.element(root).scope();
        const row = scope.ecritureGrouping.ecritureComptables[i];
        if (row) { row.extraLibelle = lbl; scope.$apply(); }
    }""", [idx, line["label"]])

    # Then fill debit/credit via the actual DOM inputs so Angular ng-model picks up the value.
    # The form reads from input fields on save — scope.$apply() alone does not update them.
    debit_str  = str(line["debit"])
    credit_str = str(line["credit"])

    await page.evaluate("""([i, d, c]) => {
        function setInput(el, val) {
            if (!el) return;
            // Native input setter bypasses Angular's value caching
            const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                window.HTMLInputElement.prototype, 'value'
            ).set;
            nativeInputValueSetter.call(el, val);
            el.dispatchEvent(new Event('input',  { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        }
        const debitEl  = document.querySelector(`input#dc_${i}_6`);
        const creditEl = document.querySelector(`input#dc_${i}_7`);
        setInput(debitEl,  d);
        setInput(creditEl, c);

        // Also update scope directly as a safety net
        const root  = document.querySelector('.td-root');
        const scope = angular.element(root).scope();
        const row   = scope.ecritureGrouping.ecritureComptables[i];
        if (row) {
            row.debit  = parseFloat(d)  || 0;
            row.credit = parseFloat(c) || 0;
            if (scope.calculateTotalDebit)  scope.calculateTotalDebit(true, row, false);
            if (scope.calculateTotalCredit) scope.calculateTotalCredit(true, row, false);
            scope.$apply();
        }
    }""", [idx, debit_str, credit_str])

async def verify_and_save(page: Page, ref: str, callback):
    await wait(page, 1500)
    kpis = await page.evaluate("""() => {
        const s = document.querySelector('.ax-badge-kpi.ax-badge-purple .ax-badge-kpi-value');
        const d = document.querySelector('.ax-badge-kpi.ax-badge-green .ax-badge-kpi-value');
        return { 
            solde: s ? s.textContent.trim() : "999", 
            debit: d ? d.textContent.trim() : "0,000" 
        };
    }""")
    
    is_bal = "0,000" in kpis['solde'] and kpis['debit'] != "0,000"
    log(f"  📊 Verification -> Solde: {kpis['solde']} | Ready: {is_bal}")
    
    if callback: callback(ref, 'success' if is_bal else 'error')
    
    if is_bal:
        await page.click("#ec-save")
        await wait_for_spinner(page)
        return True
    return False

# ─────────────────────────────────────────────────────────────────────────
# Runner
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None):
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(SETTINGS.get("cdp_url"))
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page = next(p for p in all_pages if "kompta" in p.url.lower())
        await page.bring_to_front()
        
        await do_login(page)
        await select_context(page)
        
        await page.evaluate("""() => {
            const m = [...document.querySelectorAll('.nax-main-menu-item span')].find(s => s.textContent.includes('Comptabilité'));
            if(m) m.click();
        }""")
        await wait(page, 1000)
        await page.click(".kc-dock-item[data-code='ECRITURE_AVANCEE']")
        await wait_for_spinner(page)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set(): break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")
            
            try:
                reset = page.locator("button[ng-click*='resetEcritures']").first
                if await reset.is_visible(): await reset.click()
                await wait(page, 500)
            except: pass
            
            await fill_header(page, entry)
            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)
            
            await verify_and_save(page, entry['docRef'], update_ui_callback)
            