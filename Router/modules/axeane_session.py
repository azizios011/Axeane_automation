import asyncio
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

async def wait(page: Page, ms: int = None) -> None:
    delay = ms if ms is not None else SETTINGS.get("slow_mo", 300)
    await page.wait_for_timeout(delay)

async def wait_for_spinner(page: Page, timeout: int = 60000) -> None:
    """Wait for spinner/loading modals to disappear."""
    try:
        # First, wait a small amount to let any spinners appear
        await wait(page, 500)
        
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
        
        # Wait a little more to be safe
        await wait(page, 500)
    except PWTimeout:
        log("  ⚠️ Spinner timeout, proceeding anyway")

async def nya_select_by_js(page: Page, ol_id: str, option_text: str) -> None:
    """Finds the option in the dropdown and clicks it."""
    await page.evaluate("""([olId, text]) => {
        const ol = document.getElementById(olId);
        if (!ol) return;
        // Search specifically for the text in the spans
        const spans = ol.querySelectorAll('li.nya-bs-option span.ng-binding');
        for (const sp of spans) {
            if (sp.textContent.trim().toLowerCase() === text.toLowerCase()) {
                sp.click();
                return;
            }
        }
    }""", [ol_id, option_text])
    await wait(page, 400) # Small wait for UI to catch up

async def get_current_context(page: Page) -> tuple[str, str]:
    """Reads the currently selected Entreprise and Exercice directly from the UI."""
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
    
    log("✅ Saisie des écritures opened")

async def fill_header(page: Page, entry: dict) -> None:
    await wait_for_spinner(page)
    
    # 1. SELECT JOURNAL (Must be first because it resets the sequence)
    journal_code = entry["journal"] 
    log(f"  Selecting Journal: {journal_code}")
    await nya_select_by_js(page, "jo-eav", journal_code)
    await wait_for_spinner(page)

    # 2. EXTRACT JOUR AND MOIS FROM CSV DATE
    date_val = entry["date"]  # e.g., "02/03/2026"
    parts = date_val.split("/")
    jour = parts[0]           # "02"
    month_idx = int(parts[1]) # 3
    
    # 3. FILL JOUR (The specific Day field)
    # We DON'T touch #ec-date-creation anymore.
    j_input = page.locator("#inputJourIdEcritureAv")
    await j_input.click()
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await j_input.type(jour, delay=50) 
    await j_input.press("Tab")
    await wait_for_spinner(page)

    # 4. SELECT MOIS
    month_name = ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", 
                  "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"][month_idx]
    await nya_select_by_js(page, "inputMoisIdEcriture", month_name)
    await wait_for_spinner(page)

    # 5. FILL REFERENCE AND LIBELLE
    # These IDs are from your DOM snippet
    await page.locator("#idDocumentInputMD2").fill(entry["piece"])
    await page.locator("#inputLibelleIdMD2").fill(entry["libelle"])
    await page.keyboard.press("Tab")
    
    await wait_for_spinner(page)

async def fill_line(page: Page, idx: int, line: dict) -> None:
    await wait_for_spinner(page)
    # ── Row management ────────────────────────────────────────────────────
    # The form opens with a couple of default empty rows already present.
    # Only click "ajouterEcriture()" if row `idx` doesn't exist yet —
    # blindly adding a row for every idx>0 creates extra unfilled rows
    # that Axeane's own save validation rejects
    # ("L'écriture N° X doit avoir un crédit ou un débit").
    current_count = await page.locator("tbody tr.td-row").count()
    if idx >= current_count:
        # From your DOM: the add button is the .td-cb with fa-plus
        await page.locator(".td-cb .fa-plus").first.click()
        # Wait for the specific row to exist
        await page.locator("tbody tr.td-row").nth(idx).wait_for(state="visible", timeout=5000)
        await wait_for_spinner(page)

    # Get the specific row (needed for the Compte field which has a dynamic ID)
    row = page.locator("tbody tr.td-row").nth(idx)
    
    # Fill Compte (Account) using Typeahead keyboard simulation
    # The ID for compte is dynamic (e.g., cc_0_3), so we locate it by its column class 'tc-cp'
    compte_input = row.locator("td.tc-cp input.form-control")
    await wait_for_spinner(page)
    await compte_input.scroll_into_view_if_needed()
    await compte_input.click()
    await compte_input.fill(line["account"])
    await wait(page, 300)
    await wait_for_spinner(page)
    
    # Select the first typeahead suggestion and confirm with Enter
    await page.keyboard.press("ArrowDown")
    await wait(page, 100)
    await page.keyboard.press("Enter")
    await wait(page, 400)
    await wait_for_spinner(page)

    # Fill Extra Libellé (using stable ID)
    lb_input = page.locator(f"#exlibelle{idx}")
    await wait_for_spinner(page)
    await lb_input.scroll_into_view_if_needed()
    await lb_input.click()
    await lb_input.fill(line["label"])
    await page.keyboard.press("Tab")
    await wait(page, 300)
    await wait_for_spinner(page)

    # Fill Débit (using stable ID)
    debit = float(line["debit"])
    if debit > 0:
        d_input = page.locator(f"#debit-eav-{idx}")
        await wait_for_spinner(page)
        await d_input.scroll_into_view_if_needed()
        await d_input.click()
        await d_input.fill(f"{debit:.3f}")
        await page.keyboard.press("Tab")
        await wait(page, 300)
        await wait_for_spinner(page)

    # Fill Crédit (using stable ID)
    credit = float(line["credit"])
    if credit > 0:
        c_input = page.locator(f"#credit-eav-{idx}")
        await wait_for_spinner(page)
        await c_input.scroll_into_view_if_needed()
        await c_input.click()
        await c_input.fill(f"{credit:.3f}")
        await page.keyboard.press("Tab")
        await wait(page, 300)
        await wait_for_spinner(page)

