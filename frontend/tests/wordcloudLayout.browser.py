"""Focused browser regression for word-cloud layout and its inline style panel."""

from playwright.sync_api import sync_playwright


URL = "http://127.0.0.1:5173/wordcloud-mask-harness.html"


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 966, "height": 898})
    page.add_init_script(
        """
        (() => {
          let count = 0;
          const dispatch = EventTarget.prototype.dispatchEvent;
          EventTarget.prototype.dispatchEvent = function(event) {
            if (event?.type === 'wordcloudstart') count += 1;
            return dispatch.call(this, event);
          };
          Object.defineProperty(window, '__wordCloudStartCount', { get: () => count });
        })();
        """
    )
    page.goto(URL, wait_until="networkidle")
    page.get_by_role("heading", name="词云", exact=True).wait_for()
    page.wait_for_timeout(350)
    assert page.evaluate("window.__wordCloudStartCount") == 1

    card = page.locator(".wordcloud-card")
    card_box = card.bounding_box()
    page.get_by_role("button", name="样式设置", exact=True).click()
    drawer = page.get_by_role("dialog", name="词云样式设置")
    drawer.wait_for()
    drawer_box = drawer.bounding_box()
    backdrop_filter = drawer.evaluate("element => getComputedStyle(element).backdropFilter")
    assert drawer.evaluate("element => getComputedStyle(element).position") == "absolute"
    assert "blur" in backdrop_filter
    assert card_box is not None and drawer_box is not None
    assert drawer_box["x"] >= card_box["x"] and drawer_box["y"] >= card_box["y"]
    assert drawer_box["x"] + drawer_box["width"] <= card_box["x"] + card_box["width"] + 1, (drawer_box, card_box)
    assert drawer_box["y"] + drawer_box["height"] <= card_box["y"] + card_box["height"] + 1
    browser.close()
