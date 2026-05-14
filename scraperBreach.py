"""
Scraper con Playwright + stealth per bypassare sistemi anti-bot.
Dipendenze: pip install playwright playwright-stealth fake-useragent
             playwright install chromium
"""

import asyncio
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from fake_useragent import UserAgent
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth


@dataclass
class ScraperConfig:
    headless: bool = True
    min_delay: float = 1.5
    max_delay: float = 4.0
    timeout: int = 30_000  # ms
    proxy: Optional[str] = None  # "http://user:pass@host:port"
    cookies_file: Optional[str] = None
    extra_headers: dict = field(default_factory=dict)


VIEWPORT_SIZES = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1366, "height": 768},
    {"width": 1280, "height": 800},
]

LOCALES = ["it-IT", "en-US", "en-GB", "fr-FR"]
TIMEZONES = ["Europe/Rome", "America/New_York", "Europe/London", "Europe/Paris"]


class StealthScraper:
    def __init__(self, config: ScraperConfig = ScraperConfig()):
        self.config = config
        self._ua = UserAgent(browsers=["chrome"], os=["windows", "macos"])
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._stealth = Stealth(navigator_languages_override=("it-IT", "it"))

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        launch_kwargs = {
            "headless": self.config.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-web-security",
                "--lang=it-IT,en-US",
            ],
        }
        if self.config.proxy:
            launch_kwargs["proxy"] = {"server": self.config.proxy}

        self._browser = await self._pw.chromium.launch(**launch_kwargs)
        self._context = await self._new_context()
        return self

    async def __aexit__(self, *_):
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        await self._pw.stop()

    async def _new_context(self) -> BrowserContext:
        ua = self._ua.random
        viewport = random.choice(VIEWPORT_SIZES)
        locale = random.choice(LOCALES)
        tz = random.choice(TIMEZONES)

        ctx = await self._browser.new_context(
            user_agent=ua,
            viewport=viewport,
            locale=locale,
            timezone_id=tz,
            permissions=["geolocation"],
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": f"{locale},{locale.split('-')[0]};q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "DNT": "1",
                **self.config.extra_headers,
            },
        )
        ctx.set_default_timeout(self.config.timeout)
        return ctx

    # ------------------------------------------------------------------
    # Core scraping
    # ------------------------------------------------------------------

    async def get_html(self, url: str, wait_for: str = "domcontentloaded") -> str:
        """
        Scarica l'HTML di una pagina con evasione fingerprinting.
        wait_for: 'domcontentloaded' | 'networkidle' | 'load'
        """
        page = await self._context.new_page()
        try:
            await self._stealth.apply_stealth_async(page)
            await self._human_delay()

            response = await page.goto(url, wait_until=wait_for)
            if response is None:
                raise RuntimeError(f"Nessuna risposta da {url}")

            # Aspetta che eventuali redirect JS (es. Cloudflare) si stabilizzino
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            if await self._is_cloudflare_challenge(page):
                await self._wait_cloudflare(page)

            return await page.content()
        finally:
            await page.close()

    async def get_multiple(
        self, urls: list[str], concurrency: int = 2
    ) -> dict[str, str]:
        """Scarica più URL in parallelo con concurrency limitata."""
        semaphore = asyncio.Semaphore(concurrency)

        async def fetch(url: str) -> tuple[str, str]:
            async with semaphore:
                html = await self.get_html(url)
                return url, html

        results = await asyncio.gather(
            *[fetch(u) for u in urls], return_exceptions=True
        )
        return {url: html for url, html in results if not isinstance(html, Exception)}

    async def _is_cloudflare_challenge(self, page: Page) -> bool:
        try:
            title = await page.title()
            return any(k in title.lower() for k in ("just a moment", "attention required", "ddos-guard"))
        except Exception:
            return False

    async def _wait_cloudflare(self, page: Page, timeout: int = 20) -> None:
        """Attende che Cloudflare completi il challenge JS automatico."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not await self._is_cloudflare_challenge(page):
                return
            await asyncio.sleep(1)
        raise TimeoutError("Cloudflare challenge non superato entro il timeout")

    async def _human_delay(self) -> None:
        delay = random.uniform(self.config.min_delay, self.config.max_delay)
        await asyncio.sleep(delay)


# ------------------------------------------------------------------
# Esempio d'uso
# ------------------------------------------------------------------


async def main():
    config = ScraperConfig(
        headless=True,
        min_delay=2.0,
        max_delay=5.0,
        # proxy="http://user:pass@proxy_host:8080",  # opzionale
    )

    async with StealthScraper(config) as scraper:
        # Singolo URL
        html = await scraper.get_html("https://www.idealista.it/immobile/35473590/")
        print(f"HTML ricevuto: {len(html)} caratteri")
        with open("output.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Salvato in output.html")

        # Multipli URL
        # urls = ["https://example.com", "https://httpbin.org/headers"]
        # results = await scraper.get_multiple(urls, concurrency=2)
        # for url, html in results.items():
        #     print(f"{url}: {len(html)} chars")


if __name__ == "__main__":
    asyncio.run(main())
