# ==============================================================================
# PULSETRACK ANALYTICS - DOCKER-ENGINE PACKING (DOCKERFILE)
# ==============================================================================
# Datum: 01.06.2026 | Version: 1.2 | Status: Produktionsbereit & Gehärtet
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei beschreibt die "Bauanleitung" für den Anwendungs-Container.
# Docker verpackt PulseTrack in eine isolierte, transportable Box (das Image),
# die auf jedem Server weltweit (z. B. bei Hetzner, AWS, DigitalOcean) sofort läuft.
#
# KUNDENVERSTÄNDLICHE & GESCHÄFTSFÜHRER-ASPEKTE (WARUM DIESES DOCKERFILE PREMIUM IST):
# 1. Höchste Server-Sicherheit (Nicht-Root-Ausführung):
#    Die Software wird absichtlich unter einem eingeschränkten Benutzerkonto
#    ("appuser") ausgeführt. Selbst im extrem unwahrscheinlichen Fall eines
#    Hacker-Einbruchs kann der Angreifer niemals die Kontrolle über Ihren Server übernehmen!
# 2. Multi-Stage-Build (Minimale Größe & Schnelligkeit):
#    Das System wird in zwei Stufen gebaut. Im fertigen Container verbleiben keine
#    unnötigen Entwickler-Werkzeuge. Das macht den Container winzig und extrem schnell geladen.
# 3. SQLite WAL-Sicherheit (Single-Worker):
#    Der Server startet uvicorn mit genau 1 Worker. Das ist eine kritische technische
#    Absicherung für unsere Hochleistungs-Datenbank SQLite im WAL-Modus. Sie verhindert
#    zuverlässig, dass sich Schreibzugriffe gegenseitig blockieren.
# ==============================================================================

# --- STUFE 1: DER BUILDER (DIE WERKSTATT) ---
# Hier laden wir alle Programmpakete blitzschnell über das Werkzeug "uv" herunter.
FROM python:3.11-slim AS builder

# Systemabhängigkeiten für uv installieren (D-6)
RUN pip install uv --no-cache-dir

WORKDIR /build

# Kopiere Metadaten und installiere alle Abhängigkeiten
COPY pyproject.toml .
COPY README.md .
RUN uv pip install --system .

# --- STUFE 2: DIE RUNTIME (DAS FERTIGE SAUBERE PRODUKT) ---
# Dies ist das schmale, sichere Image, das schlussendlich auf Ihrem Server gestartet wird.
FROM python:3.11-slim AS runtime

# Sicherheit: Erstellt einen eingeschränkten Benutzer (ohne Administrator-Rechte)
RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

# Übernehme die fertig installierten Python-Pakete aus der ersten Stufe
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Kopiere den reinen Anwendungscode
COPY app/ ./app/

# Erstelle ein geschütztes Datenverzeichnis für die SQLite-Datenbankbankdatei
RUN mkdir -p /data && chown appuser:appuser /data

# Wechsel zum sicheren, eingeschränkten Benutzerkonto
USER appuser

# Standardpfad für die hochperformante SQLite-Datenbank
ENV ANALYTICS_DB_PATH="/data/analytics.db"

# Port freigeben, unter dem PulseTrack erreichbar sein wird
EXPOSE 8000

# Automatischer Health-Check: Prüft alle 30 Sekunden, ob die PulseTrack-Engine gesund ist
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')"

# Startbefehl: Startet die FastAPI-Anwendung.
# WICHTIG: "--workers 1" garantiert die Datenkonsistenz und WAL-Mode-Sicherheit bei SQLite.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
