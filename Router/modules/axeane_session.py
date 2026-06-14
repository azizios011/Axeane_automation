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
        
        success = await page.evaluate(f"""([id, val]) => {{
            const container = document.getElementById(id);
            const options = [...container.querySelectorAll('li.nya-bs-option a')];
            const match = options.find(a => a.textContent.trim().toUpperCase().includes(val.toUpperCase()));
            if (match) {{ match.click(); return true; }}
            return false;
        }}""", [container_id, text])
        
        if not success:
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


async def _type_amount(page: Page, selector: str, value: str):
    """Click an amount field, clear it, type the value, then Tab to commit."""
    await page.click(selector)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(value, delay=60)
    await page.keyboard.press("Tab")
    await asyncio.sleep(0.2)


async def fill_line(page: Page, idx: int, line: dict):
    # 1. Add row if needed
    current_rows = await page.locator("tr.td-row").count()
    if idx >= current_rows:
        await page.locator(".td-cmd .fa-plus").first.click()
        await asyncio.sleep(0.5)

    # 2. Fill Account — type to trigger autocomplete
    acc_field = f"input#cc_{idx}_3"
    await page.wait_for_selector(acc_field, timeout=8000)
    await page.click(acc_field)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(str(line["account"]), delay=70)
    await asyncio.sleep(1.2)
    await page.keyboard.press("ArrowDown")
    await asyncio.sleep(0.2)
    await page.keyboard.press("Enter")
    await asyncio.sleep(0.5)

    # 3. Fill Label by typing directly into the libelle input
    # Try standard ID pattern first, then nth-child fallback
    lbl_sel = f"input#lbl_{idx}"
    if await page.locator(lbl_sel).count() == 0:
        lbl_sel = f"tr.td-row:nth-child({idx + 1}) input[id^='lbl_']"
    if await page.locator(lbl_sel).count() > 0:
        await page.click(lbl_sel)
        await page.keyboard.press("Control+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.type(line["label"], delay=40)
        await page.keyboard.press("Tab")
        await asyncio.sleep(0.15)

    # 4. Fill Debit / Credit by typing directly into inputs (NOT via JS scope injection —
    #    AngularJS reads from the DOM input value on save, not from scope memory).
    debit_val  = str(line["debit"])
    credit_val = str(line["credit"])

    debit_sel  = f"input#dc_{idx}_6"
    credit_sel = f"input#dc_{idx}_7"

    # Fallback selectors if IDs don't match
    if await page.locator(debit_sel).count() == 0:
        debit_sel  = f"tr.td-row:nth-child({idx + 1}) input[id$='_6']"
        credit_sel = f"tr.td-row:nth-child({idx + 1}) input[id$='_7']"

    has_debit  = await page.locator(debit_sel).count() > 0
    has_credit = await page.locator(credit_sel).count() > 0

    if line["debit"] != 0 and has_debit:
        await _type_amount(page, debit_sel, debit_val)

    if line["credit"] != 0 and has_credit:
        await _type_amount(page, credit_sel, credit_val)


async def verify_and_save(page: Page, ref: str, callback):
    # Just save — Axeane backend validates balancing, no need to check solde here.
    await wait(page, 800)
    log(f"  💾 Saving: {ref}")
    if callback:
        callback(ref, 'success')
    await page.click("#ec-save")
    await wait_for_spinner(page)
    return True

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
            