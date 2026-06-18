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

async def get_axeane_row_count(page: Page) -> int:
    """
    Read Axeane's own row counter (the N° column of the last row) rather
    than just counting tr.td-row elements. This matters because a
    "trailing extra row" isn't always blank — it can be a real duplicate
    row with data misdirected into it (see delete_last_row) — so detecting
    it by content is unreliable. Axeane's own count of its own rows is the
    ground truth.

    NOTE: assumes N° is the 2nd <td> in each tr.td-row (checkbox, then N°,
    matching the visible column order). Verify against the real DOM if
    this returns something unexpected.
    """
    try:
        last_row = page.locator("tr.td-row").last
        n_cell = last_row.locator("td").nth(1)
        text = (await n_cell.inner_text()).strip()
        return int(text)
    except Exception as e:
        log(f"    ⚠️ get_axeane_row_count failed ({e}); falling back to DOM count")
        return await page.locator("tr.td-row").count()


async def delete_last_row(page: Page) -> bool:
    """
    Select the very last row by its checkbox and remove it via the trash
    icon. Deletes strictly by position — not by checking whether the row
    "looks empty" — because a focus-desync bug can leave the trailing row
    partially filled or duplicated (e.g. a repeated account code with a
    stray value typed into its libellé) rather than cleanly blank.

    NOTE: checkbox/trash selectors are a best guess based on the visible
    UI. Verify against the real DOM if deletion doesn't actually happen.
    """
    try:
        last_row = page.locator("tr.td-row").last
        checkbox = last_row.locator("input[type='checkbox']").first
        if await checkbox.count() > 0 and not await checkbox.is_checked():
            await checkbox.check()
            await asyncio.sleep(0.2)
        trash_btn = page.locator(
            ".fa-trash, .axe-sidebar-trash, button[title*='Suppr']"
        ).first
        if await trash_btn.count() == 0:
            log("    ⚠️ No delete control found for delete_last_row()")
            return False
        await trash_btn.click()
        await asyncio.sleep(0.4)
        return True
    except Exception as e:
        log(f"    ⚠️ delete_last_row error: {e}")
        return False


