"""Browser regression for settings-page unified select controls."""

from playwright.sync_api import sync_playwright


URL = "http://127.0.0.1:5173/#/settings"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1001, "height": 898})
    page.goto(URL, wait_until="networkidle")

    controls = page.locator(".llm-config-grid .filter-select")
    controls.first.wait_for()
    assert controls.count() == 6
    assert page.locator(".llm-config-grid select").count() == 0

    trigger = controls.first.get_by_role("button")
    trigger.click()
    selected = page.locator(".llm-config-grid .filter-select__option[aria-selected='true']").first
    selected.wait_for()
    style = selected.evaluate(
        "element => ({ color: getComputedStyle(element).color, background: getComputedStyle(element).backgroundColor, boxShadow: getComputedStyle(element).boxShadow })"
    )
    assert "251, 114, 153" not in style["color"]
    assert "251, 114, 153" not in style["background"]
    assert style["boxShadow"] == "none"
    browser.close()
