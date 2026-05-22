# API Smoke-Tests
#
# Datum: 20.05.2026 | Version: 1.0 | Status: In Entwicklung
#
# Diese Testsuite validiert die Funktionsfähigkeit der FastAPI-Endpunkte
# unseres Analytics-Tools.


import pytest
from fastapi.testclient import TestClient

from app import database
from app.main import app


@pytest.fixture(scope="module", autouse=True)
def setup_database() -> None:
    """Initialisiert die Datenbank vor dem Start der Test-Suite."""
    database.init_db()

@pytest.fixture
def client():
    """Liefert einen TestClient, der die Startup-Events korrekt ausführt."""
    with TestClient(app) as c:
        yield c

def test_tracker_endpoint(client) -> None:
    """Prüft, ob das JavaScript-Tracking-Skript erfolgreich ausgeliefert wird."""
    response = client.get("/tracker.js")

    assert response.status_code == 200
    assert "application/javascript" in response.headers["content-type"]
    assert "pulsetrack" in response.text or "Analytics" in response.text

def test_capture_hit(client) -> None:
    """Prüft, ob ein Seitenaufruf (Hit) korrekt per POST von der API akzeptiert wird."""
    payload = {
        "url": "https://example.com/test-page",
        "referrer": "https://google.com"
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0.0.0 Safari/537.36"
    }
    
    response = client.post("/api/hit", json=payload, headers=headers)
    assert response.status_code == 202
    assert response.json() == {"status": "accepted"}

def test_dashboard(client) -> None:
    """Prüft, ob das Web-Dashboard erfolgreich serverseitig gerendert wird und erreichbar ist."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "PulseTrack" in response.text