async def cleanup_trailing_rows(page: Page, expected_count: int, max_attempts: int = 3):
    """
    Compare Axeane's own row count (N° column) against how many rows we
    actually intended to fill, and delete the last row repeatedly until
    the counts match — or give up after max_attempts so a genuinely
    unrelated problem doesn't loop forever.
    """
    for _ in range(max_attempts):
        current = await get_axeane_row_count(page)
        if current <= expected_count:
            return
        log(f"    🧹 Axeane reports {current} rows, expected {expected_count} — deleting last row")
        if not await delete_last_row(page):
            return
    final = await get_axeane_row_count(page)
    if final > expected_count:
        log(f"    ⚠️ cleanup_trailing_rows gave up: still {final} rows after {max_attempts} attempts")

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

    # 3b. Verify focus actually landed back inside THIS row before typing
    # anything else. Selecting an account that already appears elsewhere
    # in the entry (e.g. a repeated 411000 line) can leave the cursor
    # somewhere unexpected — values typed afterward then land in the wrong
    # field, or in a row Axeane spawns on the side. If focus drifted,
    # recover by explicitly clicking into this row's Libelle field instead
    # of continuing to type blind.
    focus_ok = await page.evaluate("""(rowIdx) => {
        const rows = document.querySelectorAll('tr.td-row');
        const row = rows[rowIdx];
        return !!(row && row.contains(document.activeElement));
    }""", idx)

    if not focus_ok:
        log(f"    ⚠️ Focus drifted away from row {idx} after account "
            f"selection (account '{line['account']}' may repeat earlier "
            f"in this entry) — attempting recovery")
        row = page.locator("tr.td-row").nth(idx)
        # Heuristic: Libelle is the 2nd text input in the row (1st is the
        # account field, cc_{idx}_3). VERIFY this against the real DOM —
        # inspect the Libelle input's id/selector and tell me if this
        # guess is wrong, since a bad guess here would make things worse.
        libelle_input = row.locator("input").nth(1)
        if await libelle_input.count() > 0:
            await libelle_input.click()
            await asyncio.sleep(0.2)
        else:
            log(f"    ⚠️ Could not locate a recovery field for row {idx} "
                f"— this row's values may be unreliable, flag for review")

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
    #    - NOT last row → Tab to commit credit, then click add-button to open
    #      next row. We Tab first so the value is registered before the click,
    #      then wait for the new row's account input to appear in the DOM.
    #    - Last row → Tab once to commit, stop. No trailing empty row added.
    await asyncio.sleep(0.3)
    if not is_last:
        await page.keyboard.press("Tab")   # commit credit value first
        await asyncio.sleep(0.2)
        await page.locator(".td-cmd .fa-plus").first.click()
        # Wait until the next row's account input is present before returning
        next_acc = f"input#cc_{idx + 1}_3"
        try:
            await page.wait_for_selector(next_acc, timeout=5000)
        except:
            await asyncio.sleep(0.6)   # fallback if selector naming differs
    else:
        # Last row: click save directly instead of Tab.
        # Tab on a credit field can trigger Axeane to create a new empty row,
        # which then blocks saving with "doit avoir un crédit ou un débit".
        # Clicking #ec-save commits the credit value and saves in one action.
        await asyncio.sleep(0.2)
        # === SAVE LOGIC DISABLED FOR INSPECTION ===
        # await cleanup_trailing_rows(page, expected_count=idx + 1)
        # await page.click("#ec-save")
        # await wait_for_spinner(page)
        log(f"    ⏸️  Save disabled — inspect the form now (row {idx+1})")

    # 8. Debug: color the row green once done
    await color_row(page, idx, "#D4EDDA")

    log(f"    Row {idx+1}{'[LAST]' if is_last else ''}: "
        f"{line['account']} | {line['label']} | D:{debit_val:.3f} C:{credit_val:.3f}")


async def verify_and_save(page: Page, ref: str, callback):
    """
    Actively verify the save succeeded instead of assuming success just
    because #ec-save was clicked and the spinner cleared. This is what was
    missing before: a blocked save (e.g. from a dangling empty row) was
    silently reported as 'success' in the UI, which is why the stuck form
    in the screenshot wasn't caught automatically.

    Checks, in order:
      1. An error toast/alert from Axeane (validation/balance errors)
      2. The Réf/N°doc field having cleared/changed — Axeane resets this
         when starting a fresh entry after a real save

    NOTE: the error-toast selector is a best guess (common Angular toast
    classes). Trigger a deliberate validation error once in the browser,
    inspect the DOM for the actual error element, and adjust the selector
    below if it doesn't match.
    """
    error_locator = page.locator(".toast-error, .alert-danger, .ng-toast--danger")
    if await error_locator.count() > 0:
        error_text = (await error_locator.first.inner_text()).strip()
        log(f"  ❌ Save FAILED for {ref}: {error_text}")
        if callback:
            callback(ref, 'error')
        return False

    ref_field = page.locator("#idDocumentInputMD2")
    if await ref_field.count() > 0:
        current_val = (await ref_field.input_value()).strip()
        expected_piece = ref.split("/")[0].strip()
        if current_val == expected_piece:
            # Field still shows our ref — the form likely never reset,
            # meaning the save click didn't actually go through.
            log(f"  ❌ Save UNCONFIRMED for {ref}: form did not reset after save")
            if callback:
                callback(ref, 'error')
            return False

    log(f"  💾 Saved: {ref}")
    if callback:
        callback(ref, 'success')
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

            # === SAVE LOGIC DISABLED FOR INSPECTION ===
            # await verify_and_save(page, entry['docRef'], update_ui_callback)
            log(f"  ⏸️  Entry {entry['docRef']} filled — save disabled, inspect visually")
            