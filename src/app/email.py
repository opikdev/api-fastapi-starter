"""Outgoing email. The log sender stands in until you plug in a provider."""

import logging
from typing import Protocol

logger = logging.getLogger("app.email")


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, text: str) -> None: ...


class LogEmailSender:
    """Logs each email instead of sending it. Replace it with your provider's client."""

    async def send(self, *, to: str, subject: str, text: str) -> None:
        logger.info("Email not sent, because no provider is set up", extra={"subject": subject})
