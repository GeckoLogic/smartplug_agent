"""
notifier.py - Notification dispatching for Smart Plug Monitoring Agent
"""

from __future__ import annotations

import asyncio
import logging
import smtplib
from email.mime.text import MIMEText
from typing import Optional

from config import NotificationConfig

logger = logging.getLogger(__name__)


def _send_email_sync(cfg, subject: str, body: str) -> None:
    """Synchronous helper – run in executor so it doesn't block the event loop."""
    email_cfg = cfg.email
    if email_cfg is None or not email_cfg.enabled:
        return

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = email_cfg.smtp_user
    message["To"] = ", ".join(email_cfg.to)

    with smtplib.SMTP(email_cfg.smtp_host, email_cfg.smtp_port, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(email_cfg.smtp_user, email_cfg.smtp_password)
        server.sendmail(
            email_cfg.smtp_user,
            email_cfg.to,
            message.as_string(),
        )

    logger.info("Email notification sent: %s", subject)


async def _send_telegram(cfg: NotificationConfig, subject: str, body: str) -> None:
    """Send a Telegram message via the Bot API."""
    telegram_cfg = cfg.telegram
    if telegram_cfg is None or not telegram_cfg.enabled:
        return

    try:
        import httpx

        url = f"https://api.telegram.org/bot{telegram_cfg.bot_token}/sendMessage"
        payload = {
            "chat_id": telegram_cfg.chat_id,
            "text": f"{subject}\n\n{body}",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
        logger.info("Telegram notification sent: %s", subject)
    except Exception as exc:
        logger.error("Failed to send Telegram notification: %s", exc)


async def notify(cfg: NotificationConfig, subject: str, body: str) -> None:
    """
    Dispatch notifications to all enabled channels concurrently.

    Errors in individual channels are logged and swallowed so that a failure
    in one channel does not prevent delivery via others.
    """
    tasks = []

    # Email (sync, run in executor)
    if cfg.email is not None and cfg.email.enabled:
        loop = asyncio.get_event_loop()

        async def _email_task():
            try:
                await loop.run_in_executor(
                    None, _send_email_sync, cfg, subject, body
                )
            except Exception as exc:
                logger.error("Failed to send email notification: %s", exc)

        tasks.append(_email_task())

    # Telegram (async)
    if cfg.telegram is not None and cfg.telegram.enabled:
        async def _telegram_task():
            try:
                await _send_telegram(cfg, subject, body)
            except Exception as exc:
                logger.error("Failed to send Telegram notification: %s", exc)

        tasks.append(_telegram_task())

    if tasks:
        await asyncio.gather(*tasks)
    else:
        logger.debug("No notification channels enabled; skipping notify('%s')", subject)
