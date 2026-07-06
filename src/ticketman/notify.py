"""Notifications. Desktop toast only.

Every alert also prints to the console, so you still see it if the toast
backend is unavailable (headless session, missing platform support).
"""

from __future__ import annotations

import logging

from ticketman.models import NotificationConfig

log = logging.getLogger(__name__)


class Notifier:
    """Sends desktop toast notifications."""

    def __init__(self, config: NotificationConfig) -> None:
        self.config = config

    def notify(self, title: str, message: str) -> None:
        """Alert on all configured channels. Console always, toast if enabled."""
        log.info("ALERT: %s - %s", title, message)
        if self.config.desktop:
            self._desktop_notify(title, message)

    def _desktop_notify(self, title: str, message: str) -> None:
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="Ticketman",
                timeout=15,
            )
        except Exception as e:
            log.warning("Desktop toast failed (%s). Console alert still shown.", e)
