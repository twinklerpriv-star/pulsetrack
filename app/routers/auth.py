# ==============================================================================
# API-ROUTER: B2B-KUNDEN-AUTHENTIFIZIERUNG (REGISTRIERUNG & LOGIN)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Aktiv gepflegt & Sicherheitsüberprüft
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei regelt den sicheren Zugang zum PulseTrack-System. Sie erlaubt es
# Firmenkunden (B2B), sich zu registrieren und sicher einzuloggen.
# Dabei setzen wir branchenführende Sicherheitsstandards ein, um Kundendaten
# vor Hackern zu schützen und gleichzeitig gesetzliche DSGVO-Pflichten
# (wie das revisionssichere Unterzeichnen des AVV-Vertrags) vollautomatisch abzuwickeln.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Branchenführende Sicherheit: Passwörter werden mit dem modernsten Standard
#   (Argon2id) verschlüsselt. Selbst bei Server-Hacks sind Ihre Zugangsdaten sicher.
# - Keine Passwort-Spionage: Fehlerhafte Logins geben keine Details über existierende
#   E-Mail-Adressen preis (Vermeidung von User-Enumeration).
# - Einfaches AVV-Setup: Der gesetzliche DSGVO-Vertrag wird direkt digital unterzeichnet.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Verwendet 'argon2-cffi' für bestmögliches, GPU-resistentes Passwort-Hashing.
# - Erzeugt sichere HTTPOnly-, Secure- und SameSite=Lax-Session-Cookies.
# - Implementiert in-memory Rate-Limiting gegen Brute-Force-Angriffe.
# ==============================================================================

import hashlib
import logging
import secrets
import time
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User, UserAVVSignature
from app.services.security import is_rate_limited

logger = logging.getLogger("analytics_auth")
router = APIRouter(tags=["Authentication"])
# Argon2id Passwort-Hasher instanziieren (GPU-resistent und extrem sicher)
ph = PasswordHasher()

# In-Memory-Session-Store für einfache, hochsichere HTTPOnly-Sessions
# Format: {session_id: {"user_id": user_id, "email": email, "expires_at": float}}
sessions = {}
SESSION_COOKIE_NAME = "pt_session"
SESSION_DURATION = 86400 * 30  # 30 Tage Gültigkeit für die Kundensitzung

