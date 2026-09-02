"""Light-theme browser checks for the button hierarchy and selection feedback."""

from playwright.sync_api import sync_playwright


ROOT_URL = "http://127.0.0.1:5173/#/"
SETTINGS_URL = "http://127.0.0.1:5173/#/settings"
DETAIL_URL = "http://127.0.0.1:5173/#/analysis/24/comments"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1001, "height": 898})

    page.goto(ROOT_URL, wait_until="networkidle")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    preview = page.get_by_role("button", name="获取视频信息")
    preview.wait_for()
    assert preview.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(251, 114, 153)"

    slider = page.locator(".filter-bar .segmented").first
    history_tabs = page.get_by_role("tablist", name="历史类型")
    assert "segmented" in (history_tabs.get_attribute("class") or "")
    active = slider.locator("button.active")
    inactive = slider.locator("button:not(.active)").first
    assert active.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(255, 255, 255)"
    inactive.hover()
    assert inactive.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(214, 221, 231)"

    page.goto(DETAIL_URL, wait_until="networkidle")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    page.get_by_role("button", name="评论排序").wait_for()
    assert page.locator("select.select-sm").count() == 0

    page.goto(SETTINGS_URL, wait_until="networkidle")
    page.evaluate("document.documentElement.dataset.theme = 'light'")
    clear_key = page.get_by_role("button", name="清除密钥").first
    clear_key.wait_for()
    assert "btn-danger" in (clear_key.get_attribute("class") or "")
    assert clear_key.evaluate("element => getComputedStyle(element).backgroundColor") == "rgb(220, 38, 38)"
    browser.close()
