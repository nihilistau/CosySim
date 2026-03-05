"""Inspect AIStudio + Gemini live DOM for crawler targeting."""
import asyncio
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp("http://localhost:9222")
        ctx = browser.contexts[0]

        for page in ctx.pages:
            domain = page.url.split("/")[2] if "://" in page.url else ""

            if "aistudio.google.com" in domain:
                print(f"\n=== AISTUDIO: {page.url} ===")
                # Get nav links
                links = await page.evaluate(
                    "[...document.querySelectorAll('a[href],nav a,mat-nav-item,[routerlink]')]"
                    ".map(e=>({text:(e.innerText||e.textContent||'').trim().slice(0,60),"
                    "href:e.href||e.getAttribute('routerLink')||''}))"
                    ".filter(e=>e.text||e.href).slice(0,30)"
                )
                print("NAV LINKS:", links)
                btns = await page.evaluate(
                    "[...document.querySelectorAll('button,[role=button]')]"
                    ".map(e=>(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,60))"
                    ".filter(t=>t).slice(0,20)"
                )
                print("BUTTONS:", btns)

            elif "gemini.google.com" in domain:
                print(f"\n=== GEMINI: {page.url} ===")
                btns = await page.evaluate(
                    "[...document.querySelectorAll('button,[role=button],textarea,input')]"
                    ".map(e=>({tag:e.tagName,text:(e.innerText||e.getAttribute('aria-label')||'').trim().slice(0,60),ph:e.placeholder||''}))"
                    ".filter(e=>e.text||e.ph).slice(0,20)"
                )
                print("ELEMENTS:", btns)


asyncio.run(main())
