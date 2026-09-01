import logging

import httpx

from app.models.tenant_config import TenantConfig

logger = logging.getLogger("valeria")
GRAPH_API = "https://graph.facebook.com/v21.0"


def normalize_recipient_phone(phone: str) -> str:
    digits = phone.lstrip("+").strip()
    if digits.startswith("521") and len(digits) == 13:
        return "52" + digits[3:]
    return digits


async def send_text_message(tenant: TenantConfig, to_phone: str, text: str) -> None:
    if not tenant.whatsapp_token or not tenant.whatsapp_phone_number_id:
        logger.error("Faltan credenciales de WhatsApp para tenant %s", tenant.slug)
        return

    recipient = normalize_recipient_phone(to_phone)
    url = f"{GRAPH_API}/{tenant.whatsapp_phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {tenant.whatsapp_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": text},
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, headers=headers, json=payload)
        if response.is_error:
            logger.error(
                "WhatsApp API error tenant=%s status=%s body=%s",
                tenant.slug,
                response.status_code,
                response.text,
            )
        response.raise_for_status()
