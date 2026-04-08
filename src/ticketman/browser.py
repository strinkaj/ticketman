"""Browser manager — Playwright with stealth and persistent profiles."""

from __future__ import annotations

import asyncio
import logging
import random
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, async_playwright
from playwright_stealth import stealth_async

from ticketman.models import BrowserConfig

log = logging.getLogger(__name__)


class BrowserManager:
    """Manages a stealth Playwright browser with persistent profile."""

    def __init__(self, config: BrowserConfig) -> None:
        self.config = config
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("Browser not started. Call start() first.")
        return self._page

    async def start(self) -> Page:
        """Launch browser with stealth and persistent profile."""
        profile_dir = Path(self.config.profile_dir).resolve()
        profile_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = await async_playwright().start()

        # Use persistent context for cookie/session reuse across runs
        self._context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            headless=self.config.headless,
            slow_mo=self.config.slowmo,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
            timezone_id="America/New_York",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )

        # Use existing page or create one
        if self._context.pages:
            self._page = self._context.pages[0]
        else:
            self._page = await self._context.new_page()

        # Apply stealth patches
        await stealth_async(self._page)

        log.info("Browser started (headless=%s, profile=%s)", self.config.headless, profile_dir)
        return self._page

    async def stop(self) -> None:
        """Close browser and cleanup."""
        if self._context:
            await self._context.close()
        if self._playwright:
            await self._playwright.stop()
        self._page = None
        self._context = None
        self._playwright = None
        log.info("Browser stopped")

    async def human_delay(self, min_ms: int = 50, max_ms: int = 300) -> None:
        """Random delay to mimic human timing."""
        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)

    async def human_click(self, selector: str) -> None:
        """Click an element with human-like behavior."""
        element = await self.page.wait_for_selector(selector, timeout=10000)
        if element:
            # Move to element with slight offset
            box = await element.bounding_box()
            if box:
                x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
                y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
                await self.page.mouse.move(x, y, steps=random.randint(5, 15))
                await self.human_delay(30, 100)
            await element.click()
        await self.human_delay()

    async def human_type(self, selector: str, text: str) -> None:
        """Type text with human-like delays between keystrokes."""
        await self.human_click(selector)
        for char in text:
            await self.page.keyboard.type(char, delay=random.randint(30, 120))
        await self.human_delay()

    async def screenshot(self, name: str) -> Path:
        """Take a screenshot and save to screenshots/ directory."""
        screenshots_dir = Path("screenshots")
        screenshots_dir.mkdir(exist_ok=True)
        path = screenshots_dir / f"{name}.png"
        await self.page.screenshot(path=str(path), full_page=True)
        log.info("Screenshot saved: %s", path)
        return path
