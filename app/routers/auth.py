# API Router: Authentifizierung & AVV-Abschluss
#
# Datum: 31.05.2026 | Version: 1.1 | Status: Aktiv gepflegt

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
ph = PasswordHasher()

# In-Memory-Session-Store fuer einfache, sichere HTTPOnly-Sessions
# Format: {session_id: {"user_id": user_id, "email": email, "expires_at": float}}
sessions = {}
SESSION_COOKIE_NAME = "pt_session"
SESSION_DURATION = 86400 * 30  # 30 Tage Gueltigkeit

def get_current_user_id(request: Request) -> int:
    """Dependency zur Authentifizierung des Nutzers ueber das Session-Cookie mit Expiry-Check (D-3)."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    
    session = sessions[session_id]
    # Serverseitiger Expiry-Check (D-3)
    expires_at = session.get("expires_at")
    if expires_at is not None and time.time() > expires_at:
        sessions.pop(session_id, None)
        raise HTTPException(status_code=401, detail="Session expired. Please log in again.")
        
    return session["user_id"]

def register(
    request: Request,
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Registriert einen neuen B2B-SaaS-Kunden mit Validierung und Argon2 (A-1, D-4, D-5, D-11).
    Faehrt synchron im Thread-Pool, um Event-Loop Blockagen zu vermeiden.
    """
    # D-4: Rate-Limiting auf Register
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")
    if is_rate_limited(client_ip, "auth_register_limit"):
        raise HTTPException(status_code=429, detail="Zu viele Registrierungsversuche. Bitte warten Sie eine Minute.")

    # D-5: E-Mail und Passwort Validierung
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
        # D-11: Standardisierte Fehlermeldung zur Vermeidung von User-Enumeration
        raise HTTPException(status_code=400, detail="Registrierung fehlgeschlagen. Bitte ueberpruefen Sie Ihre Eingaben.")
        
    # 2. Passwort mit Argon2 hashen
    password_hash = ph.hash(password)
    
    # 3. User anlegen (E-6 nutzt UTCDateTime default)
    new_user = User(
        email=normalized_email,
        password_hash=password_hash,
        subscription_status="trial"  # Startet standardmaeßig in 14-taegiger Testphase
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # 4. Session automatisch erstellen und einloggen
        session_id = secrets.token_hex(32)
        sessions[session_id] = {
            "user_id": new_user.id,
            "email": new_user.email,
            "expires_at": time.time() + SESSION_DURATION
        }
        
        # Cookie setzen (HTTPOnly, Secure=True, SameSite Lax) (D-2)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            secure=True,  # secure=True erzwungen (D-2)
            samesite="lax",
            max_age=SESSION_DURATION
        )
        return {"status": "success", "message": "User registered and logged in successfully."}
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
    Verifiziert Login-Daten und setzt das sichere Session-Cookie mit Expiry (A-1, D-2, D-3, D-4, D-11).
    Faehrt synchron im Thread-Pool.
    """
    # D-4: Rate-Limiting auf Login
    forwarded_for = request.headers.get("x-forwarded-for")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")
    if is_rate_limited(client_ip, "auth_login_limit"):
        raise HTTPException(status_code=429, detail="Zu viele Anmeldeversuche. Bitte warten Sie eine Minute.")

    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    
    # D-11: Standardisierte Fehlermeldung zur Vermeidung von User-Enumeration
    generic_error = "Ungueltige E-Mail-Adresse oder Passwort."
    if not user:
        raise HTTPException(status_code=400, detail=generic_error)
        
    try:
        # Argon2 Passwort-Überprüfung
        ph.verify(user.password_hash, password)
    except VerifyMismatchError:
        raise HTTPException(status_code=400, detail=generic_error)
        
    # Session ID generieren mit Ablaufzeit (D-3)
    session_id = secrets.token_hex(32)
    sessions[session_id] = {
        "user_id": user.id,
        "email": user.email,
        "expires_at": time.time() + SESSION_DURATION
    }
    
    # Cookie setzen (secure=True) (D-2)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        secure=True,  # secure=True erzwungen (D-2)
        samesite="lax",
        max_age=SESSION_DURATION
    )
    return {"status": "success", "message": "Logged in successfully."}

def logout(request: Request, response: Response):
    """Loescht die aktive Session aus dem Store und bereinigt das Cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id in sessions:
        sessions.pop(session_id, None)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success", "message": "Logged out successfully."}

def sign_avv(
    request: Request,
    avv_version: str = Form("1.0"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """
    Schließt den DSGVO-Auftragsverarbeitungsvertrag digital ab und loggt dies revisionssicher (A-1, D-7, C-2).
    Faehrt synchron im Thread-Pool.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    # AVV Duplikats-Pruefung
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

    # 1. Metadaten für das Audit-Log erfassen
    signed_at = datetime.now(tz=timezone.utc)
    
    # IP-Adresse des Unterzeichners ermitteln (anonymisiert für DSGVO-Rechtskonformität)
    forwarded_for = request.headers.get("x-forwarded-for")
    raw_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "127.0.0.1")
    
    # Simple IP Anonymisierung für den AVV Log-Eintrag (Maskierung des letzten Oktetts)
    if "." in raw_ip:
        ip_parts = raw_ip.split(".")
        anonymized_ip = f"{ip_parts[0]}.{ip_parts[1]}.{ip_parts[2]}.0"
    else:
        anonymized_ip = "IPv6"

    # 2. Kryptografischen Signatur-Hash berechnen zur Garantie der Integrität des Log-Eintrags
    # Der Hash verkettet UserID, Version, Zeitpunkt und den sicheren, globalen Salt (D-7)
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
        raise HTTPException(status_code=500, detail="Internal server error during AVV logging.")

# FastAPI APIRouter registrieren (A-1, def statt async def fuer DB-interaktive Routen)
router.add_api_route("/register", register, methods=["POST"])
router.add_api_route("/login", login, methods=["POST"])
router.add_api_route("/logout", logout, methods=["POST"])
router.add_api_route("/api/avv/sign", sign_avv, methods=["POST"])
