from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from openai import OpenAI

from app.config import settings
from app.database import Reminder, SessionLocal
from app.models.tenant_config import TenantConfig
from app.services.whatsapp import normalize_recipient_phone

logger = logging.getLogger("valeria")

REMINDER_INTENT_HINTS = (
    "recuerd",
    "recordator",
    "agenda",
    "cita",
    "avísame",
    "avisame",
    "avisa me",
    "programa",
    "anota",
)

CONFIRM_YES = {"si", "sí", "yes", "ok", "dale", "confirmo", "confirma"}
CONFIRM_NO = {"no", "cancelar", "cancela", "nel"}

LIST_REMINDER_COMMANDS = {"recordatorios", "citas", "mis citas", "mis recordatorios"}


def looks_like_reminder_request(text: str) -> bool:
    lowered = text.lower().strip()
    return any(hint in lowered for hint in REMINDER_INTENT_HINTS)


def resolve_timezone(name: str) -> ZoneInfo:
    tz_name = (name or "America/Tijuana").strip() or "America/Tijuana"
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        logger.warning("Timezone inválida o sin tzdata (%s) — usando UTC", tz_name)
        return ZoneInfo("UTC")


def local_to_utc(local_dt: datetime, tz_name: str) -> datetime:
    tz = resolve_timezone(tz_name)
    if local_dt.tzinfo is None:
        local_dt = local_dt.replace(tzinfo=tz)
    else:
        local_dt = local_dt.astimezone(tz)
    return local_dt.astimezone(timezone.utc)


def utc_to_local(utc_dt: datetime, tz_name: str) -> datetime:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    return utc_dt.astimezone(resolve_timezone(tz_name))


def format_local(utc_dt: datetime, tz_name: str) -> str:
    local = utc_to_local(utc_dt, tz_name)
    return local.strftime("%d/%m/%Y %H:%M")


def _get_state_model():
    from app.database import ConversationState

    return ConversationState


def get_reminder_draft(tenant_id: int, advisor_phone: str) -> dict | None:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        state = (
            db.query(ConversationState)
            .filter(
                ConversationState.tenant_id == tenant_id,
                ConversationState.phone == advisor_phone,
            )
            .first()
        )
        if not state or not (state.reminder_draft or "").strip():
            return None
        try:
            return json.loads(state.reminder_draft)
        except json.JSONDecodeError:
            return None


def set_reminder_draft(tenant_id: int, advisor_phone: str, draft: dict | None) -> None:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        state = (
            db.query(ConversationState)
            .filter(
                ConversationState.tenant_id == tenant_id,
                ConversationState.phone == advisor_phone,
            )
            .first()
        )
        payload = json.dumps(draft, ensure_ascii=False) if draft else ""
        if not state:
            state = ConversationState(
                tenant_id=tenant_id,
                phone=advisor_phone,
                bot_enabled=True,
                handoff_reason="",
                assigned_advisor_phone="",
                bridge_customer_phone="",
                reminder_draft=payload,
            )
            db.add(state)
        else:
            state.reminder_draft = payload
            state.updated_at = datetime.now(timezone.utc)
        db.commit()


def create_reminder(
    tenant_id: int,
    advisor_phone: str,
    remind_at_utc: datetime,
    note: str,
    customer_name: str = "",
    customer_phone: str = "",
) -> Reminder:
    with SessionLocal() as db:
        reminder = Reminder(
            tenant_id=tenant_id,
            advisor_phone=normalize_recipient_phone(advisor_phone),
            customer_phone=normalize_recipient_phone(customer_phone) if customer_phone else "",
            customer_name=(customer_name or "").strip()[:120],
            note=(note or "").strip(),
            remind_at=remind_at_utc,
            status="pending",
        )
        db.add(reminder)
        db.commit()
        db.refresh(reminder)
        # Detach values we need
        db.expunge(reminder)
        return reminder


