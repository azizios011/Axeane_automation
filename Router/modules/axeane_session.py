import asyncio
from playwright.async_api import Browser, Page, TimeoutError as PWTimeout, async_playwright
from data.config import SETTINGS
from functions.helpers import log

async def wait(page: Page, ms: int = None) -> None:
    delay = ms if ms is not None else SETTINGS.get("slow_mo", 300)
    await page.wait_for_timeout(delay)

async def nya_select_by_js(page: Page, ol_id: str, option_text: str) -> None:
    """Click a nya-bs-select option by its visible text via JS."""
    found = await page.evaluate(
        """([olId, text]) => {
            const ol = document.getElementById(olId);
            if (!ol) return false;
            const spans = ol.querySelectorAll('li.nya-bs-option a span.ng-binding');
            for (const sp of spans) {
                if (sp.textContent.trim() === text) {
                    sp.closest('li').click();
                    const scope = angular.element(ol).scope();
                    if (scope) scope.$apply();
                    return true;
                }
            }
            return false;
        }""",
        [ol_id, option_text],
    )
    if not found:
        log(f"  WARNING: option '{option_text}' not found in #{ol_id}")
    await wait(page)

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
    date = entry["date"]
    month = int(date.split("/")[1])
    jour = date.split("/")[0]
    
    d = page.locator("#ec-date-creation")
    await d.scroll_into_view_if_needed()
    await d.click(); await d.fill(date); await d.press("Tab")
    await wait(page)
    
    journal_code = "CA" if entry.get("is_cash") else entry["journal"]
    await nya_select_by_js(page, "jo-eav", journal_code)
    await nya_select_by_js(page, "inputMoisIdEcriture", ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"][month])
    
    j = page.locator("#inputJourIdEcritureAv")
    await j.scroll_into_view_if_needed()
    await j.click(); await j.fill(jour); await j.press("Tab")
    await wait(page)
    
    p = page.locator("#idDocumentInputMD2")
    await p.scroll_into_view_if_needed()
    await p.click(); await p.fill(entry["piece"]); await p.press("Tab")
    await wait(page)
    
    lb = page.locator("#inputLibelleIdMD2")
    await lb.scroll_into_view_if_needed()
    await lb.click(); await lb.fill(entry["libelle"]); await lb.press("Tab")
    await wait(page)

async def fill_line(page: Page, idx: int, line: dict) -> None:
    # 1. Add new row via JS if needed
    if idx > 0:
        await page.evaluate("document.querySelector(\"button[ng-click='ajouterEcriture()']\").click()")
        await wait(page, 300)
        # Wait for the new row to actually render in the DOM before interacting
        await page.locator("tbody tr.td-row").nth(idx).wait_for(state="visible", timeout=5000)

    # 2. Get the specific row (needed for the Compte field which has a dynamic ID)
    row = page.locator("tbody tr.td-row").nth(idx)
    
    # 3. Fill Compte (Account) using Typeahead keyboard simulation
    # 🆕 The ID for compte is dynamic (e.g., cc_0_3), so we locate it by its column class 'tc-cp'
    compte_input = row.locator("td.tc-cp input.form-control")
    await compte_input.scroll_into_view_if_needed()
    await compte_input.click()
    await compte_input.fill(line["account"])
    await wait(page, 300)
    
    # Select the first typeahead suggestion and confirm with Enter
    await page.keyboard.press("ArrowDown")
    await wait(page, 100)
    await page.keyboard.press("Enter")
    await wait(page, 400)

    # 4. Fill Extra Libellé (using stable ID)
    lb_input = page.locator(f"#exlibelle{idx}")
    await lb_input.scroll_into_view_if_needed()
    await lb_input.click()
    await lb_input.fill(line["label"])
    await page.keyboard.press("Tab")
    await wait(page, 300)

    # 5. Fill Débit (using stable ID)
    debit = float(line["debit"])
    if debit > 0:
        d_input = page.locator(f"#debit-eav-{idx}")
        await d_input.scroll_into_view_if_needed()
        await d_input.click()
        await d_input.fill(f"{debit:.3f}")
        await page.keyboard.press("Tab")
        await wait(page, 300)

    # 6. Fill Crédit (using stable ID)
    credit = float(line["credit"])
    if credit > 0:
        c_input = page.locator(f"#credit-eav-{idx}")
        await c_input.scroll_into_view_if_needed()
        await c_input.click()
        await c_input.fill(f"{credit:.3f}")
        await page.keyboard.press("Tab")
        await wait(page, 300)

async def save_entry(page: Page) -> None:
    await page.locator("#ec-save").scroll_into_view_if_needed()
    await page.locator("#ec-save").click()
    await wait(page, 1500)

async def reset_form(page: Page) -> None:
    btn = page.locator("button[ng-click*='resetEcritures']")
    if await btn.count() > 0:
        await btn.first.click()
        await wait(page, 500)

async def run(entries: list[dict]) -> None:
    cdp_url = SETTINGS.get("cdp_url", "http://localhost:9222")
    async with async_playwright() as pw:
        log(f"Connecting to CDP at {cdp_url}...")
        browser: Browser = await pw.chromium.connect_over_cdp(cdp_url)
        
        all_pages = [p for ctx in browser.contexts for p in ctx.pages]
        page: Page = next(
            (p for p in all_pages if "axeane" in p.url.lower() or "kompta" in p.url.lower()),
            all_pages[0] if all_pages else None,
        )
        
        if page is None:
            raise RuntimeError("No page found. Is Axeane Kompta open?")
            
        log(f"Connected to: {page.url}")
        await page.bring_to_front()

        await do_login(page)
        
        entreprise, exercice = await get_current_context(page)
        log(f"✅ Detected Browser Context: {entreprise} / {exercice}")
        
        if entreprise == "Unknown" or exercice == "Unknown":
            log("⚠️ WARNING: Could not detect context. Please ensure it's correct in the browser.")
        else:
            log(f"  Using context: {entreprise} / {exercice}")

        await select_context(page)
        await navigate_to_saisie(page)

        total = len(entries)
        for i, entry in enumerate(entries):
            if not entry.get("balanced", True):
                log(f"SKIP {entry['docRef']} — not balanced")
                continue

            log(f"[{i+1}/{total}] {entry['docRef']} — {len(entry['lines'])} lines")
            await fill_header(page, entry)
            for j, line in enumerate(entry["lines"]):
                log(f"  line {j}: {line['account']} D:{line['debit']} C:{line['credit']}")
                await fill_line(page, j, line)
            await save_entry(page)
            await reset_form(page)

        log("Done — all entries processed.")
        