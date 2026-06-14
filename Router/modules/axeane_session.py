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
# Debug: color a form row by its 0-based index
# ─────────────────────────────────────────────────────────────────────────

async def color_row(page: Page, idx: int, color: str):
    """Paint a table row in the saisie form for visual debugging."""
    await page.evaluate("""([i, c]) => {
        const rows = document.querySelectorAll('tr.td-row');
        if (rows[i]) rows[i].style.backgroundColor = c;
    }""", [idx, color])

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
    parts = entry["date"].split("/")  # parts[0]=Day, parts[1]=Month, parts[2]=Year
    piece = entry["piece"].split("/")[0]
    libelle = entry["libelle"].split("|")[-1].strip()

    await select_nya_bs(page, "jo-eav", entry["journal"])
    await wait_for_spinner(page)

    month_idx = int(parts[1])
    month_name = MONTH_FR[month_idx]
    log(f"    Setting Month: {month_name}")
    await select_nya_bs(page, "inputMoisIdEcriture", month_name)

    await page.click("#inputJourIdEcritureAv")
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(parts[0], delay=100)
    await page.keyboard.press("Tab")
    await wait(page, 1200)

    await page.fill("#idDocumentInputMD2", piece)
    await page.fill("#inputLibelleIdMD2", libelle)
    await page.keyboard.press("Tab")
    log(f"  ✅ Header Ready: {piece}")


async def fill_line(page: Page, idx: int, line: dict, is_last: bool):
    """
    Fill one accounting line.

    is_last=True  → this is the final row; do NOT click add-button after it
                    (an empty trailing row would block Axeane from saving).
    is_last=False → click the add-button after filling to open the next row
                    without triggering Axeane's auto-submit on a balanced form.
    """
    # 1. Add row if the form doesn't have enough rows yet
    current_rows = await page.locator("tr.td-row").count()
    if idx >= current_rows:
        await page.locator(".td-cmd .fa-plus").first.click()
        await asyncio.sleep(0.5)

    # 2. Debug: highlight the row we're about to fill (orange = in progress)
    await color_row(page, idx, "#FFF3CD")

    # 3. Fill Account
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

    # 4. Fill Libelle — cursor lands here after account selection.
    #    The field is pre-filled with the header libelle; clear it first.
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.type(line["label"], delay=40)
    await page.keyboard.press("Tab")   # Libelle → Debit
    await asyncio.sleep(0.2)

    debit_val  = float(line["debit"])
    credit_val = float(line["credit"])

    # 5. Fill Debit
    if debit_val != 0:
        await page.keyboard.type(f"{debit_val:.3f}", delay=50)
    await page.keyboard.press("Tab")   # Debit → Credit
    await asyncio.sleep(0.2)

    # 6. Fill Credit
    if credit_val != 0:
        await page.keyboard.type(f"{credit_val:.3f}", delay=50)

    # 7. Commit strategy:
    #    - NOT last row → click add-button (commits credit, opens next blank row
    #      without triggering Axeane's balanced-form auto-submit via Tab).
    #    - Last row     → just Tab once to commit credit, then stop.
    #      The form will be ready to save; no trailing empty row is added.
    await asyncio.sleep(0.3)
    if not is_last:
        await page.locator(".td-cmd .fa-plus").first.click()
        await asyncio.sleep(0.4)
    else:
        await page.keyboard.press("Tab")  # commit the last credit value
        await asyncio.sleep(0.3)

    # 8. Debug: color the row green once done
    await color_row(page, idx, "#D4EDDA")

    log(f"    Row {idx+1}{'[LAST]' if is_last else ''}: "
        f"{line['account']} | {line['label']} | D:{debit_val:.3f} C:{credit_val:.3f}")


async def verify_and_save(page: Page, ref: str, callback):
    # No solde check — Axeane backend validates balance. Just save.
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
            const m = [...document.querySelectorAll('.nax-main-menu-item span')]
                        .find(s => s.textContent.includes('Comptabilité'));
            if(m) m.click();
        }""")
        await wait(page, 1000)
        await page.click(".kc-dock-item[data-code='ECRITURE_AVANCEE']")
        await wait_for_spinner(page)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set(): break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']} ({len(entry['lines'])} rows)")

            try:
                reset = page.locator("button[ng-click*='resetEcritures']").first
                if await reset.is_visible(): await reset.click()
                await wait(page, 500)
            except: pass

            await fill_header(page, entry)

            lines = entry["lines"]
            for j, line in enumerate(lines):
                is_last = (j == len(lines) - 1)
                await fill_line(page, j, line, is_last=is_last)

            await verify_and_save(page, entry['docRef'], update_ui_callback)
            