def list_pending_reminders(tenant_id: int, advisor_phone: str = "") -> list[dict]:
    with SessionLocal() as db:
        query = (
            db.query(Reminder)
            .filter(Reminder.tenant_id == tenant_id, Reminder.status == "pending")
            .order_by(Reminder.remind_at.asc())
        )
        rows = query.all()
        items = []
        for row in rows:
            if advisor_phone and normalize_recipient_phone(advisor_phone) != normalize_recipient_phone(
                row.advisor_phone
            ):
                # Still show if advisor_phone empty on old rows? keep filter
                continue
            items.append(
                {
                    "id": row.id,
                    "note": row.note,
                    "customer_name": row.customer_name,
                    "customer_phone": row.customer_phone,
                    "remind_at": row.remind_at,
                    "status": row.status,
                }
            )
        return items


def cancel_reminder(tenant_id: int, reminder_id: int, advisor_phone: str = "") -> bool:
    with SessionLocal() as db:
        row = (
            db.query(Reminder)
            .filter(Reminder.id == reminder_id, Reminder.tenant_id == tenant_id)
            .first()
        )
        if not row or row.status != "pending":
            return False
        if advisor_phone and normalize_recipient_phone(advisor_phone) != normalize_recipient_phone(
            row.advisor_phone
        ):
            return False
        row.status = "cancelled"
        db.commit()
        return True


def fetch_due_reminders(limit: int = 50) -> list[Reminder]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        rows = (
            db.query(Reminder)
            .filter(Reminder.status == "pending")
            .order_by(Reminder.remind_at.asc())
            .limit(200)
            .all()
        )
        due: list[Reminder] = []
        for row in rows:
            remind_at = row.remind_at
            if remind_at is None:
                continue
            if remind_at.tzinfo is None:
                remind_at = remind_at.replace(tzinfo=timezone.utc)
            if remind_at <= now:
                db.expunge(row)
                due.append(row)
            if len(due) >= limit:
                break
        return due


def mark_reminder_sent(reminder_id: int) -> None:
    with SessionLocal() as db:
        row = db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if not row:
            return
        row.status = "sent"
        row.sent_at = datetime.now(timezone.utc)
        db.commit()


def mark_reminder_failed(reminder_id: int) -> None:
    """Deja pendiente para reintento; solo logueamos fuera."""
    logger.warning("Falló envío de recordatorio id=%s — se reintentará", reminder_id)


def parse_reminder_with_ai(tenant: TenantConfig, text: str) -> dict | None:
    """Devuelve draft dict o None si no es recordatorio / no se pudo parsear."""
    if not settings.openai_api_key:
        return _parse_reminder_fallback(tenant, text)

    tz = tenant.timezone or "America/Tijuana"
    now_local = datetime.now(resolve_timezone(tz))
    client = OpenAI(api_key=settings.openai_api_key)

    system = (
        "Eres un parser de recordatorios para asesores de WhatsApp. "
        "Responde SOLO JSON válido, sin markdown.\n"
        "El recordatorio es SOLO para el asesor (nunca para el cliente).\n"
        f"Zona horaria del negocio: {tz}\n"
        f"Fecha/hora actual local: {now_local.isoformat()}\n"
        "Schema:\n"
        "{"
        '"is_reminder": boolean, '
        '"datetime_local": "YYYY-MM-DDTHH:MM:SS" | null, '
        '"customer_name": string, '
        '"customer_phone": string, '
        '"note": string, '
        '"error": string'
        "}\n"
        "Si el mensaje no pide crear un recordatorio/cita, is_reminder=false.\n"
        "Si falta fecha u hora, is_reminder=true y error explicando qué falta.\n"
        "datetime_local debe estar en la zona del negocio."
    )

    try:
        response = client.chat.completions.create(
            model=tenant.openai_model or settings.openai_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
            max_tokens=250,
        )
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        data = json.loads(raw)
    except Exception:
        logger.exception("No se pudo parsear recordatorio con IA")
        return _parse_reminder_fallback(tenant, text)

    if not data.get("is_reminder"):
        return None

    if data.get("error") and not data.get("datetime_local"):
        return {"error": str(data.get("error"))}

    dt_raw = data.get("datetime_local")
    if not dt_raw:
        return {"error": "Necesito fecha y hora (ej. mañana a las 10:00)."}

    try:
        local_dt = datetime.fromisoformat(str(dt_raw).replace("Z", ""))
        if local_dt.tzinfo is not None:
            local_dt = local_dt.replace(tzinfo=None)
        remind_at = local_to_utc(local_dt, tz)
    except ValueError:
        return {"error": "No entendí la fecha/hora. Prueba: mañana 10:00 cita con María."}

    if remind_at <= datetime.now(timezone.utc) - timedelta(minutes=1):
        return {"error": "Esa fecha/hora ya pasó. Dame una hora futura."}

    note = (data.get("note") or text).strip()
    return {
        "remind_at_utc": remind_at.isoformat(),
        "customer_name": (data.get("customer_name") or "").strip(),
        "customer_phone": normalize_recipient_phone(str(data.get("customer_phone") or "")),
        "note": note,
    }


