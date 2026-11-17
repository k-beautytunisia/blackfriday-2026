from pathlib import Path
import json
import subprocess
import time
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).parent
PORT = 8091
URL = f"http://127.0.0.1:{PORT}/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, executable_path="/usr/bin/chromium", args=["--no-sandbox"])
    desktop = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
    network_calls = []
    desktop.on("request", lambda req: network_calls.append(req.url))
    desktop.goto(URL, wait_until="networkidle", timeout=30000)
    assert desktop.locator("body").evaluate("e => e.classList.contains('sync-ok')")
    assert "Préproduction" in desktop.locator("#previewRibbon").inner_text()
    assert "2026" in desktop.locator("#syncStamp").inner_text()
    assert desktop.locator("#popup").is_visible(timeout=5000)
    desktop.screenshot(path=str(ROOT / "preview-popup-desktop.png"), full_page=False)
    desktop.locator("#popCta").click()
    desktop.wait_for_timeout(1100)
    assert desktop.locator("#bfView").is_visible()
    desktop.wait_for_timeout(400)
    assert desktop.locator(".card[data-id]").count() >= 24
    desktop.screenshot(path=str(ROOT / "preview-shop-desktop.png"), full_page=False)

    data = json.loads((ROOT / "catalogue.json").read_text())
    ids = [p["id"] for p in data["products"][:3]]
    desktop.evaluate("pid => window.KBBF.add(pid,1)", ids[0])
    assert desktop.evaluate("window.KBBF.calculate().rate") == 10
    desktop.evaluate("pid => window.KBBF.add(pid,1)", ids[1])
    assert desktop.evaluate("window.KBBF.calculate().rate") == 15
    desktop.evaluate("pid => window.KBBF.add(pid,1)", ids[2])
    assert desktop.evaluate("window.KBBF.calculate().rate") == 20
    result = desktop.evaluate("window.KBBF.calculate()")
    assert result["units"] == 3, result
    assert result["rate"] == 20, result
    assert result["total"] == result["subtotal"] - result["discount"], result
    desktop.locator("#cartBtn").click()
    assert "simulation" in desktop.locator("#drFoot").inner_text().lower() or "simul" in desktop.locator("#drFoot").inner_text().lower()
    desktop.screenshot(path=str(ROOT / "preview-cart-desktop.png"), full_page=False)
    desktop.locator("#checkout").click()
    assert desktop.locator("#modal").is_visible()
    assert "aucune commande" in desktop.locator("#modal").inner_text().lower()
    assert not any("/api/" in url for url in network_calls), network_calls
    assert not any("/api/trpc" in url for url in network_calls), network_calls
    assert desktop.locator("footer").count() == 0

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.goto(URL, wait_until="networkidle", timeout=30000)
    assert mobile.locator("body").evaluate("e => e.classList.contains('sync-ok')")
    mobile.screenshot(path=str(ROOT / "preview-popup-mobile.png"), full_page=False)
    mobile.locator("#popCta").click()
    mobile.wait_for_timeout(2200)
    assert mobile.locator("#bfView").is_visible()
    overflow = mobile.evaluate("document.documentElement.scrollWidth > window.innerWidth")
    assert not overflow, "horizontal overflow on mobile"
    mobile.screenshot(path=str(ROOT / "preview-shop-mobile.png"), full_page=False)

    # Fail closed when the embedded snapshot is stale: freeze Date.now at 45 minutes later.
    stale = browser.new_page(viewport={"width": 1000, "height": 800})
    stale.add_init_script("const real=Date.now; Date.now=()=>real()+46*60*1000;")
    stale.goto(URL, wait_until="networkidle", timeout=30000)
    assert stale.locator("body").evaluate("e => e.classList.contains('sync-error')")
    assert stale.locator("#syncError").is_visible()
    assert stale.locator("#bfView").is_hidden()

    print("PASS: fresh snapshot | popup | Black Friday universe | 116 in-stock items | 3-tier calculation | no order API | no footer | mobile | stale fail-closed")
    browser.close()
