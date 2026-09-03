"""Browser acceptance checks for the GLM option in the independent LLM settings."""

from playwright.sync_api import sync_playwright


URL = "http://127.0.0.1:5173/#/settings"


def choose(page, aria_label: str, option_name: str) -> None:
    trigger = page.get_by_role("button", name=aria_label)
    trigger.click()
    page.get_by_role("option", name=option_name).click()


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1001, "height": 898})
    page.goto(URL, wait_until="networkidle")

    for aria_label in ("情绪分析模型供应商", "智能总结模型供应商"):
        trigger = page.get_by_role("button", name=aria_label)
        trigger.wait_for()
        trigger.click()
        assert page.get_by_role("option", name="阿里百炼").count() == 1
        assert page.get_by_role("option", name="DeepSeek").count() == 1
        assert page.get_by_role("option", name="智谱 GLM").count() == 1
        assert page.get_by_role("option", name="自定义兼容接口").count() == 1
        page.keyboard.press("Escape")

    choose(page, "情绪分析模型供应商", "智谱 GLM")
    sentiment_block = page.locator(".llm-config-block").first
    assert sentiment_block.locator(".llm-base-url input").input_value() == "https://open.bigmodel.cn/api/paas/v4/"
    assert sentiment_block.get_by_role("button", name="情绪分析模型模型").is_disabled()

    choose(page, "情绪分析模型供应商", "自定义兼容接口")
    manual_model = sentiment_block.get_by_role("textbox", name="情绪分析模型模型名称")
    manual_model.fill("local-compatible-model")
    assert manual_model.input_value() == "local-compatible-model"

    browser.close()
