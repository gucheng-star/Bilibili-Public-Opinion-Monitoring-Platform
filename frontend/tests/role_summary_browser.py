"""Browser smoke for the single-video role-based AI briefing controls.

Run this through the local Vite dev server with a synthetic fixture analysis.
The summary endpoint is fulfilled in-browser, so no model request is made.
"""

from __future__ import annotations

import json

from playwright.sync_api import sync_playwright


BASE_URL = "http://127.0.0.1:5173/#/"
FIXTURE_TITLE = "情感分析模拟评论测试集（不抓取）"


def main() -> None:
    captured_posts: list[dict] = []
    filters = {
        "gender": "all", "dateFrom": "", "dateTo": "", "region": "",
        "sentiment": "all", "duplicateMode": "include", "sourceAnalysisId": "all",
    }

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 320, "height": 900})
        page.set_default_timeout(5000)

        def fulfill_summary(route):
            if route.request.method == "POST":
                captured_posts.append(json.loads(route.request.post_data or "{}"))
                payload = {
                    "id": 1, "analysis_id": 1, "filters": filters, "filter_hash": "browser-smoke",
                    "interpretation_view": "creator", "report_mode": "standard", "thinking_status": "unsupported",
                    "summary_text": "## 观察\n观众集中讨论解释是否清晰。\n\n## 依据与边界\n仅依据筛选统计和代表性样本。\n\n## 建议线索\n可补充关键概念的说明。",
                    "provider": "custom", "model": "browser-mock", "matched_count": 24, "sampled_count": 3,
                    "created_at": "2026-09-04T12:00:00", "updated_at": "2026-09-04T12:00:00", "stale": False,
                }
                route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
            else:
                route.fulfill(status=200, content_type="application/json", body="[]")

        page.route(
            "**/api/auth/status",
            lambda route: route.fulfill(
                status=200, content_type="application/json", body='{"logged_in": true}'
            ),
        )
        page.route(
            "**/api/history?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps([{
                    "id": 1, "bv": "TEST-SENTIMENT-24", "video_title": FIXTURE_TITLE,
                    "video_cover": "", "total_comments": 24, "status": "done",
                    "mode": "nlp", "created_at": "2026-09-04T12:00:00",
                }], ensure_ascii=False),
            ),
        )
        page.route("**/api/summaries/1", fulfill_summary)
        page.goto(BASE_URL, wait_until="domcontentloaded")
        page.locator(".history-rail__toggle").wait_for(timeout=5000)
        if page.locator(".history-rail__toggle").get_attribute("aria-expanded") != "true":
            page.locator(".history-rail__toggle").click()
        page.locator(".history-panel__record").first.wait_for()
        page.locator(".history-panel__record").first.click()
        page.locator(".ai-summary-card").wait_for()

        boundaries: set[str] = set()
        for option_index in range(4):
            page.locator(".ai-summary-controls .filter-select__trigger").first.click()
            page.locator(".filter-select__option").nth(option_index).click()
            boundaries.add(page.locator(".ai-summary-boundary").inner_text())
        assert len(boundaries) == 4
        assert not captured_posts, "changing controls must not call the model endpoint"

        page.locator(".ai-summary-controls .filter-select__trigger").first.click()
        page.locator(".filter-select__option").nth(2).click()
        page.locator(".ai-summary-controls .filter-select__trigger").nth(1).click()
        page.locator(".filter-select__option").nth(1).click()
        page.locator(".ai-summary-card__action").click()
        page.locator(".ai-summary-meta__notice").wait_for()
        assert captured_posts == [{
            "filters": filters, "regenerate": False,
            "interpretationView": "creator", "reportMode": "standard",
        }]
        assert page.locator(".ai-summary-standard-report").is_visible()
        assert page.locator(".ai-summary-standard-report h4").all_inner_texts() == ["观察", "依据与边界", "建议线索"]
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        initial_theme = page.evaluate("document.documentElement.dataset.theme")
        page.locator(".theme-toggle").click()
        page.wait_for_timeout(700)
        assert page.evaluate("document.documentElement.dataset.theme") != initial_theme
        assert page.locator(".ai-summary-controls").is_visible()
        browser.close()


if __name__ == "__main__":
    main()
