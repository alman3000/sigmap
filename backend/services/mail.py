"""
SMTP service — supports three modes controlled by SMTP_MODE in .env:

  host     — sends to the VPS host's own postfix/exim4 via Docker host-gateway (no auth)
  relay    — sends to a boky/postfix relay container on the internal network (no auth)
  external — sends to any SMTP server with optional STARTTLS or SSL and credentials
"""

import smtplib
import ssl
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from config import get_settings

logger = logging.getLogger(__name__)


def send_magic_link_email(to_email: str, magic_link: str) -> None:
    settings = get_settings()

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "graffmap – Login Link"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email

    text = (
        f"graffmap Admin Login\n\n"
        f"Klicke auf den Link um dich anzumelden "
        f"(gültig {settings.MAGIC_LINK_EXPIRE_MINUTES} Minuten):\n\n"
        f"{magic_link}\n\n"
        f"Falls du diesen Link nicht angefordert hast, ignoriere diese Mail."
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;background:#1a1a1a;color:#e0e0e0;padding:40px;margin:0">
  <div style="max-width:480px;margin:0 auto">
    <h2 style="color:#f59e0b;margin-top:0">graffmap Admin</h2>
    <p>Klicke auf den Link um dich anzumelden
       (gültig {settings.MAGIC_LINK_EXPIRE_MINUTES} Minuten):</p>
    <p style="margin:24px 0">
      <a href="{magic_link}"
         style="background:#f59e0b;color:#1a1a1a;padding:12px 24px;
                text-decoration:none;border-radius:6px;font-weight:bold">
        Jetzt anmelden
      </a>
    </p>
    <p style="word-break:break-all;color:#888;font-size:12px">{magic_link}</p>
    <hr style="border:none;border-top:1px solid #3a3a3a;margin:24px 0">
    <p style="color:#666;font-size:12px">
      Falls du diesen Link nicht angefordert hast, ignoriere diese Mail.
    </p>
  </div>
</body>
</html>"""

    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    _dispatch(msg, settings)


def send_new_photo_notification(filename: str) -> None:
    """Notify all admin emails that a new photo is waiting for review."""
    settings = get_settings()
    if not settings.admin_email_list:
        return

    admin_url = f"{settings.APP_URL}/admin.html"

    for email in settings.admin_email_list:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "graffmap – Neues Foto zur Freigabe"
        msg["From"] = settings.SMTP_FROM
        msg["To"] = email

        text = (
            f"Ein neues Foto wurde hochgeladen und wartet auf Freigabe.\n\n"
            f"Datei: {filename}\n\n"
            f"Admin-Übersicht: {admin_url}\n"
        )
        html = f"""<!DOCTYPE html>
<html>
<body style="font-family:sans-serif;background:#1a1a1a;color:#e0e0e0;padding:40px;margin:0">
  <div style="max-width:480px;margin:0 auto">
    <h2 style="color:#f59e0b;margin-top:0">graffmap – Neues Foto</h2>
    <p>Ein neues Foto wartet auf Freigabe:</p>
    <p style="color:#aaa;font-size:14px;font-family:monospace">{filename}</p>
    <p style="margin:24px 0">
      <a href="{admin_url}"
         style="background:#f59e0b;color:#1a1a1a;padding:12px 24px;
                text-decoration:none;border-radius:6px;font-weight:bold">
        Zur Admin-Übersicht
      </a>
    </p>
  </div>
</body>
</html>"""

        msg.attach(MIMEText(text, "plain", "utf-8"))
        msg.attach(MIMEText(html, "html", "utf-8"))
        try:
            _dispatch(msg, settings)
        except Exception as exc:
            logger.warning("Admin notification to %s failed: %s", email, exc)


# ── internal helpers ────────────────────────────────────────────────────────

def _dispatch(msg: MIMEMultipart, settings) -> None:
    mode = settings.SMTP_MODE.lower()
    if mode == "host":
        logger.info("SMTP mode=host → %s:%d", settings.SMTP_HOST_GATEWAY, settings.SMTP_HOST_PORT)
        _send_relay(msg, settings.SMTP_HOST_GATEWAY, settings.SMTP_HOST_PORT)
    elif mode == "relay":
        logger.info("SMTP mode=relay → %s:%d", settings.SMTP_RELAY_HOST, settings.SMTP_RELAY_PORT)
        _send_relay(msg, settings.SMTP_RELAY_HOST, settings.SMTP_RELAY_PORT)
    elif mode == "external":
        logger.info(
            "SMTP mode=external → %s:%d (ssl=%s tls=%s)",
            settings.SMTP_EXTERNAL_HOST,
            settings.SMTP_EXTERNAL_PORT,
            settings.SMTP_EXTERNAL_SSL,
            settings.SMTP_EXTERNAL_TLS,
        )
        _send_external(msg, settings)
    else:
        raise ValueError(f"Unknown SMTP_MODE '{settings.SMTP_MODE}' — use host, relay, or external")


def _send_relay(msg: MIMEMultipart, host: str, port: int) -> None:
    """Plain SMTP, no auth, no TLS — for local relays."""
    with smtplib.SMTP(host, port, timeout=10) as smtp:
        smtp.sendmail(msg["From"], msg["To"], msg.as_string())


def _send_external(msg: MIMEMultipart, settings) -> None:
    """SMTP with optional STARTTLS (port 587) or implicit SSL (port 465) and credentials."""
    user = settings.SMTP_EXTERNAL_USER or None
    password = settings.SMTP_EXTERNAL_PASSWORD or None

    if settings.SMTP_EXTERNAL_SSL:
        # Implicit TLS — typically port 465
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(
            settings.SMTP_EXTERNAL_HOST,
            settings.SMTP_EXTERNAL_PORT,
            context=ctx,
            timeout=10,
        ) as smtp:
            if user:
                smtp.login(user, password)
            smtp.sendmail(msg["From"], msg["To"], msg.as_string())

    elif settings.SMTP_EXTERNAL_TLS:
        # STARTTLS — typically port 587
        ctx = ssl.create_default_context()
        with smtplib.SMTP(
            settings.SMTP_EXTERNAL_HOST,
            settings.SMTP_EXTERNAL_PORT,
            timeout=10,
        ) as smtp:
            smtp.starttls(context=ctx)
            if user:
                smtp.login(user, password)
            smtp.sendmail(msg["From"], msg["To"], msg.as_string())

    else:
        # Plain external SMTP without TLS (uncommon, avoid in prod)
        with smtplib.SMTP(
            settings.SMTP_EXTERNAL_HOST,
            settings.SMTP_EXTERNAL_PORT,
            timeout=10,
        ) as smtp:
            if user:
                smtp.login(user, password)
            smtp.sendmail(msg["From"], msg["To"], msg.as_string())
