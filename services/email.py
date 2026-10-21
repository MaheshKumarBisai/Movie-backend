import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from core.config import settings

logger = logging.getLogger(__name__)

async def send_otp_email(email: str, otp: int) -> bool:
    """
    Send OTP via SMTP.
    Returns True if email was sent successfully.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning(f"SMTP credentials not configured. OTP for {email}: {otp}")
        return False

    msg = MIMEMultipart()
    msg['From'] = settings.SMTP_FROM
    msg['To'] = email
    msg['Subject'] = f"{otp} is your ShowGo OTP"

    body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 32px 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F8FAFC; color: #0F172A;">
    <div style="max-width: 480px; margin: 0 auto; background-color: #FFFFFF; padding: 32px 28px; border-radius: 10px; border: 1px solid #E2E8F0; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);">
        <h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A;">ShowGo Verification</h2>
        <p style="font-size: 15px; line-height: 1.6; color: #334155; margin: 0 0 16px 0;">
            Use the following one-time code to sign in to your account:
        </p>
        <p style="font-size: 16px; line-height: 1.6; color: #0F172A; margin: 0 0 20px 0;">
            Your OTP is: <strong style="font-size: 22px; font-weight: 700; color: #0F172A; background-color: #F1F5F9; padding: 4px 10px; border-radius: 6px; letter-spacing: 3px; border: 1px solid #CBD5E1;">{otp}</strong>
        </p>
        <p style="font-size: 13px; line-height: 1.5; color: #64748B; margin: 0 0 20px 0;">
            This code will expire in 5 minutes. Please do not share it with anyone.
        </p>
        <div style="border-top: 1px solid #E2E8F0; padding-top: 16px;">
            <p style="font-size: 12px; color: #94A3B8; margin: 0;">
                If you did not request this code, you can safely ignore this email.
            </p>
        </div>
    </div>
</body>
</html>"""
    msg.attach(MIMEText(body, 'html'))

    try:
        # SMTP_SSL for port 465, starttls for 587
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
            
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.send_message(msg)
        server.quit()
        logger.info(f"OTP Email sent to {email}")
    except Exception as e:
        logger.error(f"SMTP failed to send email: {e}")
        return False

from email.mime.application import MIMEApplication
import os

async def send_ticket_email(email: str, pdf_path: str, movie_title: str) -> bool:
    """
    Send Booking Ticket PDF via SMTP.
    """
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning(f"SMTP not configured. Could not send ticket for {movie_title} to {email}")
        return False

    msg = MIMEMultipart()
    msg['From'] = settings.SMTP_FROM
    msg['To'] = email
    msg['Subject'] = f"Your Ticket for {movie_title} - ShowGo"

    body = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin: 0; padding: 32px 16px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F8FAFC; color: #0F172A;">
    <div style="max-width: 480px; margin: 0 auto; background-color: #FFFFFF; padding: 32px 28px; border-radius: 10px; border: 1px solid #E2E8F0; box-shadow: 0 2px 4px rgba(0, 0, 0, 0.04);">
        <h2 style="margin: 0 0 16px 0; font-size: 20px; font-weight: 700; color: #0F172A;">Ticket Confirmed!</h2>
        <p style="font-size: 15px; line-height: 1.6; color: #334155; margin: 0 0 16px 0;">
            Enjoy your movie! Your ticket for <strong>{movie_title}</strong> is attached to this email.
        </p>
        <p style="font-size: 13px; line-height: 1.5; color: #64748B; margin: 0 0 20px 0;">
            Please present the attached PDF at the cinema hall entrance.
        </p>
        <div style="border-top: 1px solid #E2E8F0; padding-top: 16px;">
            <p style="font-size: 12px; color: #94A3B8; margin: 0;">
                ShowGo Booking Service
            </p>
        </div>
    </div>
</body>
</html>"""
    msg.attach(MIMEText(body, 'html'))

    # Attach PDF
    try:
        with open(pdf_path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(pdf_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(pdf_path)}"'
            msg.attach(part)
    except Exception as e:
        logger.error(f"Failed to attach PDF: {e}")
        return False

    try:
        if settings.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)
        else:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
            
        server.login(settings.SMTP_USER, settings.SMTP_PASS)
        server.send_message(msg)
        server.quit()
        logger.info(f"Ticket Email sent to {email}")
        return True
    except Exception as e:
        logger.error(f"SMTP failed to send ticket email: {e}")
        return False
