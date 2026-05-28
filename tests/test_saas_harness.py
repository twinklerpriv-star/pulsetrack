# SaaS QA Test-Suite: Multi-Tenancy, Queue Flush, HMAC-Rotation & Caddy TLS
#
# Datum: 28.05.2026 | Version: 1.0 | Status: Aktiv gepflegt

import os
import secrets
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Sicherstellen, dass das Env-Secret gesetzt ist
os.environ["ANALYTICS_SALT_SECRET"] = "test_system_salt_secret_1234567890"

from app.database import Base, get_db
from app.main import app
from app.models.hit import Hit
from app.models.user import DailyKey, User
from app.models.website import Website
from app.routers.auth import SESSION_COOKIE_NAME, ph, sessions
from app.services.queue_worker import hit_queue, write_queue_to_db
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
    """Initialisiert die DB-Tabellen vor dem Testdurchlauf und löscht sie danach."""
    Base.metadata.create_all(bind=engine_test)
    yield
    Base.metadata.drop_all(bind=engine_test)

from unittest.mock import patch


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
    """Bietet eine saubere, transaktionsisolierte DB-Session für jeden Testfall."""
    connection = engine_test.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)
    
    # Session überschreiben im FastAPI-Dependency-System
    def override_get_db():
        try:
            yield session
        finally:
            pass
            
    app.dependency_overrides[get_db] = override_get_db
    
    # Patch SessionLocal in app.services.queue_worker to write hits to the test database
    # Wir nutzen den Proxy, damit save_batch_to_db() unsere Test-Session nicht schließt
    with patch("app.services.queue_worker.SessionLocal", return_value=NonClosingSessionProxy(session)):
        yield session
    
    session.close()
    transaction.rollback()
    connection.close()
    app.dependency_overrides.clear()
    sessions.clear()  # Session-Store aufräumen

client = TestClient(app)

# 2. Testfälle

def test_user_registration_and_login(db_session):
    """Prüft die Neuregistrierung, Passwortsicherung mit Argon2 und den Login-Prozess."""
    # 1. Registrieren
    reg_data = {"email": "pepi@elektro-pepi.at", "password": "SuperSecurePassword123!"}
    response_reg = client.post("/register", data=reg_data)
    assert response_reg.status_code == 200
    assert "registered" in response_reg.json()["message"]

    # 2. Prüfen, ob der User in der DB existiert und passwortgehasht ist
    user = db_session.query(User).filter(User.email == "pepi@elektro-pepi.at").first()
    assert user is not None
    assert user.password_hash.startswith("$argon2id$")  # Verifiziert Argon2id-Präfix

    # 3. Einloggen
    response_login = client.post("/login", data=reg_data)
    assert response_login.status_code == 200
    assert SESSION_COOKIE_NAME in response_login.cookies

    # 4. Falsches Passwort prüfen
    response_fail = client.post("/login", data={"email": "pepi@elektro-pepi.at", "password": "WrongPassword"})
    assert response_fail.status_code == 400


