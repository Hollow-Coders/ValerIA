import logging
import re
from datetime import datetime, timezone

from sqlalchemy import func

from app.database import Message, SessionLocal, Tenant
from app.models.tenant_config import TenantConfig
from app.services.conversation import get_history, save_message
from app.services.handoff_keywords import wants_human_handoff
from app.services.whatsapp import normalize_recipient_phone, send_text_message

logger = logging.getLogger("valeria")

CLOSE_COMMANDS = {"fin", "cerrar", "listo", "done", "end"}
LIST_COMMANDS = {"lista", "chats", "pendientes"}


def _get_state_model():
    from app.database import ConversationState

    return ConversationState


def phones_match(a: str, b: str) -> bool:
    if not a or not b:
        return False
    return normalize_recipient_phone(a) == normalize_recipient_phone(b)


def is_advisor_phone(tenant: TenantConfig, phone: str) -> bool:
    return bool(tenant.notify_phone) and phones_match(phone, tenant.notify_phone)


def display_phone(phone: str) -> str:
    return f"+{normalize_recipient_phone(phone)}"


def get_or_create_state(tenant_id: int, phone: str):
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        state = (
            db.query(ConversationState)
            .filter(ConversationState.tenant_id == tenant_id, ConversationState.phone == phone)
            .first()
        )
        if state:
            return state

        state = ConversationState(
            tenant_id=tenant_id,
            phone=phone,
            bot_enabled=True,
            handoff_reason="",
            assigned_advisor_phone="",
            bridge_customer_phone="",
        )
        db.add(state)
        db.commit()
        db.refresh(state)
        return state


def is_bot_enabled(tenant_id: int, phone: str) -> bool:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        state = (
            db.query(ConversationState)
            .filter(ConversationState.tenant_id == tenant_id, ConversationState.phone == phone)
            .first()
        )
        return True if state is None else state.bot_enabled


def pause_bot(
    tenant_id: int,
    phone: str,
    reason: str = "manual",
    advisor_phone: str = "",
) -> None:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        state = (
            db.query(ConversationState)
            .filter(ConversationState.tenant_id == tenant_id, ConversationState.phone == phone)
            .first()
        )
        if not state:
            state = ConversationState(
                tenant_id=tenant_id,
                phone=phone,
                bot_enabled=False,
                handoff_reason=reason,
                assigned_advisor_phone=advisor_phone,
                bridge_customer_phone="",
            )
            db.add(state)
        else:
            state.bot_enabled = False
            state.handoff_reason = reason
            if advisor_phone:
                state.assigned_advisor_phone = advisor_phone
            state.updated_at = datetime.now(timezone.utc)
        db.commit()


def resume_bot(tenant_id: int, phone: str) -> None:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        state = (
            db.query(ConversationState)
            .filter(ConversationState.tenant_id == tenant_id, ConversationState.phone == phone)
            .first()
        )
        if not state:
            return
        state.bot_enabled = True
        state.handoff_reason = ""
        state.assigned_advisor_phone = ""
        state.updated_at = datetime.now(timezone.utc)
        db.commit()


def _set_advisor_active_customer(tenant_id: int, advisor_phone: str, customer_phone: str) -> None:
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
        if not state:
            state = ConversationState(
                tenant_id=tenant_id,
                phone=advisor_phone,
                bot_enabled=True,
                handoff_reason="",
                assigned_advisor_phone="",
                bridge_customer_phone=customer_phone,
            )
            db.add(state)
        else:
            state.bridge_customer_phone = customer_phone
            state.updated_at = datetime.now(timezone.utc)
        db.commit()


def _clear_advisor_active_customer(tenant_id: int, advisor_phone: str, customer_phone: str = "") -> None:
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
        if not state:
            return
        if customer_phone and state.bridge_customer_phone and not phones_match(
            state.bridge_customer_phone, customer_phone
        ):
            return
        state.bridge_customer_phone = ""
        state.updated_at = datetime.now(timezone.utc)
        db.commit()


def get_advisor_active_customer(tenant_id: int, advisor_phone: str) -> str:
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
        return state.bridge_customer_phone if state else ""


def list_pending_for_advisor(tenant_id: int, advisor_phone: str) -> list[dict]:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        states = (
            db.query(ConversationState)
            .filter(
                ConversationState.tenant_id == tenant_id,
                ConversationState.bot_enabled.is_(False),
            )
            .order_by(ConversationState.updated_at.desc())
            .all()
        )
        pending = []
        for state in states:
            if state.assigned_advisor_phone and not phones_match(
                state.assigned_advisor_phone, advisor_phone
            ):
                continue
            if phones_match(state.phone, advisor_phone):
                continue
            pending.append(
                {
                    "phone": state.phone,
                    "phone_display": display_phone(state.phone),
                    "reason": state.handoff_reason or "",
                    "updated_at": state.updated_at,
                }
            )
        return pending


