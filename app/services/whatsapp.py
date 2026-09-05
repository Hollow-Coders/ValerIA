import logging

import httpx

from app.models.tenant_config import TenantConfig

logger = logging.getLogger("valeria")
GRAPH_API = "https://graph.facebook.com/v21.0"


def _digits_only(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def normalize_recipient_phone(phone: str) -> str:
    """Forma canónica para comparar números (México 521… → 52…)."""
    digits = _digits_only(phone)
    if digits.startswith("521") and len(digits) == 13:
        return "52" + digits[3:]
    return digits


def recipient_candidates(phone: str) -> list[str]:
    """
    Meta a veces tiene el número en allowlist como 52… y a veces como 521…
    Probamos ambos formatos para móviles de México.
    """
    digits = _digits_only(phone)
    if not digits:
        return []

    candidates = [digits]
    if digits.startswith("521") and len(digits) == 13:
        alt = "52" + digits[3:]
        if alt not in candidates:
            candidates.append(alt)
    elif digits.startswith("52") and len(digits) == 12:
        alt = "521" + digits[2:]
        if alt not in candidates:
            candidates.append(alt)
    return candidates


async def send_text_message(tenant: TenantConfig, to_phone: str, text: str) -> None:
    if not tenant.whatsapp_token or not tenant.whatsapp_phone_number_id:
        logger.error("Faltan credenciales de WhatsApp para tenant %s", tenant.slug)
        return

    candidates = recipient_candidates(to_phone)
    if not candidates:
        logger.error("Teléfono destino vacío tenant=%s", tenant.slug)
        return

    url = f"{GRAPH_API}/{tenant.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {tenant.whatsapp_token}",
        "Content-Type": "application/json",
    }

    last_response: httpx.Response | None = None
    async with httpx.AsyncClient(timeout=20.0) as client:
        for recipient in candidates:
            payload = {
                "messaging_product": "whatsapp",
                "to": recipient,
                "type": "text",
                "text": {"body": text},
            }
            response = await client.post(url, headers=headers, json=payload)
            if response.is_success:
                if recipient != candidates[0]:
                    logger.info(
                        "WhatsApp OK con formato alterno tenant=%s to=%s",
                        tenant.slug,
                        recipient,
                    )
                return

            last_response = response
            body = response.text
            is_allowlist = response.status_code == 400 and "131030" in body
            if is_allowlist and recipient != candidates[-1]:
                logger.warning(
                    "WhatsApp 131030 tenant=%s to=%s — reintentando otro formato MX",
                    tenant.slug,
                    recipient,
                )
                continue

            logger.error(
                "WhatsApp API error tenant=%s status=%s to=%s body=%s",
                tenant.slug,
                response.status_code,
                recipient,
                body,
            )
            response.raise_for_status()

    if last_response is not None:
        last_response.raise_for_status()
