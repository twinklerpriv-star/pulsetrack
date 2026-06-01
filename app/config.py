# ==============================================================================
# PULSETRACK ANALYTICS - KONFIGURATION & EINSTELLUNGS-MANAGEMENT
# ==============================================================================
# Datum: 01.06.2026 | Version: 2.1 | Status: Aktiv gepflegt & Sicherheitsüberwacht
#
# BETRIEBSWIRTSCHAFTLICHER ZWECK DIESER DATEI:
# Diese Datei lädt und validiert alle Systemeinstellungen (z. B. Zugänge für den
# Zahlungsdienstleister Stripe, E-Mail-Einstellungen und den geheimen Sicherheits-
# Schlüssel). Sie stellt sicher, dass das System nur mit sicheren Passwörtern
# startet und fehlerhafte Konfigurationen sofort beim Starten abgefangen werden.
#
# AUSWIRKUNG FÜR DEN KUNDEN / GESCHÄFTSFÜHRER:
# - Schutz vor unsicheren Standard-Passwörtern: Die Software verweigert den
#   Start, wenn der IT-Techniker vergisst, die Standard-Passwörter zu ändern.
# - Flexibilität: Alle Abrechnungspläne (Starter, Business) werden hier zentral
#   definiert, was spätere Tarifanpassungen extrem einfach macht.
#
# INFORMATION FÜR DEN IT-TECHNIKER:
# - Basiert auf Pydantic BaseSettings zur automatischen Erkennung von .env-Dateien.
# - Verwendet SecretStr, um sensible Passwörter vor versehentlichem Logging zu schützen.
# ==============================================================================

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import ConfigDict, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """
    Diese Klasse liest die Konfigurationen aus den Umgebungsvariablen oder einer '.env'-Datei.
    Sie validiert die Werte zur Laufzeit, um Abstürze während des Betriebs zu verhindern.
    """
    # Geheimer Masterschlüssel für die Anonymisierung der Besucher-IP-Adressen
    ANALYTICS_SALT_SECRET: SecretStr
    
    # Speicherort der SQLite-Datenbankdatei (Standard: analytics.db)
    ANALYTICS_DB_PATH: str = "analytics.db"
    
    # --------------------------------------------------------------------------
    # Stripe Abrechnungskonfiguration (B2B-Abonnements)
    # --------------------------------------------------------------------------
    STRIPE_SECRET_KEY: SecretStr
    STRIPE_PUBLISHABLE_KEY: str = "pk_test_mock"
    STRIPE_WEBHOOK_SECRET: SecretStr
    
    # Stripe Price IDs: Diese verknüpfen PulseTrack mit Ihren Tarifen in Stripe
    STRIPE_PRICE_STARTER: str = "price_starter"
    STRIPE_PRICE_BUSINESS: str = "price_business"
    STRIPE_PRICE_ENTERPRISE: str = "price_enterprise"

    # --------------------------------------------------------------------------
    # SMTP E-Mail-Konfiguration (Transaktions-Mails für Kündigungen & Rechnungen)
    # --------------------------------------------------------------------------
    SMTP_HOST: str | None = None
    SMTP_PORT: int | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: SecretStr | None = None

    model_config = ConfigDict(
        env_file=".env",
        extra="ignore"
    )

    @field_validator("ANALYTICS_SALT_SECRET")
    @classmethod
    def secret_must_not_be_default(cls, v: SecretStr) -> SecretStr:
        """
        SICHERHEITSVALIDIERUNG:
        Verhindert, dass PulseTrack im unsicheren "Demonstrationsmodus" in Produktion geht.
        Trägt der IT-Techniker das Standardpasswort ein, bricht der Start ab.
        """
        if v.get_secret_value() in ("change-me-in-production", "pulsetrack-fallback-secret"):
            raise ValueError("ANALYTICS_SALT_SECRET MUSS für die produktive Nutzung zwingend geändert werden!")
        return v


@lru_cache
def get_settings() -> Settings:
    """Caching-Funktion: Lädt die Einstellungen nur einmal im Speicher, um Performance zu sparen."""
    return Settings()


# Globale Instanz für den einfachen Import in allen Systemkomponenten
settings = get_settings()


@dataclass
class InstallConfig:
    """Repräsentiert den Installations- und Aktivierungsstatus einer Kundenwebsite."""
    configured: bool
    primary_site: str | None
    allowed_origins: list[str]
    track_apex: bool
    track_subdomains: bool
    permissive: bool

    @property
    def is_active(self) -> bool:
        return self.configured and (self.permissive or bool(self.allowed_origins))


def get_database_path() -> str:
    """Gibt den Pfad zur SQLite-Datenbankdatei zurück."""
    return settings.ANALYTICS_DB_PATH



