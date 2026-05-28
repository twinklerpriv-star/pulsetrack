# PulseTrack - Web-Analytics MVP

**Datum:** 20.05.2026 | **Version:** 1.0 | **Status:** MVP Funktionsbereit

PulseTrack ist ein extrem leichtgewichtiges, datenschutzfreundliches und selbst gehostetes Web-Analytics-System. Es dient als datenschutzkonforme (DSGVO-konforme) Alternative zu Google Analytics oder Plausible.

---

## Key Features & USPs (Unique Selling Propositions)

1.  **Absolut Cookie-frei & DSGVO-konform:** Keine Nutzung von Cookies zur Identifikation von Besuchern. IP-Adressen werden zur Wahrung der Privatsphäre sofort mit einem kryptografischen Salt gehasht (`SHA-256`) und niemals im Klartext gespeichert.
2.  **Ultra-Leichtgewichtiger Client-Tracker (< 1KB):** Der JavaScript-Client (`tracker.js`) beeinträchtigt die Ladezeit von Webseiten nicht und nutzt modernste Browser-APIs wie `navigator.sendBeacon` zur asynchronen Hintergrundübermittlung.
3.  **Modernes Premium-Dashboard:** Ein ansprechendes, glassmorphistisches Dark-Mode-Dashboard zur Echtzeit-Analyse von Seitenaufrufen, eindeutigen Besuchern, Verweisen (Referrer), Browser- und Betriebssystem-Verteilungen.
4.  **Zero-Dependency-Database:** Nutzt das in Python standardmäßig integrierte `SQLite` zur ressourcenschonenden, lokalen Datenspeicherung ohne zusätzliche relationale DB-Server.

---

## Technische Architektur

*   **Backend API:** FastAPI (hochperformantes Python-Framework)
*   **Datenbank:** SQLite (via Python Standard-Bibliothek `sqlite3`)
*   **Frontend-Dashboard:** HTML5 / CSS3 (Modernes Glassmorphism-UI, Google Fonts "Outfit" & "Inter")
*   **Paket-Manager:** `uv` (extrem schneller moderner Python-Paketmanager)
*   **Qualitätssicherung:** `ruff` (Linter & Formatter), `pytest` (API-Tests)

---

## Installation & Startanleitung

### Windows (ohne Befehle – per Doppelklick)

Im Ordner `01`:

1. **`START-HIER.bat`** oder einmalig **`install.bat`**
2. **`start.bat`** – startet den Server und öffnet den Setup-Assistenten im Browser

### Mit uv (Kommandozeile)

Stellen Sie sicher, dass Sie den modernen Python-Paketmanager **`uv`** installiert haben.

### 1. Abhängigkeiten installieren
Führen Sie im Verzeichnis `/01` folgenden Befehl aus, um die virtuelle Umgebung zu erstellen und alle Abhängigkeiten zu installieren:

```bash
uv venv
uv pip install -e .
```

*Alternativ, da wir ein Standard-Setup nutzen, installieren Sie die Pakete über `uv pip` direkt:*
```bash
uv pip install fastapi uvicorn jinja2 pydantic httpx pytest
```

### 2. Die Anwendung starten
Starten Sie den lokalen Web- und Analytics-Server mit Uvicorn:

```bash
uv run uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

**Windows (ohne `uv`):** Nutzen Sie den Python-Launcher `py`:

```bash
py -m pip install fastapi uvicorn jinja2 pydantic
py -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Beim ersten Start leitet PulseTrack auf den **Setup-Assistenten** um: [http://127.0.0.1:8000/setup](http://127.0.0.1:8000/setup)

*   **Das Analyse-Dashboard** ist unter [http://127.0.0.1:8000/](http://127.0.0.1:8000/) erreichbar (nach abgeschlossener Einrichtung).
*   **Der JS-Tracker** ist unter [http://127.0.0.1:8000/tracker.js](http://127.0.0.1:8000/tracker.js) abrufbar.

---

## Integration auf Client-Webseiten

Fügen Sie einfach das folgende Script-Tag in das HTML-Dokument (`<head>` oder `<body>`) jeder Webseite ein, die Sie tracken möchten. Ersetzen Sie `localhost:8000` durch Ihre Server-Domain:

```html
<script src="http://127.0.0.1:8000/tracker.js" defer></script>
```

---

## Qualitätssicherung (Tests & Code-Qualität)

Um die Einhaltung unserer Code-Qualitätsregeln zu überprüfen, können Sie folgende Befehle ausführen:

### Tests ausführen (pytest)
```bash
uv run pytest
```

**Windows:**
```bash
py -m pip install pytest httpx fastapi uvicorn jinja2 pydantic
py -m pytest
```

### Code-Qualität prüfen (ruff)
```bash
uv run ruff check .
```

---

## Lizenz

Dieses Projekt ist unter der **GNU Affero General Public License v3.0 (AGPL-3.0)** lizenziert. Details finden Sie in der [LICENSE](file:///c:/Users/monik/Desktop/Thomas/Programmierung/Earning%20Money/01/LICENSE)-Datei.

Die AGPL v3 stellt sicher, dass alle Verbesserungen an der Codebasis der Community zugänglich gemacht werden müssen, wenn PulseTrack als Cloud-Dienst (SaaS) angeboten wird. Dies schützt das Projekt vor unlauterem Trittbrettfahren und fördert eine kollaborative Weiterentwicklung.

