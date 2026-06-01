# Transactional E-Mail Service: SMTP TLS Connection
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

import logging
import re
import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import BackgroundTasks

from app.config import settings

logger = logging.getLogger("analytics_email")

def send_smtp_email_sync(recipient_email: str, subject: str, html_content: str) -> bool:
    """Sendet eine SMTP-E-Mail synchron über eine sichere TLS-Verbindung."""
    # D-6: Schutz vor Email-Header-Injection
    if re.search(r"[\r\n]", subject) or re.search(r"[\r\n]", recipient_email):
        raise ValueError("Header-Injection-Versuch erkannt: Zeilenumbrueche in E-Mail-Metadaten sind unzulaessig.")

    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    smtp_user = settings.SMTP_USER
    smtp_pass = settings.SMTP_PASSWORD.get_secret_value() if settings.SMTP_PASSWORD else None
    
    # Falls keine SMTP-Konfiguration vorliegt (z. B. im Testbetrieb), im Debug-Modus loggen
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        logger.debug(
            f"[SMTP MOCK] E-Mail erfolgreich 'versendet' (Keine Credentials konfiguriert).\n"
            f"An: {recipient_email}\nBetreff: {subject}\nInhalt: {html_content[:200]}..."
        )
        return True
        
    try:
        # E-Mail-Struktur aufbauen
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = recipient_email
        msg["Subject"] = subject
        
        # HTML-Inhalt anhängen
        msg.attach(MIMEText(html_content, "html"))
        
        # TLS-Verbindung mit sicherer Context-Verifikation aufbauen (D-12, D-13)
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            server.starttls(context=context)
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipient_email, msg.as_string())
        
        logger.info(f"E-Mail erfolgreich an {recipient_email} versendet.")
        return True
    except Exception as e:
        logger.error(f"Kritischer Fehler beim SMTP-E-Mail-Versand an {recipient_email}: {e}")
        return False

async def queue_transactional_email(
    background_tasks: BackgroundTasks, 
    recipient_email: str, 
    subject: str, 
    html_content: str
) -> None:
    """Reiht den E-Mail-Versand asynchron in die FastAPI BackgroundTasks ein."""
    background_tasks.add_task(
        send_smtp_email_sync, 
        recipient_email, 
        subject, 
        html_content
    )
