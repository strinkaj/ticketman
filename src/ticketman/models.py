"""Data models for ticketman."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TargetEvent(BaseModel):
    """A ticket purchase target."""

    url: str
    name: str = ""
    on_sale: datetime | None = None
    sections: list[str] = Field(default_factory=list)
    max_price: float | None = None
    quantity: int = 2


class CaptchaConfig(BaseModel):
    """CAPTCHA solving service configuration."""

    provider: str = "2captcha"
    api_key: str = ""
    timeout: int = 120


class PaymentConfig(BaseModel):
    """Payment method selection."""

    card_last4: str = ""


class NotificationConfig(BaseModel):
    """Notification settings."""

    desktop: bool = True
    sms: bool = False
    twilio_sid: str = ""
    twilio_token: str = ""
    twilio_from: str = ""
    phone_to: str = ""


class BrowserConfig(BaseModel):
    """Browser automation settings."""

    headless: bool = False
    slowmo: int = 50
    profile_dir: str = "./browser_data"


class TicketmasterConfig(BaseModel):
    """Ticketmaster account settings."""

    email: str = ""
    password: str = ""


class AppConfig(BaseModel):
    """Top-level application configuration."""

    ticketmaster: TicketmasterConfig = Field(default_factory=TicketmasterConfig)
    captcha: CaptchaConfig = Field(default_factory=CaptchaConfig)
    payment: PaymentConfig = Field(default_factory=PaymentConfig)
    targets: list[TargetEvent] = Field(default_factory=list)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
