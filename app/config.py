# Installations- und Tracking-Konfiguration
#
# Datum: 28.05.2026 | Version: 2.0

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlparse

from pydantic import ConfigDict, SecretStr, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ANALYTICS_SALT_SECRET: SecretStr
    ANALYTICS_DB_PATH: str = "analytics.db"
    
    # Stripe Configuration
    STRIPE_SECRET_KEY: SecretStr
    STRIPE_PUBLISHABLE_KEY: str = "pk_test_mock"
    STRIPE_WEBHOOK_SECRET: SecretStr
    STRIPE_PRICE_STARTER: str = "price_starter"
    STRIPE_PRICE_BUSINESS: str = "price_business"
    STRIPE_PRICE_ENTERPRISE: str = "price_enterprise"

    # SMTP Configuration
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
        if v.get_secret_value() in ("change-me-in-production", "pulsetrack-fallback-secret"):
            raise ValueError("ANALYTICS_SALT_SECRET must be changed in production!")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


@dataclass
class InstallConfig:
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
    return settings.ANALYTICS_DB_PATH



def normalize_site_url(raw: str) -> str:
    """Wandelt eine Nutzereingabe in eine kanonische Origin (Schema + Host) um."""
    value = raw.strip()
    if not value:
        raise ValueError("Bitte eine Website-URL eingeben.")

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
    """Liefert die Root-Domain ohne www (z. B. elektropepi.at)."""
    if host.startswith("www."):
        return host[4:]
    parts = host.split(".")
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return None


def build_allowed_origins(primary_site: str, track_apex: bool, track_subdomains: bool) -> list[str]:
    """Erzeugt die erlaubten Browser-Origins aus der Setup-Eingabe."""
    primary = normalize_site_url(primary_site)
    parsed = urlparse(primary)
    host = parsed.netloc
    scheme = parsed.scheme

    origins = {primary}

    if track_apex:
        apex = _apex_host(host)
        if apex and apex != host:
            origins.add(f"{scheme}://{apex}")
            origins.add(f"{scheme}://www.{apex}")

    if track_subdomains:
        base = _apex_host(host) or host
        origins.add(f"{scheme}://{base}")
        origins.add(f"{scheme}://www.{base}")

    return sorted(origins)


def url_matches_allowed(url: str, allowed_origins: list[str], track_subdomains: bool) -> bool:
    """Prüft, ob eine getrackte Seiten-URL zu den konfigurierten Origins passt."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False

    page_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"

    for allowed in allowed_origins:
        if page_origin == allowed.lower():
            return True

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
    base = request_base_url.rstrip("/")
    return f'<script src="{base}/tracker.js" defer></script>'
