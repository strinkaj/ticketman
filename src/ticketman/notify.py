"""Notifications — desktop toasts and optional SMS."""

from __future__ import annotations

import logging

from ticketman.models import NotificationConfig

log = logging.getLogger(__name__)


class Notifier:
    """Sends desktop and SMS notifications."""

    def __init__(self, config: NotificationConfig) -> None:
        self.config = config

    def notify(self, title: str, message: str) -> None:
        """Send notification via all configured channels."""
        if self.config.desktop:
            self._desktop_notify(title, message)
        if self.config.sms:
            self._sms_notify(title, message)

    def _desktop_notify(self, title: str, message: str) -> None:
        """Send a desktop toast notification."""
        try:
            from plyer import notification

            notification.notify(
                title=title,
                message=message,
                app_name="Ticketman",
                timeout=10,
            )
            log.info("Desktop notification sent: %s", title)
        except Exception as e:
            log.warning("Desktop notification failed: %s", e)

    def _sms_notify(self, title: str, message: str) -> None:
        """Send an SMS via Twilio."""
        if not all([
            self.config.twilio_sid,
            self.config.twilio_token,
            self.config.twilio_from,
            self.config.phone_to,
        ]):
            log.warning("SMS configured but Twilio credentials incomplete — skipping")
            return

        try:
            from twilio.rest import Client

            client = Client(self.config.twilio_sid, self.config.twilio_token)
            client.messages.create(
                body=f"{title}: {message}",
                from_=self.config.twilio_from,
                to=self.config.phone_to,
            )
            log.info("SMS sent to %s", self.config.phone_to)
        except Exception as e:
            log.warning("SMS notification failed: %s", e)
