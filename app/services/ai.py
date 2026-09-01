import logging

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from app.config import settings
from app.models.tenant_config import TenantConfig
from app.prompts import build_system_prompt

logger = logging.getLogger("valeria")


def generate_reply(
    tenant: TenantConfig,
    user_message: str,
    history: list[dict[str, str]],
    is_first_message: bool = False,
) -> str:
    if not settings.openai_api_key:
        return "Ahorita no puedo conectarme con la IA. En un momento te atiende una persona."

    client = OpenAI(api_key=settings.openai_api_key)
    system_prompt = build_system_prompt(
        business_name=tenant.business_name,
        business_context=tenant.business_context,
        personality_level=tenant.personality_level,
        assistant_owner_name=tenant.assistant_owner_name,
        is_first_message=is_first_message,
    )

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=tenant.openai_model,
            messages=messages,
            temperature=0.92,
            max_tokens=220,
        )
    except RateLimitError:
        logger.error("OpenAI sin créditos o límite alcanzado tenant=%s", tenant.slug)
        return "Va, ahorita tengo un detallito técnico. En un momento te atiende una persona."
    except APIConnectionError:
        logger.error("No se pudo conectar con OpenAI tenant=%s", tenant.slug)
        return "Se me cayó la conexión un momento. ¿Me repites en un ratito?"
    except APIStatusError as exc:
        logger.error("Error de OpenAI tenant=%s: %s", tenant.slug, exc.message)
        return "Ahorita no puedo procesar tu mensaje. Te paso con alguien del equipo."

    reply = response.choices[0].message.content
    return (reply or "Dame un segundito, te respondo en un momento.").strip()
