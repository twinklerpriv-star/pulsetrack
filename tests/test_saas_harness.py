# SaaS QA Test-Suite: Multi-Tenancy, Ingestion, GDPR Account Deletion & Savepoint Isolation
#
# Datum: 31.05.2026 | Version: 2.0 | Status: Aktiv gepflegt

import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Sicherstellen, dass die Env-Secrets fuer die Settings-Validierung gesetzt sind
os.environ["ANALYTICS_SALT_SECRET"] = "test_system_salt_secret_1234567890"
os.environ["STRIPE_SECRET_KEY"] = "sk_test_mock_stripe_key"
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_mock_webhook_secret"

from app.database import Base, get_db
from app.main import app
from app.models.hit import Hit
from app.models.user import DailyKey, User, UserAVVSignature
from app.models.website import Website
from app.routers.auth import SESSION_COOKIE_NAME, ph, sessions
from app.services.queue_worker import hit_queue, save_batch_to_db, write_queue_to_db
from app.services.security import (
    get_or_create_daily_hmac_key,
    hash_ip_address,
    rotate_daily_hmac_key,
)

# 1. Separates Test-Datenbank-Setup (SQLite in-memory)
TEST_DATABASE_URL = "sqlite:///:memory:"
engine_test = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine_test)

@pytest.fixture(scope="module", autouse=True)
def init_test_db():
    """Initialisiert die DB-Tabellen vor dem Testdurchlauf und loescht sie danach."""
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)


class NonClosingSessionProxy:
    """Proxy-Wrapper, der verhindert, dass die Test-Session vorzeitig geschlossen wird."""
    def __init__(self, session):
        self._session = session
    def __getattr__(self, name):
        if name == "close":
            return lambda: None  # Schließen ignorieren
        return getattr(self._session, name)


@pytest.fixture
def db_session():
    """
    F-1: Bietet eine transaktionsisolierte DB-Session fuer jeden Testfall unter Verwendung
    des SAVEPOINT patterns (begin_nested()). Loest das Commit-Isolation-Problem vollstaendig.
    """
    connection = engine_test.connect()
    transaction = connection.begin()
    
    # Session erzeugen und an Verbindung binden
    session = TestingSessionLocal(bind=connection)
    
    # Erste verschachtelte Transaktion (SAVEPOINT) fuer die App starten
    nested = connection.begin_nested()
    
    # Event-Listener registrieren, um nach jedem app-internen commit() automatisch einen neuen SAVEPOINT zu starten
    @event.listens_for(session, "after_transaction_end")
    def end_savepoint(session_obj, transaction_obj):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    # Session ueberschreiben im FastAPI-Dependency-System
    def override_get_db():
        try:
            yield session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    
    # Patch SessionLocal in queue_worker und database (für retention), damit sie dieselbe isolierte Test-Session nutzen
    with patch("app.services.queue_worker.SessionLocal", return_value=NonClosingSessionProxy(session)), \
         patch("app.database.SessionLocal", return_value=NonClosingSessionProxy(session)):
        yield session
    
    session.close()
    transaction.rollback()
    connection.close()
    app.dependency_overrides.clear()
    sessions.clear()  # Session-Store aufraeumen


@pytest.fixture
def client(db_session):
    """
    F-2: Bietet einen TestClient als Fixture, um Lifespan-Triggereffekte auf die
    Produktions-Datenbank beim Modulimport zu verhindern.
    """
    with TestClient(app) as tc:
        yield tc


# 2. Testfaelle

def test_user_registration_and_login(db_session, client):
    """Prüft die Neuregistrierung, Passwortsicherung mit Argon2 und den Login-Prozess (D-5, D-11)."""
    # 1. Registrieren
    reg_data = {"email": "pepi@elektro-pepi.at", "password": "SuperSecurePassword123!"}
    response_reg = client.post("/register", data=reg_data)
    assert response_reg.status_code == 200
    assert "registered" in response_reg.json()["message"]

    # 2. Prüfen, ob der User in der DB existiert und passwortgehasht ist
    user = db_session.query(User).filter(User.email == "pepi@elektro-pepi.at").first()
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")  # Verifiziert Argon2id-Praefix

    # 3. Einloggen
    response_login = client.post("/login", data=reg_data)
    assert response_login.status_code == 200
    assert SESSION_COOKIE_NAME in response_login.cookies

    # 4. Falsches Passwort prüfen (D-11 standardisierte Fehlermeldung)
    response_fail = client.post("/login", data={"email": "pepi@elektro-pepi.at", "password": "WrongPassword"})
    assert response_fail.status_code == 400
    assert "Ungueltige E-Mail-Adresse oder Passwort" in response_fail.json()["detail"]


