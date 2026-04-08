"""Ticketmaster login and session management."""

from __future__ import annotations

import logging

from ticketman.browser import BrowserManager

log = logging.getLogger(__name__)

TM_LOGIN_URL = "https://identity.ticketmaster.com/login"
TM_HOME_URL = "https://www.ticketmaster.com"


async def login_interactive(browser: BrowserManager) -> bool:
    """Open Ticketmaster login page for manual login.

    The user logs in manually (handles 2FA, CAPTCHA, etc.).
    Session is persisted automatically via the persistent browser profile.

    Returns True if login appears successful.
    """
    page = browser.page
    log.info("Navigating to Ticketmaster login...")

    await page.goto(TM_LOGIN_URL, wait_until="networkidle")

    # Wait for the user to complete login — detected by URL change away from login page
    log.info("Please log in to Ticketmaster in the browser window.")
    log.info("Waiting for login to complete (timeout: 5 minutes)...")

    try:
        # Wait until we're redirected away from the login page
        await page.wait_for_url(
            lambda url: "identity.ticketmaster.com" not in url,
            timeout=300_000,  # 5 minutes
        )
    except Exception:
        log.error("Login timed out after 5 minutes.")
        return False

    # Verify we're logged in by checking for account indicators
    current_url = page.url
    log.info("Redirected to: %s", current_url)

    # Check if we can access account page
    await page.goto(f"{TM_HOME_URL}/member", wait_until="networkidle")
    is_logged_in = "sign-in" not in page.url.lower()

    if is_logged_in:
        log.info("Login successful! Session saved to browser profile.")
    else:
        log.warning("Login may have failed — could not verify account access.")

    return is_logged_in


async def check_session(browser: BrowserManager) -> bool:
    """Check if an existing session is still valid."""
    page = browser.page

    try:
        await page.goto(f"{TM_HOME_URL}/member", wait_until="networkidle", timeout=15000)
        is_valid = "sign-in" not in page.url.lower()
        log.info("Session check: %s", "valid" if is_valid else "expired")
        return is_valid
    except Exception:
        log.warning("Session check failed (network error)")
        return False
