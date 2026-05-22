from __future__ import annotations

import logging
import os

import resend

logger = logging.getLogger("mailer")


def send_alert_email(to: str, device_id: str, alert_time: str, alert_count: int) -> None:
    """
    Fire a device-down alert email via Resend.
    Failures are logged and never raised — cannot crash the watcher loop.
    """
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_email = os.environ.get("ALERT_FROM_EMAIL", "")

    if not api_key:
        logger.warning("RESEND_API_KEY not set — skipping email for device %s", device_id)
        return

    if not from_email:
        logger.warning("ALERT_FROM_EMAIL not set — skipping email for device %s", device_id)
        return

    resend.api_key = api_key   # set per-call so tests can patch env vars freely

    subject = f"🚨 Device Alert: {device_id} is DOWN"
    html = f"""
    <div style="font-family: sans-serif; max-width: 600px; margin: auto;">
      <div style="background: #dc2626; padding: 16px 24px; border-radius: 8px 8px 0 0;">
        <h2 style="color: white; margin: 0;">⚠️ Device Offline Alert</h2>
      </div>
      <div style="background: #f9fafb; padding: 24px; border: 1px solid #e5e7eb; border-radius: 0 0 8px 8px;">
        <p style="font-size: 16px; color: #111827;">
          Device <strong>{device_id}</strong> has stopped sending heartbeats
          and is now considered <strong>offline</strong>.
        </p>
        <table style="width: 100%; border-collapse: collapse; margin-top: 16px;">
          <tr>
            <td style="padding: 8px 12px; background: #fff; border: 1px solid #e5e7eb; font-weight: bold; width: 40%;">Device ID</td>
            <td style="padding: 8px 12px; background: #fff; border: 1px solid #e5e7eb;">{device_id}</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; background: #f3f4f6; border: 1px solid #e5e7eb; font-weight: bold;">Time (CAT)</td>
            <td style="padding: 8px 12px; background: #f3f4f6; border: 1px solid #e5e7eb;">{alert_time}</td>
          </tr>
          <tr>
            <td style="padding: 8px 12px; background: #fff; border: 1px solid #e5e7eb; font-weight: bold;">Alert #</td>
            <td style="padding: 8px 12px; background: #fff; border: 1px solid #e5e7eb;">#{alert_count}</td>
          </tr>
        </table>
        <p style="margin-top: 24px; color: #6b7280; font-size: 13px;">
          Sent by CritMon Watchdog Sentinel — Pulse-Check API
        </p>
      </div>
    </div>
    """

    try:
        params: resend.Emails.SendParams = {
            "from": from_email,       # ← was FROM_EMAIL (NameError), now the local variable
            "to": [to],
            "subject": subject,
            "html": html,
        }
        email = resend.Emails.send(params)
        logger.info("Alert email sent → id=%s to=%s device=%s", email["id"], to, device_id)
    except Exception as exc:
        logger.error("Failed to send alert email to %s: %s", to, exc)