def test_duplicate_email_registration(db_session, client):
    """Verifiziert das Verhindern von E-Mail-Duplikaten mit standardisierter Fehlermeldung (D-11)."""
    user = User(email="pepi-duplicate@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user)
    db_session.commit()

    reg_data = {"email": "pepi-duplicate@pepi.at", "password": "SuperSecurePassword123!"}
    response = client.post("/register", data=reg_data)
    
    assert response.status_code == 400
    assert "Registrierung fehlgeschlagen. Bitte ueberpruefen Sie Ihre Eingaben." in response.json()["detail"]


def test_multi_tenant_data_isolation(db_session, client):
    """Verifiziert die absolute Multi-Tenant-Datenisolierung (User A darf nicht auf User B zugreifen)."""
    # 1. Zwei Test-User anlegen
    userA = User(email="user_a@test.com", password_hash=ph.hash("passA"), subscription_status="trial")
    userB = User(email="user_b@test.com", password_hash=ph.hash("passB"), subscription_status="trial")
    db_session.add(userA)
    db_session.add(userB)
    db_session.commit()

    # 2. Webseiten anlegen (Website A gehört User A, Website B gehört User B)
    webA = Website(user_id=userA.id, domain="https://sitea.com", tracking_token="pt_live_tokenA")
    webB = Website(user_id=userB.id, domain="https://siteb.com", tracking_token="pt_live_tokenB")
    db_session.add(webA)
    db_session.add(webB)
    db_session.commit()

    # 3. Login als User A (Session erzeugen)
    session_id = secrets.token_hex(32)
    sessions[session_id] = {"user_id": userA.id, "email": userA.email}

    # 4. Zugriff auf eigene Daten (Website A) -> Muss erlaubt sein (200)
    response_own = client.get(f"/api/dashboard/stats?website_id={webA.id}", headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"})
    assert response_own.status_code == 200
    assert response_own.json()["domain"] == "https://sitea.com"

    # 5. Zugriff auf fremde Daten (Website B) -> Muss verweigert werden (403)
    response_foreign = client.get(f"/api/dashboard/stats?website_id={webB.id}", headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"})
    assert response_foreign.status_code == 403
    assert "Access denied" in response_foreign.json()["detail"]


@pytest.mark.asyncio
async def test_graceful_shutdown_queue_flushing(db_session, client):
    """Testet die SIGTERM-Datenrettungs-Logik: Puffer-Hits werden beim Herunterfahren in die DB geschrieben (F-6)."""
    # 1. Test-User und Website anlegen
    user = User(email="pepi@pepi.at", password_hash="hash", subscription_status="active")
    db_session.add(user)
    db_session.commit()
    
    website = Website(user_id=user.id, domain="https://pepi.at", tracking_token="pt_live_graceful")
    db_session.add(website)
    db_session.commit()

    # 2. Queue manuell mit ungeschriebenen Hits füllen
    while not hit_queue.empty():
        hit_queue.get_nowait()
        hit_queue.task_done()

    for i in range(3):
        await hit_queue.put({
            "token": "pt_live_graceful",
            "timestamp": datetime.utcnow(),
            "url": f"https://pepi.at/page{i}.html",
            "referrer": None,
            "user_agent": "Mozilla/5.0",
            "ip_hash": f"hash_{i}",
            "browser": "Chrome",
            "os": "Windows"
        })

    # 3. Graceful Shutdown Signal triggern
    await write_queue_to_db()

    # 4. Verifizieren: Queue muss leer sein
    assert hit_queue.empty() is True

    # 5. Verifizieren: Hits müssen in der DB sein
    hits = db_session.query(Hit).filter(Hit.website_id == website.id).all()
    assert len(hits) == 3
    assert hits[0].url == "https://pepi.at/page0.html"


def test_hmac_key_rotation_forward_secrecy(db_session, client):
    """Valide die Krypto-Rotationslogik: Löschen alter Keys verhindert rückwirkende IP-Hashes Rekonstruktion (C-2, C-3)."""
    # 1. Hole heutigen Key
    key_today = get_or_create_daily_hmac_key(db_session)
    assert len(key_today) == 64  # Hex von 32-Byte Key

    # 2. IP hashen
    ip = "203.0.113.195"
    hash_a = hash_ip_address(ip, key_today)

    # 3. Simuliere einen alten Schlüssel (von gestern)
    yesterday = datetime.now(tz=timezone.utc) - timedelta(days=2)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    
    # Sichern, dass verschlüsselt gespeichert wird
    from app.services.security import _encrypt_key
    encrypted_old_val = _encrypt_key(secrets.token_hex(32), yesterday_str)
    old_key = DailyKey(day=yesterday_str, key_value=encrypted_old_val)
    db_session.add(old_key)
    db_session.commit()

    # 4. Rotation triggern -> Muss alte Keys löschen, aber den von heute behalten
    rotate_daily_hmac_key(db_session)

    # 5. Verifizieren: Key von heute existiert noch, der alte ist gelöscht
    key_today_check = db_session.query(DailyKey).filter(DailyKey.day == datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")).first()
    assert key_today_check is not None

    key_old_check = db_session.query(DailyKey).filter(DailyKey.day == yesterday_str).first()
    assert key_old_check is None


def test_caddy_cname_verification(db_session, client):
    """Testet den Dynamic-SSL Endpoint zur Freigabe von Zertifikaten für Custom Domains."""
    # 1. User & Website anlegen
    user = User(email="caddy@test.com", password_hash="hash", subscription_status="active")
    db_session.add(user)
    db_session.commit()

    # Website hat Custom-Domain
    website = Website(user_id=user.id, domain="https://analytics.kunden-shop.at", tracking_token="pt_live_cname")
    db_session.add(website)
    db_session.commit()

    # 2. Caddy Endpoint anfragen für registrierte Domain -> Muss 200 OK + allowed: true liefern
    response_ok = client.get("/api/verify-cname-domain?domain=analytics.kunden-shop.at")
    assert response_ok.status_code == 200
    assert response_ok.json()["allowed"] is True

    # 3. Caddy Endpoint anfragen für nicht registrierte Domain -> Muss 403 liefern
    response_fail = client.get("/api/verify-cname-domain?domain=unbekanntes-shop.at")
    assert response_fail.status_code == 403


def test_stripe_checkout_creation(db_session, client):
    """Testet die Erstellung einer Stripe-Checkout-Session und den Redirect."""
    # 1. Test-User erstellen
    user = User(email="checkout_test@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user)
    db_session.commit()

    # 2. Session simulieren
    session_id = secrets.token_hex(32)
    sessions[session_id] = {"user_id": user.id, "email": user.email}

    # 3. Stripe Checkout Session mocken
    class MockCheckoutSession:
        id = "cs_test_abc123"
        url = "https://checkout.stripe.com/pay/cs_test_abc123"

    with patch("stripe.checkout.Session.create", return_value=MockCheckoutSession()) as mock_create:
        response = client.post(
            "/api/billing/checkout",
            data={"plan_type": "business"},
            headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"},
            follow_redirects=False
        )
        # Überprüfen, ob es ein Redirect zum Stripe-Checkout ist
        assert response.status_code == 303
        assert response.headers["location"] == "https://checkout.stripe.com/pay/cs_test_abc123"
        
        # Sicherstellen, dass Stripe mit den korrekten Parametern aufgerufen wurde
        mock_create.assert_called_once()
        kwargs = mock_create.call_args[1]
        assert kwargs["metadata"]["user_id"] == str(user.id)
        assert kwargs["tax_id_collection"]["enabled"] is True
        assert kwargs["automatic_tax"]["enabled"] is True


def test_synchronous_checkout_verification(db_session, client):
    """Testet die synchrone Freischaltung bei Rückkehr vom Stripe Checkout (B-1, B-3, B-4)."""
    # 1. Test-User im Trial-Modus anlegen
    user = User(email="verify_test@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user)
    db_session.commit()

    # 2. Mocking des Stripe-Session-Retrievals
    mock_session_details = {
        "id": "cs_test_abc123",
        "status": "complete",
        "payment_status": "paid",
        "customer": "cus_test_999",
        "subscription": "sub_test_888",
        "user_id": user.id
    }
    sessions["test_verify_session"] = {"user_id": user.id, "email": user.email}
    headers = {"Cookie": "pt_session=test_verify_session"}
    with patch("app.services.stripe_service.verify_checkout_session", return_value=mock_session_details):
        response = client.get("/api/verify-checkout?session_id=cs_test_abc123", headers=headers, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/?payment=success"
        # Prüfen, ob der Premium-Status in der Datenbank aktiv ist
        db_session.refresh(user)
        assert user.subscription_status == "active"
        assert user.stripe_customer_id == "cus_test_999"
        assert user.stripe_subscription_id == "sub_test_888"


def test_stripe_webhook_invoice_paid(db_session, client):
    """Simuliert einen erfolgreichen Stripe-Zahlungs-Webhook und prüft Freischaltung."""
    # 1. Test-User anlegen
    user = User(email="webhook_paid@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user)
    db_session.commit()

    # 2. Webhook Event mocken
    mock_event = {
        "type": "invoice.paid",
        "data": {
            "object": {
                "customer": "cus_webhook_123",
                "subscription": "sub_webhook_456",
                "metadata": {"user_id": str(user.id)}
            }
        }
    }

    with patch("stripe.Webhook.construct_event", return_value=mock_event):
        response = client.post(
            "/api/webhooks/stripe",
            content=b"raw_payload",
            headers={"stripe-signature": "t=123,v1=abc"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Prüfen, ob der Premium-Status in der Datenbank aktiv ist
        db_session.refresh(user)
        assert user.subscription_status == "active"
        assert user.stripe_customer_id == "cus_webhook_123"
        assert user.stripe_subscription_id == "sub_webhook_456"


def test_stripe_webhook_subscription_deleted(db_session, client):
    """Simuliert eine Kündigung über den Webhook und prüft Deaktivierung."""
    # 1. Aktiven Premium-User anlegen
    user = User(
        email="webhook_cancel@pepi.at", 
        password_hash="hash", 
        subscription_status="active",
        stripe_customer_id="cus_webhook_123",
        stripe_subscription_id="sub_webhook_456"
    )
    db_session.add(user)
    db_session.commit()

    # 2. Webhook Event mocken
    mock_event = {
        "type": "customer.subscription.deleted",
        "data": {
            "object": {
                "id": "sub_webhook_456",
                "customer": "cus_webhook_123"
            }
        }
    }

    with patch("stripe.Webhook.construct_event", return_value=mock_event):
        response = client.post(
            "/api/webhooks/stripe",
            content=b"raw_payload",
            headers={"stripe-signature": "t=123,v1=abc"}
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

        # Prüfen, ob der Premium-Status deaktiviert wurde
        db_session.refresh(user)
        assert user.subscription_status == "canceled"


def test_health_endpoint(client):
    """Testet den System-Health Check auf korrekte JSON-Rückgabe."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "queue_size" in data
    assert data["max_queue_size"] == 10000


def test_public_demo_endpoint(client):
    """Testet den öffentlichen Demo-Statistiken Endpoint auf korrekte Struktur."""
    response = client.get("/api/demo/stats")
    assert response.status_code == 200
    data = response.json()
    assert data["website_id"] == 999
    assert data["domain"] == "https://demo.pulsetrack.io"
    assert "total_hits" in data
    assert "unique_visitors" in data
    assert "live_visitors" in data
    assert len(data["top_pages"]) == 5
    assert len(data["top_referrers"]) == 5


def test_avv_sign_flow(db_session, client):
    """Testet den revisionssicheren AVV-Zustimmungs-Workflow per API."""
    # 1. Test-User erstellen
    user = User(email="avv_sign_test@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user)
    db_session.commit()

    # 2. Session simulieren
    session_id = secrets.token_hex(32)
    sessions[session_id] = {"user_id": user.id, "email": user.email}

    # 3. AVV signieren
    response = client.post(
        "/api/avv/sign",
        data={"avv_version": "1.0"},
        headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "signed"
    assert "signature_hash" in data

    # 4. Datenbank verifizieren
    signature = db_session.query(UserAVVSignature).filter(UserAVVSignature.user_id == user.id).first()
    assert signature is not None
    assert signature.avv_version == "1.0"
    assert signature.signed_from_ip in ("127.0.0.0", "IPv6")  # Anonymisiertes Format


def test_database_pruning(db_session, client):
    """Testet die automatische, tarifbasierte Löschung veralteter Analytics-Daten."""
    from app.database import prune_database
    
    # 1. Trial-User und Website anlegen
    user_trial = User(email="trial_pruning@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user_trial)
    db_session.commit()
    
    web_trial = Website(user_id=user_trial.id, domain="https://trial.at", tracking_token="pt_trial_pruning")
    db_session.add(web_trial)
    db_session.commit()

    # 2. Hits anlegen für Trial-User: 1 Hit von heute (behalten), 1 Hit von vor 15 Tagen (löschen)
    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    ts_now = now
    ts_old = (now - timedelta(days=15))
    
    hit_recent = Hit(website_id=web_trial.id, timestamp=ts_now, url="/home", user_agent="Mozilla", ip_hash="hash1", browser="Chrome", os="Windows")
    hit_old = Hit(website_id=web_trial.id, timestamp=ts_old, url="/old", user_agent="Mozilla", ip_hash="hash2", browser="Chrome", os="Windows")
    db_session.add(hit_recent)
    db_session.add(hit_old)
    db_session.commit()

    # 3. DB-Pruning-Mock patch SessionLocal to use our test db session
    with patch("app.database.SessionLocal", return_value=NonClosingSessionProxy(db_session)):
        prune_database()

    # 4. Verifizieren: Alter Hit gelöscht, neuer Hit behalten!
    hits = db_session.query(Hit).filter(Hit.website_id == web_trial.id).all()
    assert len(hits) == 1
    assert hits[0].url == "/home"


# --- Neue expanded Härtetests (F-3, F-4, C-5, D-3) ---

@pytest.mark.asyncio
async def test_hit_ingestion_happy_path(db_session, client):
    """F-3: Härtetest für Hit Ingestion Happy Path (Capture, Queue, Batch-Persistence)."""
    # 1. User & Website anlegen
    user = User(email="ingest_happy@pepi.at", password_hash="hash", subscription_status="active")
    db_session.add(user)
    db_session.commit()

    web = Website(user_id=user.id, domain="https://mypage.com", tracking_token="pt_ingest_happy")
    db_session.add(web)
    db_session.commit()

    # Queue leeren
    while not hit_queue.empty():
        hit_queue.get_nowait()
        hit_queue.task_done()

    # 2. Hit posten (202 Accepted)
    payload = {"token": "pt_ingest_happy", "url": "https://mypage.com/pricing", "referrer": "https://google.com"}
    response = client.post("/api/hit", json=payload, headers={"Origin": "https://mypage.com"})
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"

    # 3. Queue-Inhalt prüfen
    assert hit_queue.qsize() == 1
    hit_in_queue = await hit_queue.get()
    assert hit_in_queue["token"] == "pt_ingest_happy"
    assert hit_in_queue["url"] == "https://mypage.com/pricing"
    hit_queue.task_done()

    # 4. Persistenz ausführen
    await save_batch_to_db([hit_in_queue])

    # 5. DB-Inhalt validieren
    hit_db = db_session.query(Hit).filter(Hit.website_id == web.id).first()
    assert hit_db is not None
    assert hit_db.url == "https://mypage.com/pricing"
    assert hit_db.referrer == "https://google.com"


def test_hit_ingestion_unauthorized_token(db_session, client):
    """F-4: Hit Ingestion mit ungültigem Token abweisen (403)."""
    payload = {"token": "pt_invalid_token", "url": "https://mypage.com/pricing"}
    response = client.post("/api/hit", json=payload, headers={"Origin": "https://mypage.com"})
    assert response.status_code == 403


def test_hit_ingestion_unauthorized_origin(db_session, client):
    """F-4: Hit Ingestion mit falscher Herkunfts-Domain (CORS) abweisen (403)."""
    user = User(email="ingest_cors@pepi.at", password_hash="hash", subscription_status="active")
    db_session.add(user)
    db_session.commit()

    web = Website(user_id=user.id, domain="https://mypage.com", tracking_token="pt_ingest_cors")
    db_session.add(web)
    db_session.commit()

    payload = {"token": "pt_ingest_cors", "url": "https://mypage.com/pricing"}
    # Origin passt nicht zur registrierten Domain https://mypage.com
    response = client.post("/api/hit", json=payload, headers={"Origin": "https://gehackte-seite.com"})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_hit_ingestion_rate_limiting(db_session, client):
    """F-4: Hit Ingestion Rate Limiting testen (>60 Hits/Min blocken mit 429)."""
    user = User(email="ingest_rl@pepi.at", password_hash="hash", subscription_status="active")
    db_session.add(user)
    db_session.commit()

    web = Website(user_id=user.id, domain="https://mypage.com", tracking_token="pt_ingest_rl")
    db_session.add(web)
    db_session.commit()

    payload = {"token": "pt_ingest_rl", "url": "https://mypage.com/pricing"}
    
    # 60 Anfragen simulieren (das ist das Rate-Limit-Fenster)
    from app.services.security import rate_limit_store
    rate_limit_store.clear()

    for _ in range(60):
        response = client.post("/api/hit", json=payload, headers={"Origin": "https://mypage.com"})
        assert response.status_code == 202

    # 61. Anfrage muss abgeblockt werden!
    response_block = client.post("/api/hit", json=payload, headers={"Origin": "https://mypage.com"})
    assert response_block.status_code == 429
    assert "Too many tracking requests" in response_block.json()["detail"]


def test_gdpr_account_deletion(db_session, client):
    """C-5: DSGVO Recht auf Löschen (Art. 17) Härtetest (Cascade Delete auf Websites, Hits, Signaturen und Logout)."""
    # 1. User, Website, Hits und AVV-Signatur anlegen
    user = User(email="gdpr-delete@pepi.at", password_hash="hash", subscription_status="active")
    db_session.add(user)
    db_session.commit()

    web = Website(user_id=user.id, domain="https://mypage.com", tracking_token="pt_gdpr_token")
    db_session.add(web)
    db_session.commit()

    hit = Hit(website_id=web.id, timestamp=datetime.utcnow(), url="/pricing", ip_hash="abc", browser="Chrome", os="Windows")
    db_session.add(hit)

    sig = UserAVVSignature(user_id=user.id, avv_version="1.0", signed_from_ip="127.0.0.0", signature_hash="hash")
    db_session.add(sig)
    db_session.commit()

    # 2. Login simulieren
    session_id = secrets.token_hex(32)
    sessions[session_id] = {"user_id": user.id, "email": user.email}

    # 3. Loeschungs-Endpoint aufrufen
    response = client.delete("/api/account", headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"})
    assert response.status_code == 200
    assert "unwiderruflich geloescht" in response.json()["message"]

    # 4. Verifizieren: Kaskadiertes Loeschen der Daten in der DB
    user_check = db_session.query(User).filter(User.id == user.id).first()
    assert user_check is None

    web_check = db_session.query(Website).filter(Website.id == web.id).first()
    assert web_check is None

    hit_check = db_session.query(Hit).filter(Hit.website_id == web.id).first()
    assert hit_check is None

    sig_check = db_session.query(UserAVVSignature).filter(UserAVVSignature.user_id == user.id).first()
    assert sig_check is None

    # 5. Verifizieren: Session ist serverseitig gelöscht und Cookie entfernt
    assert session_id not in sessions


def test_session_expiry_enforcement(db_session, client):
    """D-3: Serverseitiges Session-Ablauf-Enforcement testen (Expired Session -> 401)."""
    user = User(email="session_exp@pepi.at", password_hash="hash", subscription_status="trial")
    db_session.add(user)
    db_session.commit()

    # 1. Abgelaufene Session anlegen (expires_at in der Vergangenheit)
    session_id = secrets.token_hex(32)
    sessions[session_id] = {
        "user_id": user.id,
        "email": user.email,
        "expires_at": time.time() - 1000  # Vor 1000 Sekunden abgelaufen
    }

    # 2. Aufruf eines geschützten Endpoints mit dieser abgelaufenen Session -> Muss 401 liefern
    response = client.get("/api/dashboard/stats?website_id=1", headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"})
    assert response.status_code == 401
    assert "Session expired" in response.json()["detail"]

    # 3. Verifizieren: Session wurde serverseitig bereinigt
    assert session_id not in sessions
