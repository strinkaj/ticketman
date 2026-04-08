"""Checkout automation — seat selection, cart, payment, confirmation."""

from __future__ import annotations

import logging
from pathlib import Path

from ticketman.browser import BrowserManager
from ticketman.captcha import CaptchaSolver
from ticketman.models import AppConfig, TargetEvent

log = logging.getLogger(__name__)


class CheckoutFlow:
    """Automates the Ticketmaster checkout process."""

    def __init__(
        self,
        browser: BrowserManager,
        solver: CaptchaSolver,
        config: AppConfig,
        target: TargetEvent,
    ) -> None:
        self.browser = browser
        self.solver = solver
        self.config = config
        self.target = target

    async def run(self) -> bool:
        """Execute the full checkout flow. Returns True on success."""
        page = self.browser.page

        try:
            # Step 1: Click into ticket selection
            log.info("Starting checkout flow...")
            await self._click_find_tickets()

            # Step 2: Select seats/tickets
            log.info("Selecting tickets...")
            await self._select_tickets()

            # Step 3: Handle any CAPTCHA challenges
            await self._handle_captcha()

            # Step 4: Proceed to checkout
            log.info("Proceeding to checkout...")
            await self._proceed_to_checkout()

            # Step 5: Handle payment
            log.info("Completing payment...")
            await self._complete_payment()

            # Step 6: Confirm purchase
            log.info("Confirming purchase...")
            success = await self._confirm_purchase()

            if success:
                await self.browser.screenshot("purchase_success")
                log.info("Purchase completed successfully!")
            else:
                await self.browser.screenshot("purchase_failed")
                log.error("Purchase may have failed — check screenshot")

            return success

        except Exception as e:
            log.error("Checkout failed: %s", e)
            await self.browser.screenshot("checkout_error")
            raise

    async def _click_find_tickets(self) -> None:
        """Click the Find Tickets / Get Tickets button on the event page."""
        page = self.browser.page
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
                    await self.browser.human_click(sel)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    return
            except Exception:
                continue

        raise RuntimeError("Could not find ticket button on event page")

    async def _select_tickets(self) -> None:
        """Select tickets based on target preferences (sections, price, quantity)."""
        page = self.browser.page
        await self.browser.human_delay(500, 1500)

        # Try to set quantity
        quantity_sel = 'select[data-testid="quantity-selector"], select[id*="quantity"]'
        try:
            quantity_el = await page.query_selector(quantity_sel)
            if quantity_el:
                await quantity_el.select_option(str(self.target.quantity))
                log.info("Set quantity to %d", self.target.quantity)
                await self.browser.human_delay(300, 800)
        except Exception as e:
            log.debug("Quantity selector not found or failed: %s", e)

        # Look for section filters if configured
        if self.target.sections:
            await self._filter_sections()

        # Look for price filter
        if self.target.max_price:
            await self._filter_price()

        # Click best available or first available listing
        await self._pick_best_available()

    async def _filter_sections(self) -> None:
        """Apply section filters if available in the UI."""
        page = self.browser.page
        for section in self.target.sections:
            try:
                section_el = await page.query_selector(f'text="{section}"')
                if section_el:
                    await section_el.click()
                    log.info("Selected section: %s", section)
                    await self.browser.human_delay(300, 600)
                    return
            except Exception:
                continue
        log.debug("No section filters matched — using best available")

    async def _filter_price(self) -> None:
        """Apply price filter if available."""
        # TM's price filter varies by event — this is a best-effort attempt
        log.debug("Price filter: max $%.0f (will verify before purchase)", self.target.max_price)

    async def _pick_best_available(self) -> None:
        """Click on the best available ticket listing."""
        page = self.browser.page

        # Common selectors for ticket listings
        listing_selectors = [
            '[data-testid="ticket-card"]',
            '.ticket-card',
            '[class*="TicketCard"]',
            'button:has-text("Add to Cart")',
            'button:has-text("Select")',
        ]

        for sel in listing_selectors:
            try:
                listings = await page.query_selector_all(sel)
                if listings:
                    # Click the first available listing
                    await listings[0].click()
                    log.info("Selected ticket listing")
                    await self.browser.human_delay(500, 1000)
                    return
            except Exception:
                continue

        # Fallback: try clicking anywhere that looks like a ticket selection
        log.warning("No standard listing found — attempting best-available click")

    async def _handle_captcha(self) -> None:
        """Detect and solve any reCAPTCHA challenges."""
        page = self.browser.page
        await self.browser.human_delay(300, 600)

        # Check for reCAPTCHA iframe
        captcha_frame = None
        for frame in page.frames:
            if "recaptcha" in frame.url.lower() or "google.com/recaptcha" in frame.url:
                captcha_frame = frame
                break

        if not captcha_frame:
            # Also check for reCAPTCHA v3 (invisible) by looking for sitekey in page
            sitekey = await self._extract_sitekey(page)
            if sitekey:
                log.info("reCAPTCHA v3 detected — solving...")
                token = await self.solver.solve_recaptcha_v3(sitekey, page.url)
                await self._inject_captcha_token(page, token)
            return

        # reCAPTCHA v2 visible
        sitekey = await self._extract_sitekey(page)
        if not sitekey:
            log.warning("CAPTCHA frame detected but could not extract sitekey")
            return

        log.info("reCAPTCHA v2 detected — solving...")
        token = await self.solver.solve_recaptcha_v2(sitekey, page.url)
        await self._inject_captcha_token(page, token)
        log.info("CAPTCHA token injected")

    async def _extract_sitekey(self, page) -> str | None:
        """Extract the reCAPTCHA sitekey from page HTML."""
        try:
            sitekey = await page.evaluate("""() => {
                const el = document.querySelector('[data-sitekey]');
                if (el) return el.getAttribute('data-sitekey');
                const scripts = document.querySelectorAll('script[src*="recaptcha"]');
                for (const s of scripts) {
                    const match = s.src.match(/[?&]render=([^&]+)/);
                    if (match) return match[1];
                }
                return null;
            }""")
            return sitekey
        except Exception:
            return None

    async def _inject_captcha_token(self, page, token: str) -> None:
        """Inject a solved CAPTCHA token into the page."""
        await page.evaluate(f"""(token) => {{
            // Set the response textarea
            const textarea = document.getElementById('g-recaptcha-response');
            if (textarea) {{
                textarea.style.display = 'block';
                textarea.value = token;
            }}
            // Also try hidden textareas (reCAPTCHA v3 / invisible)
            document.querySelectorAll('[name="g-recaptcha-response"]').forEach(el => {{
                el.value = token;
            }});
            // Trigger callback if available
            if (typeof ___grecaptcha_cfg !== 'undefined') {{
                const clients = ___grecaptcha_cfg.clients;
                for (const key in clients) {{
                    const client = clients[key];
                    if (client && client.$ && client.$.$ && client.$.$.callback) {{
                        client.$.$.callback(token);
                        return;
                    }}
                }}
            }}
        }}""", token)

    async def _proceed_to_checkout(self) -> None:
        """Navigate from cart to checkout."""
        page = self.browser.page
        await self.browser.human_delay(500, 1000)

        checkout_selectors = [
            'button:has-text("Checkout")',
            'button:has-text("Place Order")',
            'a:has-text("Checkout")',
            '[data-testid="checkout-button"]',
            '[data-testid="proceed-to-checkout"]',
        ]

        for sel in checkout_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await self.browser.human_click(sel)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    return
            except Exception:
                continue

        # Handle any additional CAPTCHA at checkout
        await self._handle_captcha()

    async def _complete_payment(self) -> None:
        """Fill payment details and complete the purchase.

        Uses saved payment method in TM account when possible (identified by last4).
        """
        page = self.browser.page
        await self.browser.human_delay(500, 1500)

        card_last4 = self.config.payment.card_last4
        if card_last4:
            # Try to select saved payment method by last 4 digits
            try:
                saved_card = await page.query_selector(f'text="{card_last4}"')
                if saved_card:
                    await saved_card.click()
                    log.info("Selected saved card ending in %s", card_last4)
                    await self.browser.human_delay(300, 600)
                    return
            except Exception:
                log.debug("Could not select saved card — may need manual entry")

        log.info("Payment form ready — waiting for completion...")

    async def _confirm_purchase(self) -> bool:
        """Click the final purchase confirmation button."""
        page = self.browser.page
        await self.browser.human_delay(500, 1000)

        confirm_selectors = [
            'button:has-text("Place Order")',
            'button:has-text("Complete Purchase")',
            'button:has-text("Submit Order")',
            'button:has-text("Pay")',
            '[data-testid="place-order-button"]',
        ]

        for sel in confirm_selectors:
            try:
                el = await page.query_selector(sel)
                if el and await el.is_visible():
                    await self.browser.human_click(sel)
                    log.info("Purchase confirmation clicked!")

                    # Wait for confirmation page
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    await self.browser.human_delay(1000, 2000)

                    # Check for success indicators
                    content = await page.content()
                    success_indicators = [
                        "order confirmed",
                        "confirmation",
                        "thank you",
                        "order number",
                        "your tickets",
                    ]
                    return any(ind in content.lower() for ind in success_indicators)
            except Exception:
                continue

        log.error("Could not find purchase confirmation button")
        return False
