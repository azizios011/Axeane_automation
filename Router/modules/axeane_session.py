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
    """Reads the currently selected Entreprise and Exercice directly from the Axeane UI."""
    try:
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

async def select_context(page: Page, entreprise: str, exercice: str) -> None:
    if entreprise == "Unknown" or exercice == "Unknown":
        log("⚠️ Context unknown, skipping automatic selection. Please ensure it's correct in the browser.")
        return
        
    log(f"Ensuring context: {entreprise} / {exercice}")
    await nya_select_by_js(page, "entreprise", entreprise)
    await wait(page, 800)
    await nya_select_by_js(page, "exercice", exercice)
    await wait(page, 800)

async def navigate_to_saisie(page: Page) -> None:
    log("Navigating to Saisie des écritures...")
    await page.locator("span.ng-binding:text('Comptabilité générale')").first.click()
    await wait(page, 600)
    await page.locator(".kc-dock-item[data-code='ECRITURE_AVANCEE']").click()
    await wait(page, 1500)
    log("Saisie des écritures opened")

async def fill_header(page: Page, entry: dict) -> None:
    date = entry["date"]
    month = int(date.split("/")[1])
    jour = date.split("/")[0]
    
    d = page.locator("#ec-date-creation")
    await d.click(); await d.fill(date); await d.press("Tab")
    await wait(page)
    
    await nya_select_by_js(page, "jo-eav", entry["journal"])
    await nya_select_by_js(page, "inputMoisIdEcriture", ["", "Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"][month])
    
    j = page.locator("#inputJourIdEcritureAv")
    await j.click(); await j.fill(jour); await j.press("Tab")
    await wait(page)
    
    p = page.locator("#idDocumentInputMD2")
    await p.click(); await p.fill(entry["piece"]); await p.press("Tab")
    await wait(page)
    
    lb = page.locator("#inputLibelleIdMD2")
    await lb.click(); await lb.fill(entry["libelle"]); await lb.press("Tab")
    await wait(page)

async def fill_line(page: Page, idx: int, line: dict) -> None:
    if idx > 0:
        await page.locator("button[ng-click='ajouterEcriture()']").click()
        await wait(page, 400)
    
    compte = page.locator(f"#cc_0_{idx}")
    await compte.click()
    await compte.fill(line["account"])
    await wait(page, 700)
    
    try:
        await page.wait_for_selector(".dropdown-menu.ng-scope li.nya-bs-option:not(.no-search-result), ul.dropdown-menu li:not(.no-search-result)", timeout=2500)
        await page.locator(".dropdown-menu.ng-scope li:not(.no-search-result), ul.dropdown-menu li:not(.no-search-result)").first.click()
    except PWTimeout:
        await compte.press("Tab")
    await wait(page)

    lb = page.locator(f"#exlibelle{idx}")
    await lb.click(); await lb.fill(line["label"]); await lb.press("Tab")
    await wait(page)

    debit = float(line["debit"])
    if debit > 0:
        d = page.locator(f"#debit-eav-{idx}")
        await d.click(); await d.fill(f"{debit:.3f}"); await d.press("Tab")
        await wait(page)

    credit = float(line["credit"])
    if credit > 0:
        c = page.locator(f"#credit-eav-{idx}")
        await c.click(); await c.fill(f"{credit:.3f}"); await c.press("Tab")
        await wait(page)

async def save_entry(page: Page) -> None:
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
        
        # 🆕 Dynamically detect and use the current context from the browser
        entreprise, exercice = await get_current_context(page)
        log(f"✅ Detected Browser Context: {entreprise} / {exercice}")
        
        await select_context(page, entreprise, exercice)
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
        