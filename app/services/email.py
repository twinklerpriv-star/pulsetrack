# ==============================================================================
# PULSETRACK ANALYTICS - TRANSAKTIONS-E-MAIL-SERVICE (SMTP-SICHERHEIT)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Sicherheitsoptimiert
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei ermöglicht den automatischen Versand wichtiger E-Mails an Ihre Kunden,
# z. B. Willkommensgrüße, Rechnungsbestätigungen, Kündigungsbestätigungen
# oder System-Warnungen.
#
# INTERNE IT-SICHERHEITSMASSNAHMEN (SCHUTZ VOR SPAM-RELAY-KAPERN):
# KUNDENVERSTÄNDLICHE ERKLÄRUNG:
# Kriminelle versuchen oft, E-Mail-Formulare zu kapern, um unbemerkt Tausende
# Spam-Mails an Dritte zu senden (Header-Injection).
# Dieser Service prüft vor dem Absenden streng, ob sich unzulässige Zeilenumbrüche
# in der Empfängeradresse oder im Betreff befinden. Falls ja, wird der Versand
# sofort blockiert.
# Zudem nutzen wir moderne, verschlüsselte TLS-Verbindungen, damit niemand Ihre
# E-Mail-Zugangsdaten im Netzwerk abfangen kann (Man-in-the-Middle-Schutz).
# ==============================================================================

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
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Sicherer, verschlüsselter E-Mail-Versand):
    Baut eine sichere, verschlüsselte Verbindung zu Ihrem E-Mail-Postfach auf
    und sendet die E-Mail ab.
    Ist in der Installation kein E-Mail-Konto hinterlegt (z. B. auf Ihrem Test-Server),
    schaltet die Funktion automatisch in einen "Mock-Modus". Sie simuliert den
    Versand im Logbuch, damit der IT-Techniker das System ohne echten Mail-Server
    testen kann.
    """
    # D-6: Schutz vor Email-Header-Injection (Sicherheitsprüfung gegen Missbrauch)
    if re.search(r"[\r\n]", subject) or re.search(r"[\r\n]", recipient_email):
        raise ValueError("Header-Injection-Versuch erkannt: Zeilenumbrueche in E-Mail-Metadaten sind unzulaessig.")

    smtp_host = settings.SMTP_HOST
    smtp_port = settings.SMTP_PORT
    smtp_user = settings.SMTP_USER
    smtp_pass = settings.SMTP_PASSWORD.get_secret_value() if settings.SMTP_PASSWORD else None
    
    # Falls keine SMTP-Konfiguration vorliegt (z. B. im Testbetrieb), im Logbuch simulieren (Mock)
    if not all([smtp_host, smtp_port, smtp_user, smtp_pass]):
        logger.debug(
            f"[SMTP MOCK] E-Mail erfolgreich 'versendet' (Keine Credentials konfiguriert).\n"
            f"An: {recipient_email}\nBetreff: {subject}\nInhalt: {html_content[:200]}..."
        )
        return True
        
    try:
        # E-Mail-Struktur aufbauen (MIME HTML-Format)
        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = recipient_email
        msg["Subject"] = subject
        
        # HTML-Inhalt anhängen (ermöglicht schöne Formatierungen und Logos in E-Mails)
        msg.attach(MIMEText(html_content, "html"))
        
        # SSL-Sicherheits-Kontext erstellen (D-12, D-13): Erzwingt moderne Verschlüsselungsprotokolle
        context = ssl.create_default_context()
        
        # Baut die Verbindung zum Mailserver auf
        with smtplib.SMTP(smtp_host, int(smtp_port)) as server:
            # Verbindung verschlüsseln (STARTTLS)
            server.starttls(context=context)
            # Am E-Mail-Server einloggen
            server.login(smtp_user, smtp_pass)
            # E-Mail absenden
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
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Hintergrund-Versand für perfekte Performance):
    Der Versand einer E-Mail über das Internet kann 1 bis 3 Sekunden dauern.
    Würden wir dies direkt beim Drücken eines Buttons tun, müsste Ihr Kunde warten.
    Diese Funktion schiebt den E-Mail-Versand in den "Hintergrund" (BackgroundTasks)
    der Server-Engine. Der Kunde erhält seine Webseite sofort, während der Server
    die E-Mail unbemerkt im Hintergrund verschickt.
    """
    background_tasks.add_task(
        send_smtp_email_sync, 
        recipient_email, 
        subject, 
        html_content
    )
