import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import init_db
from app.routes.admin import router as admin_router
from app.routes.panel import router as panel_router
from app.services.ai import generate_reply
from app.services.conversation import get_history, save_message
from app.services.handoff import (
    forward_customer_to_advisor,
    handle_advisor_message,
    is_advisor_phone,
    is_bot_enabled,
    should_handoff,
    trigger_handoff,
)
from app.services.tenant import get_tenant_by_phone_number_id
from app.services.usage import increment_usage, is_within_limit
from app.services.whatsapp import send_text_message

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("valeria")

app = FastAPI(title="ValerIA", version="0.4.0")
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
app.mount("/static", StaticFiles(directory=str(Path(__file__).resolve().parent / "static")), name="static")
app.include_router(admin_router)
app.include_router(panel_router)


@app.on_event("startup")
def on_startup() -> None:
    init_db()
    logger.info("ValerIA multi-cliente lista en puerto %s", settings.port)


@app.get("/")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "ValerIA", "mode": "multi-tenant"}


@app.get("/webhook")
async def verify_webhook(
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
) -> int:
    if hub_mode == "subscribe" and hub_verify_token == settings.whatsapp_verify_token:
        return int(hub_challenge)
    raise HTTPException(status_code=403, detail="Token de verificación inválido")


@app.post("/webhook")
async def receive_webhook(request: Request) -> dict[str, str]:
    payload = await request.json()
    logger.info("Webhook recibido")

    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        phone_number_id = value.get("metadata", {}).get("phone_number_id")
        if not phone_number_id:
            return {"status": "ignored"}

        tenant = get_tenant_by_phone_number_id(phone_number_id)
        if not tenant:
            logger.error("No hay cliente configurado para phone_number_id=%s", phone_number_id)
            return {"status": "unknown_tenant"}

        logger.info("Mensaje para tenant=%s phone_number_id=%s", tenant.slug, phone_number_id)

        messages = value.get("messages", [])
        if not messages:
            return {"status": "ignored"}

        message = messages[0]
        if message.get("type") != "text":
            # Si es el asesor, no contestar con el mensaje genérico de "solo texto"
            if is_advisor_phone(tenant, message["from"]):
                await send_text_message(
                    tenant,
                    message["from"],
                    "Por ahora el puente solo soporta texto. Manda tu respuesta en texto.",
                )
                return {"status": "advisor_unsupported_type"}
            await send_text_message(
                tenant,
                message["from"],
                "Por ahora solo leo texto, pero en un ratito te ayudo con eso.",
            )
            return {"status": "unsupported_type"}

        phone = message["from"]
        user_text = message["text"]["body"].strip()
        if not user_text:
            return {"status": "empty"}

        # Mensajes del asesor del tenant → puente WhatsApp (no IA)
        if is_advisor_phone(tenant, phone):
            status = await handle_advisor_message(tenant, phone, user_text)
            logger.info("Mensaje de asesor tenant=%s status=%s", tenant.slug, status)
            return {"status": status}

        history = get_history(tenant, phone)
        is_first_message = len(history) == 0
        save_message(tenant, phone, "user", user_text)

        # Cliente en handoff: reenviar al asesor, no responder con IA
        if not is_bot_enabled(tenant.id, phone):
            forwarded = await forward_customer_to_advisor(tenant, phone, user_text)
            logger.info(
                "Bot pausado tenant=%s phone=%s forwarded=%s",
                tenant.slug,
                phone,
                forwarded,
            )
            return {"status": "handoff_forwarded" if forwarded else "handoff_active"}

        if should_handoff(user_text):
            reply = await trigger_handoff(
                tenant,
                phone,
                user_text,
                reason="keyword",
                notify_phone=tenant.notify_phone,
            )
            save_message(tenant, phone, "assistant", reply)
            return {"status": "handoff"}

        if not is_within_limit(tenant.id, tenant.monthly_message_limit):
            reply = (
                "Va, este mes ya se alcanzó el límite de mensajes del plan. "
                "En un momento te atiende un asesor del equipo."
            )
            await trigger_handoff(
                tenant,
                phone,
                user_text,
                reason="limit",
                notify_phone=tenant.notify_phone,
                customer_reply=reply,
            )
            save_message(tenant, phone, "assistant", reply)
            logger.warning("Límite alcanzado tenant=%s", tenant.slug)
            return {"status": "limit_reached"}

        reply = generate_reply(tenant, user_text, history, is_first_message=is_first_message)
        await send_text_message(tenant, phone, reply)
        save_message(tenant, phone, "assistant", reply)
        increment_usage(tenant.id)
        logger.info("Respuesta enviada tenant=%s phone=%s", tenant.slug, phone)
        return {"status": "sent"}
    except Exception:
        logger.exception("Error procesando webhook de WhatsApp")
        return {"status": "error"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
