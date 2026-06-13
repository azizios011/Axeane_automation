import asyncio
from playwright.async_api import Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

# ─────────────────────────────────────────────────────────────────────────
# Human-Like Helpers
# ─────────────────────────────────────────────────────────────────────────

async def wait(page: Page, ms: int = None):
    await page.wait_for_timeout(ms if ms else SETTINGS.get("slow_mo", 300))

async def wait_for_spinner(page: Page, timeout: int = 40000):
    """Wait for loading spinners or modals to disappear."""
    try:
        await wait(page, 500)
        await page.wait_for_function(
            """() => ![...document.querySelectorAll('.nx-modern-spinner-modal, .modal.in, .loading-spinner')]
               .some(el => el.offsetParent !== null)""",
            timeout=timeout
        )
        await wait(page, 300)
    except: pass

async def select_dropdown(page: Page, container_selector: str, text: str):
    """Cents a dropdown, types in search, and clicks the result."""
    try:
        btn = f"{container_selector} button.dropdown-toggle"
        await page.wait_for_selector(btn, timeout=5000)
        await page.click(btn)
        await wait(page, 400)
        
        # Type into search if it exists
        search = f"{container_selector} .bs-searchbox input"
        if await page.locator(search).is_visible():
            await page.locator(search).fill(text)
            await wait(page, 500)
        
        # Click the option
        option = f"{container_selector} li.nya-bs-option a"
        options = page.locator(option)
        count = await options.count()
        for i in range(count):
            content = await options.nth(i).text_content()
            if text.upper() in content.strip().upper():
                await options.nth(i).click()
                return True
        # Fallback: Press Enter
        await page.keyboard.press("Enter")
        return True
    except: return False

# ─────────────────────────────────────────────────────────────────────────
# Navigation & Login
# ─────────────────────────────────────────────────────────────────────────

async def do_login(page: Page):
    if await page.locator("#loginInput").count() > 0:
        log(f"Logging in as {SETTINGS.get('axeane_user')}...")
        await page.locator("#loginInput").fill(SETTINGS.get("axeane_user"))
        await page.locator("#passwordInput").fill(SETTINGS.get("axeane_password"))
        await page.click("button[aria-label='Connexion']")
        await wait_for_spinner(page)

async def select_context(page: Page):
    ent = SETTINGS.get("axeane_entreprise", "CPR")
    exe = SETTINGS.get("axeane_exercice", "EX 2026")
    log(f"Setting Context: {ent} / {exe}")
    
    # Force close any blocking backdrops
    await page.evaluate("document.querySelectorAll('.modal-backdrop').forEach(el => el.remove())")

    # Open sidebar
    is_open = await page.evaluate("$('.axe-sidebar').hasClass('nax-side-bar-menu-active')")
    if not is_open:
        await page.click("#menuBtn")
        await page.wait_for_selector(".axe-sidebar.nax-side-bar-menu-active")

    await select_dropdown(page, "#entreprise", ent)
    await wait_for_spinner(page)
    await wait(page, 1000)
    
    await select_dropdown(page, "#exercice", exe)
    await wait_for_spinner(page)
    
    # Close sidebar
    await page.click("#menuBtn")

# ─────────────────────────────────────────────────────────────────────────
# Saisie Form Interaction
# ─────────────────────────────────────────────────────────────────────────

async def fill_header(page: Page, entry: dict):
    parts = entry["date"].split("/")
    piece = entry["piece"].split("/")[0]
    libelle = entry["libelle"].split("|")[-1].strip()

    # 1. Select Journal & Month
    await select_dropdown(page, "#jo-eav", entry["journal"])
    await wait_for_spinner(page)
    await select_dropdown(page, "#inputMoisIdEcriture", parts[1])
    
    # 2. Type Day (Crucial for Mvt trigger)
    await page.click("#inputJourIdEcritureAv")
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(parts[0], delay=100)
    await page.keyboard.press("Tab")
    
    # 3. Wait for Mvt to appear in the field
    await wait(page, 800)
    
    # 4. Fill Reference and Libellé
    await page.fill("#idDocumentInputMD2", piece)
    await page.fill("#inputLibelleIdMD2", libelle)
    await page.keyboard.press("Tab")
    log(f"  ✅ Header Human-Filled: {piece}")

async def fill_line(page: Page, idx: int, line: dict):
    # Ensure row exists
    rows = page.locator("tr.td-row")
    if await rows.count() <= idx:
        await page.click(".td-cmd .fa-plus")
        await wait(page, 300)

    # 1. Fill Account (cc_{idx}_3)
    acc_selector = f"#cc_{idx}_3"
    await page.click(acc_selector)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(str(line["account"]), delay=60)
    await wait(page, 1000) # Wait for autocomplete
    await page.keyboard.press("Enter")
    await wait(page, 300)
    
    # 2. Fill Libellé
    await page.fill(f"#exlibelle{idx}", line["label"])
    
    # 3. Fill Amounts
    if float(line["debit"]) > 0:
        await page.fill(f"#debit-eav-{idx}", str(line["debit"]))
        await page.keyboard.press("Tab")
    if float(line["credit"]) > 0:
        await page.fill(f"#credit-eav-{idx}", str(line["credit"]))
        await page.keyboard.press("Tab")
    
    await wait_for_spinner(page)

async def verify_and_save(page: Page, ref: str, callback):
    # Wait for Axeane to calculate totals
    await wait(page, 1000)
    
    kpis = await page.evaluate("""() => {
        const s = document.querySelector('.ax-badge-kpi.ax-badge-purple .ax-badge-kpi-value');
        const d = document.querySelector('.ax-badge-kpi.ax-badge-green .ax-badge-kpi-value');
        return { 
            solde: s ? s.textContent.trim() : "999", 
            debit: d ? d.textContent.trim() : "0,000" 
        };
    }""")
    
    is_bal = "0,000" in kpis['solde'] and kpis['debit'] != "0,000"
    log(f"  📊 Verifying Screen Badges -> Solde: {kpis['solde']} | Ready: {is_bal}")
    
    if callback: callback(ref, 'success' if is_bal else 'error')
    
    if is_bal:
        await page.click("#ec-save")
        await wait_for_spinner(page)
        # Check for error popup
        err = await page.evaluate("""() => {
            const m = document.querySelector('.modal.in, .swal2-popup');
            return (m && /erreur/i.test(m.textContent)) ? m.textContent.trim() : null;
        }""")
        if err: log(f"  ❌ Axeane Error: {err}")
        return True
    return False

# ─────────────────────────────────────────────────────────────────────────
# Main Execution
# ─────────────────────────────────────────────────────────────────────────

async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None):
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(SETTINGS.get("cdp_url"))
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page = next(p for p in all_pages if "kompta" in p.url.lower())
        await page.bring_to_front()
        
        await do_login(page)
        await select_context(page)
        
        # Navigation
        await page.evaluate("""() => {
            const m = [...document.querySelectorAll('.nax-main-menu-item span')].find(s => s.textContent.includes('Comptabilité'));
            if(m) m.click();
        }""")
        await wait(page, 800)
        await page.click(".kc-dock-item[data-code='ECRITURE_AVANCEE']")
        await wait_for_spinner(page)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set(): break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")
            
            # Reset Form button (top right trash icon)
            reset_btn = page.locator("button[ng-click*='resetEcritures']").first
            if await reset_btn.is_visible(): await reset_btn.click()
            
            await fill_header(page, entry)
            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)
            
            await verify_and_save(page, entry['docRef'], update_ui_callback)
            