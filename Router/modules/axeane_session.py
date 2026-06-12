import asyncio
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

async def wait(page: Page, ms: int = None) -> None:
    delay = ms if ms is not None else SETTINGS.get("slow_mo", 300)
    await page.wait_for_timeout(delay)

async def wait_for_spinner(page: Page, timeout: int = 60000) -> None:
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
    except PWTimeout:
        pass

async def nya_select_by_js(page: Page, ol_id: str, option_text: str) -> None:
    """JS-Hook: Selects dropdown and forces Angular brain update."""
    success = await page.evaluate("""([olId, text]) => {
        const ol = document.getElementById(olId);
        if (!ol) return false;
        const options = ol.querySelectorAll('li.nya-bs-option a');
        for (const a of options) {
            if (a.textContent.trim().toLowerCase().includes(text.toLowerCase().trim())) {
                a.click();
                const scope = angular.element(ol).scope();
                if (scope && !scope.$$phase) scope.$apply();
                return true;
            }
        }
        return false;
    }""", [ol_id, option_text])
    if not success:
        log(f"    ⚠️ JS: Could not find '{option_text}' in {ol_id}")
    await wait(page, 500)

async def reset_form(page: Page) -> None:
    """JS-Hook: Wipes the Angular Model clean."""
    log("  🧹 JS: Resetting form state...")
    await page.evaluate("""() => {
        const el = document.getElementById('ec-td-panel-sp');
        if (!el) return;
        const scope = angular.element(el).scope();
        if (scope.resetEcritures) scope.resetEcritures();
        if (scope.unsetModele) scope.unsetModele();
        if (!scope.$$phase) scope.$apply();
    }""")
    await page.keyboard.press("Escape")
    await wait_for_spinner(page)

async def fill_header(page: Page, entry: dict) -> None:
    """JS-Hook: Injects Jour, Mois, Ref, and Libelle directly into memory."""
    await wait_for_spinner(page)
    
    # 1. Journal Switch (Must be first)
    await nya_select_by_js(page, "jo-eav", entry["journal"])
    
    # 2. Inject Data
    parts = entry["date"].split("/")
    jour = parts[0]
    month_idx = int(parts[1])
    
    await page.evaluate("""([j, mIdx, p, l]) => {
        const el = document.getElementById('ecritureForm');
        if (!el) return;
        const scope = angular.element(el).scope();
        
        // Direct injection into the model
        scope.items.jourDocComptable = j;
        // Month list is 0-indexed in JS, but 1-indexed in CSV (01=Jan)
        scope.items.selectedMoisDocComptable = scope.moisList[mIdx - 1];
        scope.ecritureGrouping.piece = p;
        scope.ecritureGrouping.libelle = l;
        
        if (!scope.$$phase) scope.$apply();
    }""", [jour, month_idx, entry["piece"], entry["libelle"]])
    
    log(f"  ✅ JS: Header Injected ({jour} / {month_idx})")
    await wait_for_spinner(page)

async def fill_line(page: Page, idx: int, line: dict) -> None:
    """JS-Hook: Adds row and populates model."""
    # 1. Add Row
    await page.evaluate("""() => {
        const el = document.getElementById('ec-td-panel-sp');
        const scope = angular.element(el).scope();
        scope.ajouterEcriture();
        if (!scope.$$phase) scope.$apply();
    }""")
    
    # 2. Inject row data (Except account which needs typeahead)
    await page.evaluate("""([i, acc, lbl, deb, cre]) => {
        const el = document.getElementById('ec-td-panel-sp');
        const scope = angular.element(el).scope();
        const row = scope.ecritureGrouping.ecritureComptables[i];
        
        row.extraLibelle = lbl;
        row.debit = deb;
        row.credit = cre;
        
        if (!scope.$$phase) scope.$apply();
    }""", [idx, line["account"], line["label"], str(line["debit"]), str(line["credit"])])

    # 3. Account Selection (Requires keyboard to trigger Axeane's search logic)
    input_id = f"cc_{idx}_3"
    input_selector = f"#{input_id}"
    await page.locator(input_selector).click()
    await page.keyboard.type(line["account"], delay=50)
    await wait(page, 600) # Wait for search
    await page.keyboard.press("ArrowDown")
    await page.keyboard.press("Enter")
    await wait_for_spinner(page)

async def verify_entry(page: Page, entry: dict, update_ui_callback):
    """JS-Hook: Reads the KPI Totals directly from Angular memory."""
    ref = entry['docRef']
    if update_ui_callback: update_ui_callback(ref, 'processing')
    
    solde_text = await page.evaluate("""() => {
        const el = document.querySelector('.ax-badge-purple .ax-badge-kpi-value');
        return el ? el.textContent.trim() : "error";
    }""")
    
    is_balanced = "0,000" in solde_text or "0.000" in solde_text
    log(f"  📊 Verification -> Solde: {solde_text} | Balanced: {is_balanced}")
    
    if update_ui_callback: 
        update_ui_callback(ref, 'success' if is_balanced else 'error')
    return is_balanced

async def save_entry(page: Page) -> str | None:
    await wait_for_spinner(page)
    await page.locator("#ec-save").click()
    await wait(page, 1000)
    
    # Check for error popup
    return await page.evaluate("""() => {
        const modal = document.querySelector('.modal.in, .swal2-popup');
        if (modal && /erreur/i.test(modal.textContent)) {
            const btn = modal.querySelector('button');
            if (btn) btn.click();
            return modal.textContent.trim();
        }
        return null;
    }""")

# ... (Include run(), do_login(), select_context() from previous version) ...
async def run(entries: list[dict], update_ui_callback=None, stop_event=None, browser_log_callback=None) -> None:
    cdp_url = SETTINGS.get("cdp_url", "http://localhost:9222")
    async with async_playwright() as pw:
        log(f"Connecting to CDP at {cdp_url}...")
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page: Page = next((p for p in all_pages if "axeane" in p.url.lower() or "kompta" in p.url.lower()), all_pages[0])
        
        if browser_log_callback:
            page.on("console", lambda msg: browser_log_callback(f"🌐 BROWSER: {msg.text}") if msg.type == "error" else None)
            page.on("pageerror", lambda exc: browser_log_callback(f"💥 PAGE CRASH: {exc}"))

        await page.bring_to_front()
        # await do_login(page)  # Optional if already logged in via CDP
        # await select_context(page)
        # await navigate_to_saisie(page)

        for i, entry in enumerate(entries):
            if stop_event and stop_event.is_set(): break
            log(f"[{i+1}/{len(entries)}] {entry['docRef']}")
            
            await reset_form(page)
            await fill_header(page, entry)
            
            for j, line in enumerate(entry["lines"]):
                await fill_line(page, j, line)

            if await verify_entry(page, entry, update_ui_callback):
                err = await save_entry(page)
                if err: log(f"  ❌ Save Error: {err}")
            else:
                log("  ❌ Unbalanced in UI, skipping save.")
                