import logging

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from app.config import settings
from app.models.tenant_config import TenantConfig
from app.prompts import build_system_prompt
from app.services.context_retrieve import select_business_context

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
    focused_context = select_business_context(tenant.business_context, user_message)
    system_prompt = build_system_prompt(
        business_name=tenant.business_name,
        business_context=focused_context,
        personality_level=tenant.personality_level,
        assistant_owner_name=tenant.assistant_owner_name,
        is_first_message=is_first_message,
    )

    # Con contexto legal largo, menos historial y respuestas un poco más largas
    history_limit = 6 if len(tenant.business_context or "") > 20000 else tenant.max_history_messages
    trimmed_history = history[-history_limit:] if history else []

    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for item in trimmed_history:
        role = item.get("role", "user")
        content = item.get("content", "")
        if role == "human":
            role = "assistant"
        if role not in {"user", "assistant", "system"}:
            role = "user"
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_message})

    try:
        response = client.chat.completions.create(
            model=tenant.openai_model,
            messages=messages,
            temperature=0.85,
            max_tokens=220,
            presence_penalty=0.3,
            frequency_penalty=0.4,
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
    text = (reply or "Dame un segundito, te respondo en un momento.").strip()
    # Quitar negritas markdown si el modelo las cuela
    text = text.replace("**", "").replace("__", "")
    return text