def list_conversations(tenant_id: int | None = None) -> list[dict]:
    ConversationState = _get_state_model()
    with SessionLocal() as db:
        query = (
            db.query(
                Message.tenant_id,
                Message.phone,
                func.max(Message.created_at).label("last_message_at"),
                func.max(Message.id).label("last_message_id"),
            )
            .group_by(Message.tenant_id, Message.phone)
            .order_by(func.max(Message.created_at).desc())
        )
        if tenant_id:
            query = query.filter(Message.tenant_id == tenant_id)

        rows = query.all()
        tenants = {tenant.id: tenant for tenant in db.query(Tenant).all()}
        states = {
            (state.tenant_id, state.phone): state
            for state in db.query(ConversationState).all()
        }

        conversations = []
        for row in rows:
            tenant = tenants.get(row.tenant_id)
            if not tenant:
                continue

            # No listar el chat del asesor como conversación de cliente
            if tenant.notify_phone and phones_match(row.phone, tenant.notify_phone):
                continue

            last_message = db.query(Message).filter(Message.id == row.last_message_id).first()
            state = states.get((row.tenant_id, row.phone))
            bot_enabled = True if state is None else state.bot_enabled

            conversations.append(
                {
                    "tenant_id": row.tenant_id,
                    "tenant_name": tenant.name,
                    "phone": row.phone,
                    "phone_display": display_phone(row.phone),
                    "last_message": last_message.content if last_message else "",
                    "last_role": last_message.role if last_message else "",
                    "last_message_at": row.last_message_at,
                    "bot_enabled": bot_enabled,
                    "handoff_reason": state.handoff_reason if state else "",
                    "needs_human": not bot_enabled,
                }
            )
        return conversations


def count_pending_handoffs() -> int:
    return len([item for item in list_conversations() if item["needs_human"]])


def _format_context(tenant: TenantConfig, customer_phone: str) -> str:
    history = get_history(tenant, customer_phone)
    if not history:
        return "(Sin historial todavía)"

    lines = []
    for item in history[-6:]:
        role = item.get("role", "")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if role == "user":
            label = "Cliente"
        elif role == "human":
            label = "Asesor"
        else:
            label = "ValerIA"
        lines.append(f"{label}: {content[:180]}")
    return "\n".join(lines) if lines else "(Sin historial todavía)"


def _advisor_help_text() -> str:
    return (
        "Responde aquí y se lo mando al cliente.\n"
        "Comandos:\n"
        "FIN — devolver el chat a la IA\n"
        "LISTA — ver clientes en espera"
    )


async def trigger_handoff(
    tenant: TenantConfig,
    phone: str,
    user_text: str,
    reason: str,
    notify_phone: str = "",
    customer_reply: str | None = None,
) -> str:
    advisor = (notify_phone or tenant.notify_phone or "").strip()
    pause_bot(tenant.id, phone, reason=reason, advisor_phone=advisor)

    if customer_reply is None:
        customer_reply = (
            f"Claro, te comunico con {tenant.assistant_owner_name} o alguien del equipo de "
            f"{tenant.business_name}. En un momento te atienden."
        )

    if customer_reply:
        await send_text_message(tenant, phone, customer_reply)

    if advisor:
        active = get_advisor_active_customer(tenant.id, advisor)
        pending = list_pending_for_advisor(tenant.id, advisor)

        if not active:
            _set_advisor_active_customer(tenant.id, advisor, phone)
            active_note = "Este chat quedó activo: responde aquí para hablarle."
        elif phones_match(active, phone):
            active_note = "Este chat ya estaba activo."
        else:
            active_note = (
                f"Tienes otro chat activo ({display_phone(active)}). "
                f"Escribe LISTA y el número para cambiar a este cliente."
            )

        context = _format_context(tenant, phone)
        alert = (
            f"Handoff — {tenant.business_name}\n\n"
            f"Cliente: {display_phone(phone)}\n"
            f"Pidió: {user_text[:220]}\n"
            f"Motivo: {reason}\n\n"
            f"Contexto reciente:\n{context}\n\n"
            f"{active_note}\n\n"
            f"{_advisor_help_text()}"
        )
        if len(pending) > 1:
            alert += f"\n\nClientes en espera: {len(pending)}. Escribe LISTA para verlos."

        try:
            await send_text_message(tenant, advisor, alert)
        except Exception:
            logger.exception("No se pudo notificar handoff al asesor %s", advisor)
    else:
        logger.warning(
            "Handoff sin teléfono de asesor tenant=%s phone=%s",
            tenant.slug,
            phone,
        )

    logger.info("Handoff activado tenant=%s phone=%s reason=%s", tenant.slug, phone, reason)
    return customer_reply

