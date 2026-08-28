import binascii
import struct
import zlib
from pathlib import Path
from tempfile import gettempdir
from time import perf_counter

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ROOT / "public" / "signal-observatory-icon.png"
SCREENSHOT_DIR = Path(gettempdir()) / "bili-opinion-wordcloud-mask"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
URL = "http://127.0.0.1:5173/wordcloud-mask-harness.html"


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    checksum = binascii.crc32(kind + payload) & 0xFFFFFFFF
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)


def rgba_png(width: int, height: int, pixel: bytes) -> bytes:
    row = b"\x00" + pixel * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + png_chunk(b"IDAT", zlib.compress(row * height))
        + png_chunk(b"IEND", b"")
    )


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1280, "height": 900}, accept_downloads=True)
    console_problems: list[str] = []
    failed_requests: list[str] = []
    request_urls: list[str] = []
    page.on(
        "console",
        lambda message: console_problems.append(f"{message.type}: {message.text}")
        if message.type == "error"
        or (
            message.type == "warning"
            and "willReadFrequently" not in message.text
        )
        else None,
    )
    page.on("requestfailed", lambda request: failed_requests.append(f"{request.url}: {request.failure}"))
    page.on("request", lambda request: request_urls.append(request.url))

    started = perf_counter()
    page.goto(URL, wait_until="networkidle")
    page.get_by_role("heading", name="词云").wait_for()
    initial_seconds = perf_counter() - started
    assert page.get_by_text("词频列表 (200)").is_visible()

    page.get_by_role("button", name="词云样式").click()
    started = perf_counter()
    file_input = page.locator('input[type="file"]')
    file_input.set_input_files(str(IMAGE))
    file_input.set_input_files({
        "name": "invalid.txt",
        "mimeType": "text/plain",
        "buffer": b"not an image",
    })
    page.get_by_alt_text("词云蒙版预览，黑色为词语区域").wait_for()
    page.get_by_label("启用轮廓蒙版").wait_for(state="visible")
    page.wait_for_function("document.querySelector('input[aria-label=\"启用轮廓蒙版\"]')?.checked === true")
    upload_seconds = perf_counter() - started
    assert upload_seconds < 30

    source_before_invalid_replacement = page.get_by_alt_text("原图缩略图").get_attribute("src")
    file_input.set_input_files({
        "name": "white.png",
        "mimeType": "image/png",
        "buffer": rgba_png(1, 1, b"\xff\xff\xff\xff"),
    })
    page.get_by_text("可生成区域过小，请调整阈值或反转词语区域。").wait_for()
    assert page.get_by_alt_text("原图缩略图").get_attribute("src") != source_before_invalid_replacement
    assert page.get_by_label("启用轮廓蒙版").is_disabled()
    assert not page.get_by_label("启用轮廓蒙版").is_checked()

    file_input.set_input_files(str(IMAGE))
    page.wait_for_function("document.querySelector('input[aria-label=\"启用轮廓蒙版\"]')?.checked === true")
    first_ratio = page.locator(".wordcloud-style__area").inner_text()

    min_size = page.get_by_label("最小字号")
    max_size = page.get_by_label("最大字号")
    min_size.fill("1")
    assert min_size.input_value() == "1"
    page.get_by_role("heading", name="词云").click()
    assert min_size.input_value() == "8"
    max_size.fill("0")
    assert max_size.input_value() == "0"
    page.get_by_role("heading", name="词云").click()
    assert max_size.input_value() == "24"

    min_size.fill("40")
    min_size.press("Enter")
    assert min_size.input_value() == "23"
    assert max_size.input_value() == "24"

    max_size.fill("100")
    max_size.press("Enter")
    min_size.fill("40")
    min_size.press("Enter")
    max_size.fill("24")
    max_size.press("Enter")
    assert min_size.input_value() == "40"
    assert max_size.input_value() == "41"
    assert not page.get_by_text("最小字号必须小于最大字号。").is_visible()

    page.get_by_role("button", name="颜色方案").click()
    page.get_by_role("option", name="单色").click()
    page.wait_for_timeout(450)
    chart_canvas = page.locator(".wordcloud-card__chart canvas")
    before_color_change = chart_canvas.evaluate("canvas => canvas.toDataURL()")
    single_color = page.get_by_label("单色")
    single_color.fill("#ff0000")
    single_color.fill("#00ff00")
    single_color.fill("#0000ff")
    assert chart_canvas.evaluate("canvas => canvas.toDataURL()") == before_color_change
    page.wait_for_timeout(450)
    assert chart_canvas.evaluate("canvas => canvas.toDataURL()") != before_color_change

    page.get_by_role("button", name="颜色方案").click()
    page.get_by_role("option", name="家族多色").click()
    assert page.locator(".wordcloud-style__family-preview span").count() == 6
    family_opacity = page.locator(".wordcloud-style__family input[type='range']")
    family_opacity.fill("20")
    family_opacity.fill("45")
    family_opacity.fill("70")
    assert family_opacity.input_value() == "70"
    page.get_by_role("button", name="字体").click()
    page.get_by_role("option", name="微软雅黑").click()
    page.get_by_label("在词云中叠加原图").check()
    overlay_range = page.locator(".wordcloud-style__source-overlay input[type='range']")
    overlay_range.fill("35")
    assert overlay_range.input_value() == "35"
    page.screenshot(path=str(SCREENSHOT_DIR / "wordcloud-mask-wide.png"), full_page=True)

    threshold_range = page.locator(".wordcloud-style__section").first.locator("input[type='range']").first
    threshold_range.fill("210")
    assert page.locator(".wordcloud-style__area").inner_text() == first_ratio
    page.wait_for_function(
        "previous => document.querySelector('.wordcloud-style__area')?.textContent !== previous",
        arg=first_ratio,
    )
    first_ratio = page.locator(".wordcloud-style__area").inner_text()

    page.get_by_label("反转词语区域").check()
    page.wait_for_function(
        "previous => document.querySelector('.wordcloud-style__area')?.textContent !== previous",
        arg=first_ratio,
    )
    inverted_ratio = page.locator(".wordcloud-style__area").inner_text()
    assert inverted_ratio != first_ratio

    page.get_by_label("最小字号").fill("12")
    page.get_by_label("最小字号").press("Enter")
    page.get_by_label("最大字号").fill("60")
    page.get_by_label("最大字号").press("Enter")
    with page.expect_download(timeout=10_000) as download_info:
        page.get_by_role("button", name="下载").click()
    download = download_info.value
    download_path = Path(download.path())
    assert download_path.stat().st_size > 1000
    assert download_path.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    page.get_by_role("button", name="切换筛选加载").click()
    assert page.get_by_text("正在按当前筛选重新统计关键词…").is_visible()
    page.get_by_role("button", name="恢复筛选结果").click()
    page.get_by_alt_text("原图缩略图").wait_for()
    assert page.get_by_label("启用轮廓蒙版").is_checked()
    assert page.get_by_role("button", name="颜色方案").inner_text().strip() == "家族多色"
    assert page.get_by_label("最小字号").input_value() == "12"
    assert page.get_by_label("在词云中叠加原图").is_checked()

    first_keyword = page.locator(".wordcloud-card__keywords button").first
    first_keyword.click()
    assert first_keyword.get_attribute("title") == "点击加入词云"

    page.get_by_role("button", name="切换分析").click()
    page.get_by_alt_text("原图缩略图").wait_for(state="detached")
    assert page.get_by_label("启用轮廓蒙版").is_disabled()
    assert page.get_by_role("button", name="颜色方案").inner_text().strip() == "家族多色"
    assert first_keyword.get_attribute("title") == "点击排除"

    file_input.set_input_files({
        "name": "invalid.txt",
        "mimeType": "text/plain",
        "buffer": b"not an image",
    })
    assert page.get_by_text("仅支持 JPG、PNG 或 WebP 图片。").is_visible()

    for _ in range(10):
        page.locator('input[type="file"]').set_input_files(str(IMAGE))
        page.get_by_alt_text("词云蒙版预览，黑色为词语区域").wait_for()
        page.wait_for_function("document.querySelector('input[aria-label=\"启用轮廓蒙版\"]')?.checked === true")

    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_timeout(250)
    layout_direction = page.locator(".wordcloud-card__layout").evaluate("element => getComputedStyle(element).flexDirection")
    preview_columns = page.locator(".wordcloud-style__previews").evaluate("element => getComputedStyle(element).gridTemplateColumns")
    assert layout_direction == "column"
    assert " " not in preview_columns.strip()
    page.screenshot(path=str(SCREENSHOT_DIR / "wordcloud-mask-mobile.png"), full_page=True)

    external_requests = [
        url
        for url in request_urls
        if not url.startswith(("http://127.0.0.1:5173/", "blob:http://127.0.0.1:5173/"))
    ]
    assert not external_requests, external_requests
    assert not failed_requests, failed_requests
    assert not console_problems, console_problems
    print({
        "initial_seconds": round(initial_seconds, 3),
        "upload_and_layout_seconds": round(upload_seconds, 3),
        "first_ratio": first_ratio,
        "inverted_ratio": inverted_ratio,
        "download_bytes": download_path.stat().st_size,
        "request_count": len(request_urls),
        "layout_direction": layout_direction,
        "preview_columns": preview_columns,
    })
    browser.close()
