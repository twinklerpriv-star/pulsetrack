# Dockerfile: PulseTrack
# Datum: 20.05.2026 | Version: 1.0 | Status: Produktionsbereit

# --- Stage 1: Builder ---
# Nutzt uv für blitzschnelle Dependency-Installation
FROM python:3.11-slim AS builder

# Systemabhängigkeiten für uv
RUN pip install uv --no-cache-dir

WORKDIR /build

# Abhängigkeiten zuerst kopieren (Layer-Caching: bei Code-Änderungen bleibt dieser Layer erhalten)
COPY pyproject.toml .
RUN uv pip install --system fastapi uvicorn jinja2 pydantic

# --- Stage 2: Runtime ---
# Minimales Image, kein Build-Overhead im finalen Container
FROM python:3.11-slim AS runtime

# Sicherheit: Kein Root-Benutzer im Container
RUN useradd --no-create-home --shell /bin/false appuser

WORKDIR /app

# Installierte Python-Pakete aus dem Builder übernehmen
COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin /usr/local/bin

# Anwendungscode kopieren
COPY app/ ./app/

# Datenbank-Verzeichnis anlegen und Rechte setzen
RUN mkdir -p /data && chown appuser:appuser /data

# Als Nicht-Root-User ausführen
USER appuser

# Umgebungsvariablen (Sicherheits-Defaults)
ENV ANALYTICS_SALT_SECRET="change-me-in-production"
ENV ANALYTICS_DB_PATH="/data/analytics.db"

# Port freigeben
EXPOSE 8000

# Health-Check: prüft alle 30s ob der Server antwortet
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/tracker.js')"

# Startbefehl: Produktions-Server mit 2 Workern
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
