# Transactional E-Mail Service: SMTP TLS Connection
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import logging
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from fastapi import BackgroundTasks

logger = logging.getLogger("analytics_email")

def send_smtp_email_sync(recipient_email: str, subject: str, html_content: str) -> bool:
    """Sendet eine SMTP-E-Mail synchron über eine sichere TLS-Verbindung."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = os.environ.get("SMTP_PORT")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASSWORD")
    
    # Falls keine SMTP-Konfiguration vorliegt (z. B. im Testbetrieb), sicher loggen
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        logger.info(
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
        
        # TLS-Verbindung aufbauen
        server = smtplib.SMTP(smtp_host, int(smtp_port))
        server.starttls()
        server.login(smtp_user, smtp_pass)
        
        # Senden
        server.sendmail(smtp_user, recipient_email, msg.as_string())
        server.quit()
        
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