def _parse_reminder_fallback(tenant: TenantConfig, text: str) -> dict | None:
    if not looks_like_reminder_request(text):
        return None

    tz = tenant.timezone or "America/Tijuana"
    now = datetime.now(resolve_timezone(tz))
    lowered = text.lower()

    day = now.date()
    if "pasado mañana" in lowered or "pasado manana" in lowered:
        day = (now + timedelta(days=2)).date()
    elif "mañana" in lowered or "manana" in lowered:
        day = (now + timedelta(days=1)).date()

    time_match = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", lowered)
    if not time_match:
        return {"error": "Dime la hora, por ejemplo: mañana 10:00 cita con María."}

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    ampm = time_match.group(3)
    if ampm == "pm" and hour < 12:
        hour += 12
    if ampm == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return {"error": "Hora inválida."}

    local_dt = datetime(day.year, day.month, day.day, hour, minute)
    remind_at = local_to_utc(local_dt, tz)
    if remind_at <= datetime.now(timezone.utc):
        return {"error": "Esa hora ya pasó. Usa una hora futura."}

    return {
        "remind_at_utc": remind_at.isoformat(),
        "customer_name": "",
        "customer_phone": "",
        "note": text.strip(),
    }


def draft_confirmation_message(tenant: TenantConfig, draft: dict) -> str:
    remind_at = datetime.fromisoformat(draft["remind_at_utc"])
    when = format_local(remind_at, tenant.timezone or "America/Tijuana")
    lines = [
        "¿Lo dejo así? (solo te aviso a ti, no al cliente)",
        f"Cuándo: {when} ({tenant.timezone or 'America/Tijuana'})",
    ]
    if draft.get("customer_name"):
        lines.append(f"Cliente: {draft['customer_name']}")
    if draft.get("customer_phone"):
        lines.append(f"Tel: +{draft['customer_phone']}")
    lines.append(f"Nota: {draft.get('note', '')[:300]}")
    lines.append("\nResponde SÍ para confirmar o NO para cancelar.")
    return "\n".join(lines)


def format_reminder_list(tenant: TenantConfig, items: list[dict]) -> str:
    if not items:
        return "No tienes recordatorios pendientes."
    lines = ["Tus recordatorios pendientes:"]
    for item in items:
        when = format_local(item["remind_at"], tenant.timezone or "America/Tijuana")
        who = item.get("customer_name") or item.get("customer_phone") or "—"
        lines.append(f"#{item['id']} · {when} · {who}\n  {item.get('note', '')[:160]}")
    lines.append("\nPara cancelar: CANCELA 3 (usa el #)")
    return "\n".join(lines)


def build_due_message(tenant: TenantConfig, reminder: Reminder) -> str:
    when = format_local(reminder.remind_at, tenant.timezone or "America/Tijuana")
    lines = [
        f"Recordatorio — {tenant.business_name}",
        f"Hora: {when}",
    ]
    if reminder.customer_name:
        lines.append(f"Cliente: {reminder.customer_name}")
    if reminder.customer_phone:
        lines.append(f"Tel: +{normalize_recipient_phone(reminder.customer_phone)}")
    if reminder.note:
        lines.append(f"Detalle: {reminder.note}")
    return "\n".join(lines)
