from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import httpx
from itsdangerous import URLSafeSerializer

from app.config import settings
from app.database import SessionLocal, Tenant
from app.services.reminders import format_local, utc_to_local

logger = logging.getLogger("valeria")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/userinfo.email"


def google_oauth_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def redirect_uri() -> str:
    if settings.google_redirect_uri:
        return settings.google_redirect_uri.rstrip("/")
    base = (settings.public_base_url or "").rstrip("/")
    if base:
        return f"{base}/panel/google/callback"
    return "http://localhost:8000/panel/google/callback"


def _state_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(settings.session_secret_key, salt="google-oauth")


def build_auth_url(tenant_id: int) -> str:
    if not google_oauth_configured():
        raise RuntimeError("Google OAuth no configurado (GOOGLE_CLIENT_ID / SECRET)")

    state = _state_serializer().dumps({"tenant_id": tenant_id})
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": redirect_uri(),
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


def parse_oauth_state(state: str) -> int:
    data = _state_serializer().loads(state)
    return int(data["tenant_id"])


def is_google_connected(tenant_id: int) -> bool:
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return False
        return bool((tenant.google_refresh_token or "").strip() or (tenant.google_access_token or "").strip())


def get_google_status(tenant_id: int) -> dict:
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return {"connected": False, "email": "", "calendar_id": "primary"}
        return {
            "connected": bool((tenant.google_refresh_token or "").strip()),
            "email": tenant.google_connected_email or "",
            "calendar_id": tenant.google_calendar_id or "primary",
        }


async def exchange_code_and_store(tenant_id: int, code: str) -> dict:
    if not google_oauth_configured():
        raise RuntimeError("Google OAuth no configurado")

    async with httpx.AsyncClient(timeout=30.0) as client:
        token_resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "code": code,
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "redirect_uri": redirect_uri(),
                "grant_type": "authorization_code",
            },
        )
        if token_resp.is_error:
            logger.error("Google token exchange failed: %s", token_resp.text)
            token_resp.raise_for_status()
        tokens = token_resp.json()

        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")
        expires_in = int(tokens.get("expires_in", 3600))
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

        email = ""
        if access_token:
            info_resp = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if info_resp.is_success:
                email = (info_resp.json() or {}).get("email", "") or ""

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            raise RuntimeError("Tenant no encontrado")
        tenant.google_access_token = access_token
        if refresh_token:
            tenant.google_refresh_token = refresh_token
        tenant.google_token_expiry = expiry
        tenant.google_connected_email = email
        if not (tenant.google_calendar_id or "").strip():
            tenant.google_calendar_id = "primary"
        db.commit()

    return {"email": email, "tenant_id": tenant_id}


def disconnect_google(tenant_id: int) -> None:
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return
        tenant.google_refresh_token = ""
        tenant.google_access_token = ""
        tenant.google_token_expiry = None
        tenant.google_connected_email = ""
        db.commit()


async def _ensure_access_token(tenant_id: int) -> str | None:
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return None

        access = (tenant.google_access_token or "").strip()
        refresh = (tenant.google_refresh_token or "").strip()
        expiry = tenant.google_token_expiry
        if expiry and expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        still_valid = access and expiry and expiry > datetime.now(timezone.utc) + timedelta(minutes=1)
        if still_valid:
            return access

        if not refresh or not google_oauth_configured():
            return access or None

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        if resp.is_error:
            logger.error("Google refresh failed tenant=%s body=%s", tenant_id, resp.text)
            return None
        data = resp.json()
        access = data.get("access_token", "")
        expires_in = int(data.get("expires_in", 3600))
        expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return None
        tenant.google_access_token = access
        tenant.google_token_expiry = expiry
        db.commit()
    return access


async def create_calendar_event_for_reminder(
    tenant_id: int,
    *,
    title: str,
    note: str,
    remind_at_utc: datetime,
    timezone_name: str,
    duration_minutes: int = 60,
) -> str | None:
    """Crea evento en Google Calendar. Devuelve event_id o None."""
    if not is_google_connected(tenant_id):
        return None

    access = await _ensure_access_token(tenant_id)
    if not access:
        logger.warning("Sin access token Google para tenant=%s", tenant_id)
        return None

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return None
        calendar_id = (tenant.google_calendar_id or "primary").strip() or "primary"
        tz_name = timezone_name or tenant.timezone or "America/Tijuana"

    if remind_at_utc.tzinfo is None:
        remind_at_utc = remind_at_utc.replace(tzinfo=timezone.utc)

    start_local = utc_to_local(remind_at_utc, tz_name)
    end_local = start_local + timedelta(minutes=duration_minutes)

    body = {
        "summary": title[:200] or "Cita ValerIA",
        "description": (note or "")[:2000],
        "start": {
            "dateTime": start_local.replace(tzinfo=None).isoformat(timespec="seconds"),
            "timeZone": tz_name,
        },
        "end": {
            "dateTime": end_local.replace(tzinfo=None).isoformat(timespec="seconds"),
            "timeZone": tz_name,
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 30},
                {"method": "popup", "minutes": 10},
            ],
        },
    }

    from urllib.parse import quote

    url = f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events"

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {access}",
                "Content-Type": "application/json",
            },
            json=body,
        )
        if resp.is_error:
            logger.error(
                "Google Calendar create event failed tenant=%s status=%s body=%s",
                tenant_id,
                resp.status_code,
                resp.text,
            )
            return None
        event_id = (resp.json() or {}).get("id", "")
        logger.info(
            "Evento Google creado tenant=%s event=%s when=%s",
            tenant_id,
            event_id,
            format_local(remind_at_utc, tz_name),
        )
        return event_id or None


def set_reminder_google_event(reminder_id: int, event_id: str) -> None:
    from app.database import Reminder

    with SessionLocal() as db:
        row = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if not row:
            return
        row.google_event_id = event_id
        db.commit()
