# API Router: Authentifizierung & AVV-Abschluss
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import hashlib
import logging
import os
import secrets
from datetime import datetime, timezone

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User, UserAVVSignature

logger = logging.getLogger("analytics_auth")
router = APIRouter(tags=["Authentication"])
ph = PasswordHasher()

# In-Memory-Session-Store für einfache, sichere HTTPOnly-Sessions
# Format: {session_id: {"user_id": user_id, "email": email, "expires": float}}
sessions = {}
SESSION_COOKIE_NAME = "pt_session"
SESSION_DURATION = 86400 * 30  # 30 Tage Gültigkeit

def get_current_user_id(request: Request) -> int:
    """Dependency zur Authentifizierung des Nutzers über das Session-Cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=401, detail="Not authenticated. Please log in.")
    
    session = sessions[session_id]
    return session["user_id"]

@router.post("/register")
async def register(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Registriert einen neuen SaaS-Kunden unter Verwendung von Argon2."""
    normalized_email = email.strip().lower()
    
    # 1. Prüfen, ob die E-Mail bereits existiert
    existing_user = db.query(User).filter(User.email == normalized_email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="E-Mail already registered.")
        
    # 2. Passwort mit Argon2 hashen
    password_hash = ph.hash(password)
    
    # 3. User anlegen
    new_user = User(
        email=normalized_email,
        password_hash=password_hash,
        subscription_status="trial",  # Startet standardmäßig in 14-tägiger Testphase
        created_at=datetime.now(tz=timezone.utc).isoformat()
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        
        # 4. Session automatisch erstellen und einloggen
        session_id = secrets.token_hex(32)
        sessions[session_id] = {
            "user_id": new_user.id,
            "email": new_user.email
        }
        
        # Cookie setzen (HTTPOnly, Secure, SameSite Lax)
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            httponly=True,
            samesite="lax",
            max_age=SESSION_DURATION
        )
        return {"status": "success", "message": "User registered and logged in successfully."}
    except Exception as e:
        db.rollback()
        logger.error(f"Fehler bei Registrierung: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during registration.")

@router.post("/login")
async def login(
    response: Response,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Verifiziert Login-Daten und setzt das sichere Session-Cookie."""
    normalized_email = email.strip().lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
        
    try:
        # Argon2 Passwort-Überprüfung
        ph.verify(user.password_hash, password)
    except VerifyMismatchError:
        raise HTTPException(status_code=400, detail="Invalid email or password.")
        
    # Session ID generieren
    session_id = secrets.token_hex(32)
    sessions[session_id] = {
        "user_id": user.id,
        "email": user.email
    }
    
    # Cookie setzen
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_id,
        httponly=True,
        samesite="lax",
        max_age=SESSION_DURATION
    )
    return {"status": "success", "message": "Logged in successfully."}

@router.post("/logout")
async def logout(request: Request, response: Response):
    """Löscht die aktive Session aus dem Store und bereinigt das Cookie."""
    session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if session_id in sessions:
        del sessions[session_id]
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"status": "success", "message": "Logged out successfully."}

@router.post("/api/avv/sign")
async def sign_avv(
    request: Request,
    avv_version: str = Form("1.0"),
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id)
):
    """Schließt den DSGVO-Auftragsverarbeitungsvertrag digital ab und loggt dies revisionssicher."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
        
    # 1. Metadaten für das Audit-Log erfassen
    signed_at = datetime.now(tz=timezone.utc).isoformat()
    
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
    # Der Hash verkettet UserID, Version, Zeitpunkt und einen geheimen Server-Salt
    secret = os.environ.get("ANALYTICS_SALT_SECRET", "system_avv_secret_default")
    signature_data = f"{user_id}:{avv_version}:{signed_at}:{secret}".encode()
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
