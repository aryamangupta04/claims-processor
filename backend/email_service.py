"""Email notification service using Resend."""
from __future__ import annotations

import os

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "aryamangupta2004@gmail.com")
FROM_EMAIL = "onboarding@resend.dev"


def is_configured() -> bool:
    return bool(RESEND_API_KEY)


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email via Resend. Returns True if sent successfully."""
    if not is_configured():
        return False

    try:
        import resend
        resend.api_key = RESEND_API_KEY
        resend.Emails.send({
            "from": FROM_EMAIL,
            "to": [to_email],
            "subject": subject,
            "html": body,
        })
        return True
    except Exception:
        return False


def notify_admin_manual_review(claim_id: str, member_name: str, amount: float, reason: str):
    """Notify admin that a claim needs manual review."""
    if not ADMIN_EMAIL:
        return

    subject = f"Manual Review Required — Claim {claim_id}"
    body = f"""
    <div style="font-family: sans-serif; max-width: 500px;">
        <h2 style="color: #6B21A8;">Manual Review Required</h2>
        <p>A claim has been routed for manual review:</p>
        <table style="border-collapse: collapse; width: 100%;">
            <tr><td style="padding: 8px; color: #666;">Claim ID</td><td style="padding: 8px; font-weight: bold;">{claim_id}</td></tr>
            <tr><td style="padding: 8px; color: #666;">Member</td><td style="padding: 8px;">{member_name}</td></tr>
            <tr><td style="padding: 8px; color: #666;">Amount</td><td style="padding: 8px;">₹{amount:,.0f}</td></tr>
            <tr><td style="padding: 8px; color: #666;">Reason</td><td style="padding: 8px;">{reason}</td></tr>
        </table>
        <p style="margin-top: 20px;">
            <a href="https://claims-processor-nine.vercel.app/admin" style="background: #6B21A8; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none;">
                Review in Admin Dashboard
            </a>
        </p>
    </div>
    """
    send_email(ADMIN_EMAIL, subject, body)


def notify_member_status_update(to_email: str, claim_id: str, member_name: str, status: str, summary: str):
    """Notify member that their claim status has changed."""
    status_colors = {
        "APPROVED": "#16a34a",
        "REJECTED": "#dc2626",
        "PARTIAL": "#ca8a04",
    }
    color = status_colors.get(status, "#6B21A8")

    subject = f"Claim {claim_id} — {status}"
    body = f"""
    <div style="font-family: sans-serif; max-width: 500px;">
        <h2 style="color: #6B21A8;">Claim Status Update</h2>
        <p>Hi {member_name},</p>
        <p>Your claim <strong>{claim_id}</strong> has been updated:</p>
        <p style="font-size: 18px; color: {color}; font-weight: bold;">{status}</p>
        <p>{summary}</p>
        <p style="margin-top: 20px;">
            <a href="https://claims-processor-nine.vercel.app/" style="background: #6B21A8; color: white; padding: 10px 20px; border-radius: 6px; text-decoration: none;">
                View in Portal
            </a>
        </p>
    </div>
    """
    send_email(to_email, subject, body)