async def cleanup_extra_rows(page: Page, needed: int) -> None:
    """
    Safety net: if more rows exist than the entry actually needed
    (e.g. an unexpected leftover default row), delete the extras
    before saving so Axeane's save validation doesn't reject them.
    """
    current_count = await page.locator("tbody tr.td-row").count()
    for idx in range(current_count - 1, needed - 1, -1):
        row = page.locator("tbody tr.td-row").nth(idx)
        deleted = await page.evaluate(
            """(rowEl) => {
                const btn = rowEl.querySelector("button[ng-click*='supprimer'], button[ng-click*='delete'], .fa-trash, .fa-trash-o");
                if (btn) { (btn.closest('button') || btn).click(); return true; }
                return false;
            }""",
            await row.element_handle(),
        )
        if deleted:
            log(f"  🗑️ Removed leftover empty row {idx}")
            await wait(page, 300)
        else:
            log(f"  ⚠️ Leftover empty row {idx} found but no delete button matched — leaving as-is")
            break

# 🆕 NEW: Verification System
async def verify_entry(page: Page, entry: dict, update_ui_callback):
    ref = entry['docRef']
    
    # 1. Color row Yellow (Processing)
    if update_ui_callback: update_ui_callback(ref, 'processing')
        
    # 2. Open "Dernières écritures" panel
    is_hidden = await page.evaluate("""() => {
        const zone = document.querySelector('.td-last-zone');
        return zone ? zone.classList.contains('td-anim-hidden') : true;
    }""")
    if is_hidden:
        await page.evaluate("document.querySelector('button[ng-click=\"showAndHideLastEc()\"]').click()")
        await wait(page, 500)
        
    # 3. Verify the current entry using the live KPI bar (Tot Débit, Tot Crédit, Solde)
    try:
        # 🆕 Added .first to avoid strict mode violation from the hidden foreign currency Solde badge
        tot_debit = await page.locator(".ax-badge-kpi.ax-badge-green .ax-badge-kpi-value").first.text_content(timeout=2000)
        tot_credit = await page.locator(".ax-badge-kpi.ax-badge-red .ax-badge-kpi-value").first.text_content(timeout=2000)
        solde = await page.locator(".ax-badge-kpi.ax-badge-purple .ax-badge-kpi-value").first.text_content(timeout=2000)
        
        log(f"  📊 Verification -> Débit: {tot_debit.strip()} | Crédit: {tot_credit.strip()} | Solde: {solde.strip()}")
        is_balanced = "0,000" in solde or "0.000" in solde
    except Exception as e:
        log(f"  ⚠️ Could not read KPI bar: {e}")
        is_balanced = False

    # 4. Close "Dernières écritures" panel
    is_hidden_after = await page.evaluate("""() => {
        const zone = document.querySelector('.td-last-zone');
        return zone ? zone.classList.contains('td-anim-hidden') : true;
    }""")
    if not is_hidden_after:
        await page.evaluate("document.querySelector('button[ng-click=\"showAndHideLastEc()\"]').click()")
        await wait(page, 300)
        
    # 5. Color row Green (Success) or Red (Error)
    if update_ui_callback: update_ui_callback(ref, 'success' if is_balanced else 'error')
        
    return is_balanced

