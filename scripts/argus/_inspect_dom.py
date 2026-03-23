"""Quick inspector to dump live NLM DOM elements."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9223")
        ctx = browser.contexts[0]
        for page in ctx.pages:
            if "notebooklm" in page.url and "/notebook/" in page.url:
                print(f"Page: {page.url}")
                script = (
                    "[...document.querySelectorAll(\"button,[role='button'],mat-list-item\")]"
                    ".map(e=>(e.innerText||e.textContent||e.getAttribute('aria-label')||'').trim().slice(0,80))"
                    ".filter(t=>t.length>0).slice(0,60)"
                )
                btns = await page.evaluate(script)
                print("BUTTONS:", btns)

                inp_script = (
                    "[...document.querySelectorAll('input,textarea,[contenteditable]')]"
                    ".map(e=>({tag:e.tagName,label:e.getAttribute('aria-label'),ph:e.placeholder,ce:e.getAttribute('contenteditable')}))"
                    ".slice(0,15)"
                )
                inputs = await page.evaluate(inp_script)
                print("INPUTS:", inputs)

                # Try to get XSRF / AT token from page JS globals
                at_script = (
                    "(() => {"
                    "  try { return window.__AT__ || null; } catch(e) { return null; }"
                    "})()"
                )
                at_val = await page.evaluate(at_script)
                print("AT global:", at_val)

                # Try WIZ_global_data which often has XSRF
                wiz_script = (
                    "(() => {"
                    "  try { const w = window.WIZ_global_data; return w ? {at:w.SNlM0e, sid:w.cfb2h} : null; } catch(e) { return null; }"
                    "})()"
                )
                wiz = await page.evaluate(wiz_script)
                print("WIZ_global_data:", wiz)
                break


asyncio.run(main())