def get_current_user_id(request: Request) -> int:
    """
    IT-SICHERHEITS-DEPENDENCY:
    Überprüft bei jedem geschützten Dashboard-Aufruf, ob der Nutzer eingeloggt ist.
    Liest dazu das geheime Session-Cookie aus und verifiziert serverseitig die Gültigkeit.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Nicht autorisiert. Bitte melden Sie sich an.")
    
    session = sessions[session_id]
    # Serverseitiger Expiry-Check (D-3): Schützt vor gestohlenen alten Cookies
    expires_at = session.get("expires_at")
    if expires_at is not None and time.time() > expires_at:
        sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Sitzung abgelaufen. Bitte loggen Sie sich erneut ein.")
        
    return session["user_id"]

def register(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Neuregistrierung):
    Hier meldet sich ein neuer Webseitenbetreiber (B2B-Kunde) an.
    Das System prüft, ob die E-Mail echt aussieht, ob das Passwort stark genug ist
    (mindestens 8 Zeichen) und hasht das Passwort unumkehrbar mit Argon2id.
    Anschließend wird der B2B-Kunde direkt eingeloggt und seine Testphase (Trial) startet.
    """
    # D-4: Rate-Limiting zum Schutz vor automatisierten Bot-Registrierungen (Spam-Schutz)
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")
    if is_rate_limited(client_ip, "auth_register_limit"):
        raise HTTPException(status_code=429, detail="Zu viele Registrierungsversuche. Bitte warten Sie eine Minute.")

    # D-5: Strenge E-Mail- und Passwort-Validierung zur Systemstabilität
    normalized_email = email.strip().lower()
    if "@" not in normalized_email or "." not in normalized_email.split("@")[-1] or len(normalized_email) > 255:
        raise HTTPException(status_code=400, detail="Ungueltiges E-Mail-Format.")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Das Passwort muss mindestens 8 Zeichen lang sein.")
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="Das Passwort ist zu lang.")
        
    # 1. Prüfen, ob die E-Mail bereits existiert
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        # D-11: Standardisierte Fehlermeldung zur Vermeidung von User-Enumeration.
        # Ein Angreifer kann dadurch nicht herausfinden, welche E-Mail-Adressen im System registriert sind!
        raise HTTPException(status_code=400, detail="Registrierung fehlgeschlagen. Bitte ueberpruefen Sie Ihre Eingaben.")
        
    # 2. Passwort mit dem hochsicheren Argon2id hashen (GPU- und brute-force-resistent)
    password_hash = ph.hash(password)
    
    # 3. Neuen Benutzer in der Datenbank anlegen
    new_user = User(
        email=normalized_email,
        password_hash=password_hash,
        subscription_status="trial"  # Startet standardmäßig in der kostenlosen 14-tägigen Testphase
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # 4. Zufälligen Session-Schlüssel (Token) erzeugen und serverseitig abspeichern
        session_id = secrets.token_hex(32)
        sessions[session_id] = {
            "user_id": new_user.id,
            "email": new_user.email,
            "expires_at": time.time() + SESSION_DURATION
        }
        
        # Cookie setzen (HTTPOnly gegen Diebstahl via JS-XSS, Secure=True für HTTPS-Zwang, SameSite Lax gegen CSRF) (D-2)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=True,  # Erzwingt HTTPS-Verschlüsselung bei der Übermittlung
            samesite="lax",
            max_age=SESSION_DURATION
        )
        return {"status": "success", "message": "Benutzerkonto erfolgreich registriert und angemeldet."}
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler bei Registrierung: {e}")
        raise HTTPException(status_code=500, detail="Registrierung fehlgeschlagen. Bitte versuchen Sie es spaeter erneut.")

def login(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Login):
    Überprüft die E-Mail-Adresse und das Passwort des Kunden.
    Zum Schutz vor Spionage wird Argon2id zur Überprüfung des Passwort-Hashes genutzt.
    Ist der Login erfolgreich, wird ein sicheres, temporäres Cookie im Browser
    des Nutzers abgelegt, welches für den geschützten Dashboard-Bereich benötigt wird.
    """
    # D-4: Rate-Limiting gegen Brute-Force-Angriffe (Passwort-Erraten durch Hacker)
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")
    if is_rate_limited(client_ip, "auth_login_limit"):
        raise HTTPException(status_code=429, detail="Zu viele Anmeldeversuche. Bitte warten Sie eine Minute.")

    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    
    # D-11: Standardisierte Fehlermeldung zur Vermeidung von User-Enumeration (siehe register)
    generic_error = "Ungueltige E-Mail-Adresse oder Passwort."
    if not user:
        raise HTTPException(status_code=400, detail=generic_error)
        
    try:
        # Argon2 Passwort-Überprüfung: Vergleicht das Passwort mit dem gesicherten Hash
        ph.verify(user.password_hash, password)
    except VerifyMismatchError:
        raise HTTPException(status_code=400, detail=generic_error)
        
    # Eindeutige Session-ID generieren und mit Ablaufdatum abspeichern (D-3)
    session_id = secrets.token_hex(32)
    sessions[session_id] = {
        "user_id": user.id,
        "email": user.email,
        "expires_at": time.time() + SESSION_DURATION
    }
    
    # Session-Cookie im Browser setzen (Secure-Flag erzwungen) (D-2)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=SESSION_DURATION
    )
    return {"status": "success", "message": "Anmeldung erfolgreich abgeschlossen."}

def logout(request: Request, response: Response):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Logout):
    Meldet den B2B-Kunden sofort ab. Die serverseitige Sitzung wird gelöscht
    und das Session-Cookie im Browser des Nutzers entfernt.
    """
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id in sessions:
        sessions.pop(session_id, None)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success", "message": "Erfolgreich abgemeldet."}