def normalize_site_url(raw: str) -> str:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    Bereinigt eine vom Nutzer eingegebene Website-Adresse. Egal ob der Nutzer
    "www.elektro-pepi.at", "http://elektro-pepi.at/" oder "https://www.elektro-pepi.at"
    eingibt – diese Funktion wandelt es in ein einheitliches Format um (z. B. "https://www.elektro-pepi.at").
    Dies verhindert doppelte Einträge und Setup-Fehler.
    """
    value = raw.strip()
    if not value:
        raise ValueError("Bitte eine Website-URL eingeben.")

    # Fehlendes Protokoll (https) automatisch ergänzen
    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("Nur http:// oder https:// URLs sind erlaubt.")
    if not parsed.netloc:
        raise ValueError("Ungültige URL – Hostname fehlt.")

    host = parsed.netloc.lower()
    if "@" in host:
        raise ValueError("URLs mit Anmeldedaten sind nicht erlaubt.")

    return f"{parsed.scheme.lower()}://{host}"


def _apex_host(host: str) -> str | None:
    """
    Hilfsfunktion: Ermittelt die Hauptdomain ohne "www" (z. B. "elektro-pepi.at").
    Wichtig, um Subdomains und Hauptdomain gemeinsam zu verifizieren.
    """
    if host.startswith("www."):
        return host[4:]
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return None


def build_allowed_origins(primary_site: str, track_apex: bool, track_subdomains: bool) -> list[str]:
    """
    TECHNISCHE ERKLÄRUNG (CORS-Schutzliste):
    Generiert basierend auf den Kundeneinstellungen eine Liste erlaubter Domains.
    Wenn der Kunde z. B. wünscht, auch seine Subdomains (z. B. "shop.elektro-pepi.at")
    zu tracken, fügt diese Funktion diese automatisch der Erlaubnisliste hinzu.
    """
    primary = normalize_site_url(primary_site)
    parsed = urlparse(primary)
    host = parsed.netloc
    scheme = parsed.scheme

    origins = {primary}

    # Falls Hauptdomain (ohne www) getrackt werden soll
    if track_apex:
        apex = _apex_host(host)
        if apex and apex != host:
            origins.add(f"{scheme}://{apex}")
            origins.add(f"{scheme}://www.{apex}")

    # Falls Subdomains mit-getrackt werden sollen
    if track_subdomains:
        base = _apex_host(host) or host
        origins.add(f"{scheme}://{base}")
        origins.add(f"{scheme}://www.{base}")

    return sorted(origins)


def url_matches_allowed(url: str, allowed_origins: list[str], track_subdomains: bool) -> bool:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG (Spam-Schutz):
    Wenn PulseTrack Daten empfängt, prüft diese Funktion in Echtzeit, ob die
    getrackte Seite tatsächlich dem Kunden gehört. Dadurch wird verhindert, dass
    jemand Ihren Tracking-Code stiehlt und auf einer fremden, böswilligen Seite
    einbindet, um Ihre Statistiken zu verfälschen (Referrer-Spamming).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    page_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    for allowed in allowed_origins:
        # Exakter Abgleich der Domain
        if page_origin == allowed.lower():
            return True

        # Flexibler Abgleich für Subdomains (falls aktiviert)
        if track_subdomains:
            try:
                allowed_parsed = urlparse(allowed)
                allowed_host = allowed_parsed.netloc.lower()
                base = _apex_host(allowed_host) or allowed_host
                page_host = parsed.netloc.lower()
                if page_host == base or page_host.endswith(f".{base}"):
                    return True
            except Exception:
                continue

    return False


def parse_install_row(row) -> InstallConfig:
    """Konvertiert einen Datenbank-Eintrag der Installation in ein lesbares Python-Objekt."""
    if row is None:
        return InstallConfig(
            configured=False,
            primary_site=None,
            allowed_origins=[],
            track_apex=False,
            track_subdomains=False,
            permissive=False,
        )

    origins = json.loads(row["allowed_origins_json"] or "[]")
    return InstallConfig(
        configured=bool(row["configured"]),
        primary_site=row["primary_site"],
        allowed_origins=origins,
        track_apex=bool(row["track_apex"]),
        track_subdomains=bool(row["track_subdomains"]),
        permissive=bool(row["permissive"]),
    )


def build_integration_snippet(request_base_url: str) -> str:
    """
    KUNDENVERSTÄNDLICHE ERKLÄRUNG:
    Generiert den exakten HTML-Code-Schnipsel (Snippet), den Ihr IT-Techniker
    in den HTML-Kopf (Head) Ihrer Website kopieren muss.
    Dieser Schnipsel lädt das extrem kleine Tracking-Skript absolut unbemerkt
    und blitzschnell im Hintergrund.
    """
    base = request_base_url.rstrip("/")
    return f'<script src="{base}/tracker.js" defer></script>'
