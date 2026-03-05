"""Quick vision pipeline test — inject a banner into the DOM, screenshot it,
ask the vision model if it can see it, then clean up."""
import asyncio
import base64
import requests
from playwright.async_api import async_playwright

SCREENSHOT = r"C:\Files\Models\CosySim\data\har_files\users_dump_folder\screenshots\vision_test.png"
LMSTUDIO   = "http://localhost:1234/v1/chat/completions"
MODEL      = "qwen/qwen3-vl-4b"

INJECT_JS = """() => {
    const el = document.createElement('div');
    el.id = 'argus-vision-test';
    el.innerText = 'ARGUS VISION TEST - CAN YOU SEE ME?';
    el.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:999999',
        'background:#ff0066', 'color:white', 'font-size:28px',
        'font-weight:bold', 'text-align:center', 'padding:20px'
    ].join(';');
    document.body.appendChild(el);
}"""

REMOVE_JS = """() => {
    const el = document.getElementById('argus-vision-test');
    if (el) el.remove();
}"""


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]

        page = next((pg for pg in ctx.pages if "aistudio" in pg.url), None)
        if not page:
            print("No AIStudio tab found, using first page")
            page = ctx.pages[0]

        await page.bring_to_front()
        print(f"Page: {page.url}")

        # Inject banner
        await page.evaluate(INJECT_JS)
        print("Banner injected")

        # Screenshot
        await page.screenshot(path=SCREENSHOT)
        print(f"Screenshot saved: {SCREENSHOT}")

        # Remove banner
        await page.evaluate(REMOVE_JS)
        print("Banner removed")

    # Ask vision model
    b64 = base64.b64encode(open(SCREENSHOT, "rb").read()).decode()
    resp = requests.post(LMSTUDIO, json={
        "model": MODEL,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            {"type": "text", "text": (
                "There should be a bright pink/red banner at the very top of the page "
                "that says 'ARGUS VISION TEST - CAN YOU SEE ME?'. "
                "Can you see it? What does it say exactly? What colour is it?"
            )},
        ]}],
        "max_tokens": 200,
        "temperature": 0.1,
    }, timeout=60)

    answer = resp.json()["choices"][0]["message"]["content"]
    print("\n--- Vision model says ---")
    print(answer)


asyncio.run(main())