async def check_for_error_popup(page: Page) -> str | None:
    """
    After clicking Enregistrer, Axeane may show an "Erreur" modal
    (e.g. "L'écriture N° 5 doit avoir un crédit ou un débit").
    Returns the error message if found (and closes the modal), else None.
    """
    await wait(page, 400)
    try:
        msg = await page.evaluate("""() => {
            const candidates = document.querySelectorAll('.modal, .ax-modal, [role="alertdialog"], .swal2-popup');
            for (const el of candidates) {
                if (el.offsetParent === null) continue;
                const text = el.textContent || '';
                if (/erreur/i.test(text)) {
                    const closeBtn = el.querySelector('.close, button[aria-label="Close"], .swal2-confirm, .swal2-close');
                    if (closeBtn) closeBtn.click();
                    return text.trim().replace(/\\s+/g, ' ');
                }
            }
            return null;
        }""")
        return msg
    except Exception:
        return None

async def save_entry(page: Page) -> str | None:
    """Clicks Enregistrer and returns an error message string if Axeane rejected the save, else None."""
    await wait_for_spinner(page)
    await page.locator("#ec-save").scroll_into_view_if_needed()
    await page.locator("#ec-save").click()
    await wait(page, 1500)
    await wait_for_spinner(page)
    return await check_for_error_popup(page)

async def reset_form(page: Page) -> None:
    """Ensure the form is completely cleared and no modals are blocking the UI."""
    await wait_for_spinner(page)
    
    # Click the reset button
    btn = page.locator("button[ng-click*='resetEcritures']")
    if await btn.count() > 0:
        await btn.first.click()
        await wait(page, 500)
    
    # SPECIAL FIX: Escape any stuck tooltips or menus
    await page.keyboard.press("Escape")
    await wait_for_spinner(page)

# 🆕 UPDATED: Accepts the UI callback
# ... [Keep all other functions exactly as they were] ...

async def run(entries: list[dict], update_ui_callback=None, stop_event=None) -> None:
    cdp_url = SETTINGS.get("cdp_url", "http://localhost:9222")
    async with async_playwright() as pw:
        log(f"Connecting to CDP at {cdp_url}...")
        browser: Browser = await pw.chromium.connect_over_cdp(cdp_url)
        
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page: Page = next(
            (p for p in all_pages if "axeane" in p.url.lower() or "kompta" in p.url.lower()),
            all_pages[0] if all_pages else None,
        )
        
        if page is None: raise RuntimeError("No page found. Is Axeane Kompta open?")
        log(f"Connected to: {page.url}")
        await page.bring_to_front()

        await do_login(page)
        await select_context(page)
        await navigate_to_saisie(page)

        total = len(entries)
        for i, entry in enumerate(entries):
            # 🆕 Check if the user clicked the Stop button
            if stop_event and stop_event.is_set():
                log("🛑 Automation stopped by user.")
                break
                
            if not entry.get("balanced", True):
                log(f"SKIP {entry['docRef']} — not balanced locally ({entry.get('error_reason')})")
                if update_ui_callback: update_ui_callback(entry['docRef'], 'error')
                continue

            log(f"[{i+1}/{total}] {entry['docRef']} — {len(entry['lines'])} lines")
            
            await wait_for_spinner(page)
            await reset_form(page)  # Ensure fresh start for each entry
            await wait_for_spinner(page)
            await fill_header(page, entry)
            for j, line in enumerate(entry["lines"]):
                log(f"  line {j}: {line['account']} D:{line['debit']} C:{line['credit']}")
                await fill_line(page, j, line)

            # Safety net: remove any leftover default rows beyond what we filled
            await cleanup_extra_rows(page, len(entry["lines"]))

            is_verified = await verify_entry(page, entry, update_ui_callback)
            
            if is_verified:
                save_error = await save_entry(page)
                if save_error:
                    log(f"  ❌ Axeane rejected save for {entry['docRef']}: {save_error}")
                    if update_ui_callback: update_ui_callback(entry['docRef'], 'error')
                else:
                    await reset_form(page)
            else:
                log(f"  ❌ SKIPPING SAVE: Entry {entry['docRef']} is not balanced in Axeane UI!")
                await reset_form(page)

        log("Done — all entries processed.")
    