async def forward_customer_to_advisor(
    tenant: TenantConfig,
    customer_phone: str,
    text: str,
) -> bool:
    advisor = (tenant.notify_phone or "").strip()
    if not advisor:
        return False

    active = get_advisor_active_customer(tenant.id, advisor)
    if not active:
        _set_advisor_active_customer(tenant.id, advisor, customer_phone)
    elif not phones_match(active, customer_phone):
        # Aviso suave si el mensaje es de un chat que no es el activo
        await send_text_message(
            tenant,
            advisor,
            (
                f"Mensaje de otro cliente en espera ({display_phone(customer_phone)}):\n"
                f"{text[:500]}\n\n"
                f"Tu chat activo es {display_phone(active)}. "
                f"Escribe LISTA para cambiar."
            ),
        )
        return True

    await send_text_message(
        tenant,
        advisor,
        f"Cliente {display_phone(customer_phone)}:\n{text}",
    )
    return True


async def handle_advisor_message(
    tenant: TenantConfig,
    advisor_phone: str,
    text: str,
) -> str:
    """Procesa un mensaje del asesor. Devuelve status corto para el webhook."""
    cleaned = text.strip()
    command = cleaned.lower()

    if command in LIST_COMMANDS:
        pending = list_pending_for_advisor(tenant.id, advisor_phone)
        active = get_advisor_active_customer(tenant.id, advisor_phone)
        if not pending:
            await send_text_message(
                tenant,
                advisor_phone,
                "No hay clientes esperando asesor ahora.",
            )
            return "advisor_list_empty"

        lines = ["Clientes en espera:"]
        for idx, item in enumerate(pending, start=1):
            marker = " (activo)" if active and phones_match(active, item["phone"]) else ""
            reason = f" — {item['reason']}" if item["reason"] else ""
            lines.append(f"{idx}. {item['phone_display']}{reason}{marker}")
        lines.append("\nResponde con el número para activar ese chat.")
        await send_text_message(tenant, advisor_phone, "\n".join(lines))
        return "advisor_list"

    if command in CLOSE_COMMANDS:
        active = get_advisor_active_customer(tenant.id, advisor_phone)
        if not active:
            await send_text_message(
                tenant,
                advisor_phone,
                "No tienes un chat activo. Escribe LISTA para ver pendientes.",
            )
            return "advisor_close_none"

        resume_bot(tenant.id, active)
        _clear_advisor_active_customer(tenant.id, advisor_phone, active)

        pending = list_pending_for_advisor(tenant.id, advisor_phone)
        customer_msg = (
            f"Listo, te dejo de nuevo con ValerIA de {tenant.business_name}. "
            f"Si necesitas algo más, aquí seguimos."
        )
        await send_text_message(tenant, active, customer_msg)
        save_message(tenant, active, "assistant", customer_msg)

        advisor_msg = f"Listo. ValerIA retomó el chat con {display_phone(active)}."
        if pending:
            next_customer = pending[0]["phone"]
            _set_advisor_active_customer(tenant.id, advisor_phone, next_customer)
            advisor_msg += (
                f"\nSiguiente en espera: {display_phone(next_customer)}. "
                f"Ya quedó activo. Escribe LISTA para ver todos."
            )
        await send_text_message(tenant, advisor_phone, advisor_msg)
        return "advisor_closed"

    # Selección por número de lista
    if re.fullmatch(r"\d{1,2}", cleaned):
        pending = list_pending_for_advisor(tenant.id, advisor_phone)
        index = int(cleaned) - 1
        if 0 <= index < len(pending):
            chosen = pending[index]["phone"]
            _set_advisor_active_customer(tenant.id, advisor_phone, chosen)
            context = _format_context(tenant, chosen)
            await send_text_message(
                tenant,
                advisor_phone,
                (
                    f"Chat activo: {display_phone(chosen)}\n\n"
                    f"Contexto:\n{context}\n\n"
                    f"{_advisor_help_text()}"
                ),
            )
            return "advisor_switched"
        await send_text_message(
            tenant,
            advisor_phone,
            "Número inválido. Escribe LISTA para ver las opciones.",
        )
        return "advisor_bad_index"

    active = get_advisor_active_customer(tenant.id, advisor_phone)
    if not active:
        pending = list_pending_for_advisor(tenant.id, advisor_phone)
        if len(pending) == 1:
            active = pending[0]["phone"]
            _set_advisor_active_customer(tenant.id, advisor_phone, active)
        elif pending:
            await send_text_message(
                tenant,
                advisor_phone,
                "Tienes varios chats en espera. Escribe LISTA y el número del cliente.",
            )
            return "advisor_need_select"
        else:
            await send_text_message(
                tenant,
                advisor_phone,
                "No hay un cliente activo en handoff ahora.",
            )
            return "advisor_idle"

    # Asegurar que el bot siga pausado mientras el asesor habla
    pause_bot(tenant.id, active, reason="advisor_bridge", advisor_phone=advisor_phone)
    await send_text_message(tenant, active, cleaned)
    save_message(tenant, active, "human", cleaned)
    return "advisor_forwarded"


def should_handoff(user_text: str) -> bool:
    return wants_human_handoff(user_text)