def test_multi_tenant_data_isolation(db_session):
    """Verifiziert die absolute Multi-Tenant-Datenisolierung (User A darf nicht auf User B zugreifen)."""
    # 1. Zwei Test-User anlegen
    userA = User(email="user_a@test.com", password_hash=ph.hash("passA"), created_at="2026-05-28", subscription_status="trial")
    userB = User(email="user_b@test.com", password_hash=ph.hash("passB"), created_at="2026-05-28", subscription_status="trial")
    db_session.add(userA)
    db_session.add(userB)
    db_session.commit()

    # 2. Webseiten anlegen (Website A gehört User A, Website B gehört User B)
    webA = Website(user_id=userA.id, domain="https://siteA.com", tracking_token="pt_live_tokenA", created_at="2026-05-28")
    webB = Website(user_id=userB.id, domain="https://siteB.com", tracking_token="pt_live_tokenB", created_at="2026-05-28")
    db_session.add(webA)
    db_session.add(webB)
    db_session.commit()

    # 3. Login als User A (Session erzeugen)
    session_id = secrets.token_hex(32)
    sessions[session_id] = {"user_id": userA.id, "email": userA.email}

    # 4. Zugriff auf eigene Daten (Website A) -> Muss erlaubt sein (200)
    # Wir übergeben das Cookie absolut verlässlich direkt im HTTP-Header
    response_own = client.get(f"/api/dashboard/stats?website_id={webA.id}", headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"})
    assert response_own.status_code == 200
    assert response_own.json()["domain"] == "https://siteA.com"

    # 5. Zugriff auf fremde Daten (Website B) -> Muss verweigert werden (403)
    response_foreign = client.get(f"/api/dashboard/stats?website_id={webB.id}", headers={"Cookie": f"{SESSION_COOKIE_NAME}={session_id}"})
    assert response_foreign.status_code == 403
    assert "Access denied" in response_foreign.json()["detail"]


@pytest.mark.asyncio
async def test_graceful_shutdown_queue_flushing(db_session):
    """Testet die SIGTERM-Datenrettungs-Logik: Puffer-Hits werden beim Herunterfahren in die DB geschrieben."""
    # 1. Test-User und Website anlegen
    user = User(email="pepi@pepi.at", password_hash="hash", created_at="2026-05-28", subscription_status="active")
    db_session.add(user)
    db_session.commit()
    
    website = Website(user_id=user.id, domain="https://pepi.at", tracking_token="pt_live_graceful", created_at="2026-05-28")
    db_session.add(website)
    db_session.commit()

    # 2. Queue manuell mit ungeschriebenen Hits füllen
    # Zuerst Queue leeren, um Unabhängigkeit zu garantieren
    while not hit_queue.empty():
        hit_queue.get_nowait()
        hit_queue.task_done()

    for i in range(3):
        await hit_queue.put({
            "token": "pt_live_graceful",
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "url": f"https://pepi.at/page{i}.html",
            "referrer": None,
            "user_agent": "Mozilla/5.0",
            "ip_hash": f"hash_{i}",
            "browser": "Chrome",
            "os": "Windows"
        })

    # 3. Graceful Shutdown Signal triggern (wir flushen manuell über die Service-Methode)
    # Da get_db() überschrieben ist, leiten wir mockmäßig an die Session weiter
    app.dependency_overrides[get_db] = lambda: db_session
    await write_queue_to_db()

    # 4. Verifizieren: Queue muss leer sein
    assert hit_queue.empty() is True

    # 5. Verifizieren: Hits müssen in der DB sein
    hits = db_session.query(Hit).filter(Hit.website_id == website.id).all()
    assert len(hits) == 3
    assert hits[0].url == "https://pepi.at/page0.html"


def test_hmac_key_rotation_forward_secrecy(db_session):
    """Valide die Krypto-Rotationslogik: Löschen alter Keys verhindert rückwirkende IP-Hashes Rekonstruktion."""
    # 1. Hole heutigen Key
    key_today = get_or_create_daily_hmac_key(db_session)
    assert len(key_today) == 64  # Hex von 32-Byte Key

    # 2. IP hashen
    ip = "203.0.113.195"
    hash_a = hash_ip_address(ip, key_today)

    # 3. Simuliere einen alten Schlüssel (von gestern)
    yesterday = datetime.now(tz=timezone.utc) - timedelta(days=2)
    yesterday_str = yesterday.strftime("%Y-%m-%d")
    old_key = DailyKey(day=yesterday_str, key_value=secrets.token_hex(32))
    db_session.add(old_key)
    db_session.commit()

    # 4. Rotation triggern -> Muss alte Keys löschen, aber den von heute behalten
    rotate_daily_hmac_key(db_session)

    # 5. Verifizieren: Key von heute existiert noch, der alte ist gelöscht
    key_today_check = db_session.query(DailyKey).filter(DailyKey.day == datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")).first()
    assert key_today_check is not None

    key_old_check = db_session.query(DailyKey).filter(DailyKey.day == yesterday_str).first()
    assert key_old_check is None


def test_caddy_cname_verification(db_session):
    """Testet den Dynamic-SSL Endpoint zur Freigabe von Zertifikaten für Custom Domains."""
    # 1. User & Website anlegen
    user = User(email="caddy@test.com", password_hash="hash", created_at="2026-05-28", subscription_status="active")
    db_session.add(user)
    db_session.commit()

    # Website hat Custom-Domain
    website = Website(user_id=user.id, domain="https://analytics.kunden-shop.at", tracking_token="pt_live_cname", created_at="2026-05-28")
    db_session.add(website)
    db_session.commit()

    # 2. Caddy Endpoint anfragen für registrierte Domain -> Muss 200 OK + allowed: true liefern
    response_ok = client.get("/api/verify-cname-domain?domain=analytics.kunden-shop.at")
    assert response_ok.status_code == 200
    assert response_ok.json()["allowed"] is True

    # 3. Caddy Endpoint anfragen für nicht registrierte Domain -> Muss 403 liefern
    response_fail = client.get("/api/verify-cname-domain?domain=unbekanntes-shop.at")
    assert response_fail.status_code == 403


def test_stripe_checkout_creation(db_session):
    """Testet die Erstellung einer Stripe-Checkout-Session und den Redirect."""
    # 1. Test-User erstellen
    user = User(email="checkout_test@pepi.at", password_hash="hash", created_at="2026-05-28", subscription_status="trial")
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


def test_synchronous_checkout_verification(db_session):
    """Testet die synchrone Freischaltung bei Rückkehr vom Stripe Checkout."""
    # 1. Test-User im Trial-Modus anlegen
    user = User(email="verify_test@pepi.at", password_hash="hash", created_at="2026-05-28", subscription_status="trial")
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

    with patch("app.services.stripe_service.verify_checkout_session", return_value=mock_session_details):
        response = client.get("/api/verify-checkout?session_id=cs_test_abc123", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/?payment=success"

        # Prüfen, ob der Premium-Status in der Datenbank aktiv ist
        db_session.refresh(user)
        assert user.subscription_status == "active"
        assert user.stripe_customer_id == "cus_test_999"
        assert user.stripe_subscription_id == "sub_test_888"


def test_stripe_webhook_invoice_paid(db_session):
    """Simuliert einen erfolgreichen Stripe-Zahlungs-Webhook und prüft Freischaltung."""
    # 1. Test-User anlegen
    user = User(email="webhook_paid@pepi.at", password_hash="hash", created_at="2026-05-28", subscription_status="trial")
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


def test_stripe_webhook_subscription_deleted(db_session):
    """Simuliert eine Kündigung über den Webhook und prüft Deaktivierung."""
    # 1. Aktiven Premium-User anlegen
    user = User(
        email="webhook_cancel@pepi.at", 
        password_hash="hash", 
        created_at="2026-05-28", 
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


def test_health_endpoint():
    """Testet den System-Health Check auf korrekte JSON-Rückgabe."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "queue_size" in data
    assert data["max_queue_size"] == 10000


def test_public_demo_endpoint():
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


def test_avv_sign_flow(db_session):
    """Testet den revisionssicheren AVV-Zustimmungs-Workflow per API."""
    # 1. Test-User erstellen
    user = User(email="avv_sign_test@pepi.at", password_hash="hash", created_at="2026-05-28", subscription_status="trial")
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
    from app.models.user import UserAVVSignature
    signature = db_session.query(UserAVVSignature).filter(UserAVVSignature.user_id == user.id).first()
    assert signature is not None
    assert signature.avv_version == "1.0"
    assert signature.signed_from_ip in ("127.0.0.0", "IPv6")  # Anonymisiertes Format
