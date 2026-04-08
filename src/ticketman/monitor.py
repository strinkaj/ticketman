"""Event monitoring — polls Ticketmaster for ticket availability."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

from ticketman.browser import BrowserManager
from ticketman.models import TargetEvent

log = logging.getLogger(__name__)


class EventMonitor:
    """Watches a Ticketmaster event page for ticket availability."""

    def __init__(self, browser: BrowserManager, target: TargetEvent) -> None:
        self.browser = browser
        self.target = target
        self._event_id = self._extract_event_id(target.url)

    @staticmethod
    def _extract_event_id(url: str) -> str:
        """Extract event ID from Ticketmaster URL."""
        # Handles: /event/artist-name/EVENT_ID or /event/EVENT_ID
        match = re.search(r"/event/(?:[\w-]+/)?([A-Za-z0-9]+)(?:\?|$)", url)
        if match:
            return match.group(1)
        raise ValueError(f"Cannot extract event ID from URL: {url}")

    async def wait_for_onsale(self) -> None:
        """Sleep until 30 seconds before the on-sale time."""
        if not self.target.on_sale:
            log.info("No on-sale time configured — starting immediately")
            return

        now = datetime.now(timezone.utc)
        on_sale_utc = self.target.on_sale.astimezone(timezone.utc)

        # Wake up 30 seconds before on-sale
        wake_time = on_sale_utc.timestamp() - 30
        sleep_seconds = wake_time - now.timestamp()

        if sleep_seconds > 0:
            log.info(
                "On-sale at %s — sleeping %.0f seconds (waking 30s early)",
                self.target.on_sale.isoformat(),
                sleep_seconds,
            )
            await asyncio.sleep(sleep_seconds)
        else:
            log.info("On-sale time already passed — starting immediately")

    async def poll_for_tickets(self, poll_interval: float = 1.5) -> bool:
        """Poll the event page until tickets become available.

        Returns True when tickets are found.
        """
        page = self.browser.page
        log.info("Monitoring: %s", self.target.url)

        while True:
            try:
                await page.goto(self.target.url, wait_until="domcontentloaded", timeout=15000)
                await self.browser.human_delay(200, 500)

                # Check for various ticket-available indicators
                available = await self._check_availability(page)
                if available:
                    log.info("Tickets available!")
                    return True

                # Check if we're in a Queue-it waiting room
                if await self._is_in_queue(page):
                    log.info("In Queue-it waiting room — waiting for our turn...")
                    await self._wait_through_queue(page)
                    return True

                log.debug("No tickets yet — polling again in %.1fs", poll_interval)
                await asyncio.sleep(poll_interval)

            except Exception as e:
                log.warning("Poll error: %s — retrying in %.1fs", e, poll_interval * 2)
                await asyncio.sleep(poll_interval * 2)

    async def _check_availability(self, page) -> bool:
        """Check if the event page shows available tickets."""
        # Look for the main ticket button
        selectors = [
            'button:has-text("Find Tickets")',
            'button:has-text("Get Tickets")',
            'button:has-text("See Tickets")',
            'a:has-text("Find Tickets")',
            '[data-testid="find-tickets-button"]',
            '[data-testid="get-tickets-cta"]',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    return True
            except Exception:
                continue

        return False

    async def _is_in_queue(self, page) -> bool:
        """Detect Queue-it waiting room."""
        url = page.url
        content = await page.content()
        return "queue-it" in url.lower() or "queue-it" in content.lower()

    async def _wait_through_queue(self, page, timeout: int = 600) -> None:
        """Wait in Queue-it until redirected to the event page."""
        log.info("Waiting in queue (timeout: %ds)...", timeout)
        try:
            await page.wait_for_url(
                lambda url: "ticketmaster.com/event" in url.lower(),
                timeout=timeout * 1000,
            )
            log.info("Queue complete — redirected to event page")
        except Exception:
            log.error("Queue wait timed out after %ds", timeout)
            raise