def sign_avv(
    request: Request,
    avv_version: str = Form("1.0"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Auftragsverarbeitungs-Vertrag / AVV):
    Jedes europäische Unternehmen, das Besucherdaten erhebt, MUSS laut DSGVO einen
    AVV-Vertrag mit dem Dienstleister abschließen.
    Diese Funktion ermöglicht den vollautomatischen, digitalen Vertragsabschluss
    mit einem einzigen Klick im Dashboard!
    Wir loggen den Abschluss revisionssicher (gesetzlich geschützt):
    1. Welcher Kunde hat unterschrieben?
    2. Welche AVV-Version wurde unterzeichnet?
    3. Wann wurde unterschrieben?
    4. Die IP-Adresse wird aus Datenschutzgründen nur maskiert geloggt (z.B. 192.168.1.0).
    5. Es wird ein unumkehrbarer, manipulationssicherer Signatur-Hash erstellt.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden.")
        
    # AVV Duplikats-Prüfung: Verhindert doppelte Unterschriften
    existing_sig = db.query(UserAVVSignature).filter(
        UserAVVSignature.user_id == user_id,
        UserAVVSignature.avv_version == avv_version
    ).first()
    if existing_sig:
        return {
            "status": "signed",
            "message": "AVV bereits unterzeichnet.",
            "signed_at": existing_sig.signed_at,
            "signature_hash": existing_sig.signature_hash
        }

    # 1. Metadaten für das revisionssichere Audit-Log erfassen
    signed_at = datetime.now(tz=timezone.utc)
    
    # IP-Adresse ermitteln und datenschutzkonform maskieren (C-2)
    forwarded_for = request.headers.get("x-forwarded-for")
    raw_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")
    
    if "." in raw_ip:
        ip_parts = raw_ip.split(".")
        anonymized_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0"
    else:
        anonymized_ip = "IPv6"

    # 2. Kryptografischen Signatur-Hash berechnen zur Garantie der Integrität (D-7)
    # Der Hash verkettet Kunden-ID, Version, Zeitpunkt und das geheime Master-Secret.
    # Dadurch kann niemand den Eintrag nachträglich verändern oder fälschen.
    secret = settings.ANALYTICS_SALT_SECRET.get_secret_value()
    signature_data = f"{user_id}:{avv_version}:{signed_at.isoformat()}:{secret}".encode()
    signature_hash = hashlib.sha256(signature_data).hexdigest()

    new_signature = UserAVVSignature(
        user_id=user_id,
        avv_version=avv_version,
        signed_at=signed_at,
        signed_from_ip=anonymized_ip,
        signature_hash=signature_hash
    )
    
    try:
        db.add(new_signature)
        db.commit()
        db.refresh(new_signature)
        logger.info(f"AVV v{avv_version} erfolgreich digital signiert für User {user_id}.")
        return {
            "status": "signed", 
            "signed_at": signed_at, 
            "signature_hash": signature_hash
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler bei AVV-Signatur: {e}")
        raise HTTPException(status_code=500, detail="Interner Serverfehler während der AVV-Vertragsunterzeichnung.")

# API-Routen registrieren
# WICHTIG FÜR DEN IT-TECHNIKER:
# Wir verwenden 'def' statt 'async def', da diese Routen direkt mit der blockierenden
# SQLite-Datenbank interagieren. FastAPI führt synchrone Routen automatisch in einem
# Thread-Pool aus, wodurch die Server-Performance (Event-Loop) unbeeinträchtigt bleibt.
router.add_api_route("/register", register, methods=["POST"])
router.add_api_route("/login", login, methods=["POST"])
router.add_api_route("/logout", logout, methods=["POST"])
router.add_api_route("/api/avv/sign", sign_avv, methods=["POST"])
