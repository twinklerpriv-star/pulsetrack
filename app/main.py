# FastAPI Hauptanwendung
#
# Datum: 27.05.2026 | Version: 1.2


import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app import database
from app.config import build_integration_snippet

logger = logging.getLogger("analytics_main")
logging.basicConfig(level=logging.INFO)


def _cors_origins_for_config() -> list[str]:
    try:
        config = database.get_install_config()
    except Exception:
        return []
    if config.permissive:
        return ["*"]
    if config.allowed_origins:
        return config.allowed_origins
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        database.init_db()
        logger.info("Datenbank erfolgreich beim Start vorbereitet.")
    except Exception as e:
        logger.critical(f"Kritischer Fehler beim Anwendungsstart: {e}")
    yield


app = FastAPI(
    title="PulseTrack",
    description="Minimalistisches, datenschutzkonformes Web-Analytics-System.",
    version="0.2.0",
    lifespan=lifespan,
)

class DynamicCORSMiddleware(CORSMiddleware):
    """Lädt erlaubte Origins bei jedem Request neu (Setup ohne Neustart)."""

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            origins = _cors_origins_for_config()
            self.allow_origins = origins
            self.allow_all_origins = "*" in origins
        await super().__call__(scope, receive, send)


app.add_middleware(
    DynamicCORSMiddleware,
    allow_origins=[],
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


class HitPayload(BaseModel):
    url: str
    referrer: str | None = None


def _request_base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _setup_context(request: Request, **extra):
    config = database.get_install_config()
    return {
        "request": request,
        "primary_site": config.primary_site or "",
        "track_apex": config.track_apex,
        "track_subdomains": config.track_subdomains,
        "show_skip": os.environ.get("PULSETRACK_ALLOW_PERMISSIVE_SETUP", "").lower() in ("1", "true", "yes"),
        **extra,
    }


@app.post("/api/hit", status_code=202)
async def capture_hit(payload: HitPayload, request: Request):
    if not database.is_url_allowed_for_tracking(payload.url):
        raise HTTPException(status_code=403, detail="URL is not allowed by the current tracking configuration.")

    user_agent = request.headers.get("user-agent")

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_ip = forwarded_for.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "127.0.0.1"

    try:
        database.save_hit(
            url=payload.url,
            referrer=payload.referrer,
            user_agent=user_agent,
            client_ip=client_ip,
        )
        return {"status": "accepted"}
    except Exception as e:
        logger.error(f"Fehler bei der Hit-Erfassung: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during event logging.") from e


@app.get("/tracker.js")
async def get_tracker():
    tracker_path = os.path.join(os.path.dirname(__file__), "tracker.js")
    if os.path.exists(tracker_path):
        return FileResponse(tracker_path, media_type="application/javascript")
    raise HTTPException(status_code=404, detail="Tracker script not found.")


@app.get("/setup", response_class=HTMLResponse)
async def setup_form(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="setup.html",
        context=_setup_context(request),
    )


@app.post("/setup")
async def setup_submit(
    request: Request,
    primary_site: str = Form(""),
    track_apex: str | None = Form(None),
    track_subdomains: str | None = Form(None),
    permissive: str | None = Form(None),
):
    show_skip = os.environ.get("PULSETRACK_ALLOW_PERMISSIVE_SETUP", "").lower() in ("1", "true", "yes")

    if permissive and show_skip:
        database.configure_permissive_dev()
        return RedirectResponse(url="/?configured=1", status_code=303)

    try:
        database.configure_from_setup(
            primary_site=primary_site,
            track_apex=track_apex == "1",
            track_subdomains=track_subdomains == "1",
        )
    except ValueError as exc:
        return templates.TemplateResponse(
            request=request,
            name="setup.html",
            context=_setup_context(
                request,
                error=str(exc),
                primary_site=primary_site,
                track_apex=track_apex == "1",
                track_subdomains=track_subdomains == "1",
            ),
        )

    return RedirectResponse(url="/?configured=1", status_code=303)


@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    config = database.get_install_config()
    if not config.is_active:
        return RedirectResponse(url="/setup", status_code=303)

    try:
        summary = database.get_analytics_summary()
        setup_done = request.query_params.get("configured") == "1"
        return templates.TemplateResponse(
            request=request,
            name="dashboard.html",
            context={
                "summary": summary,
                "install_config": config,
                "integration_snippet": build_integration_snippet(_request_base_url(request)),
                "setup_done": setup_done,
            },
        )
    except Exception as e:
        logger.error(f"Fehler beim Rendern des Dashboards: {e}")
        raise HTTPException(status_code=500, detail="Error generating dashboard view.") from e
