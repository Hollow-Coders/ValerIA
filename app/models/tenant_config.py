from dataclasses import dataclass
from pathlib import Path


@dataclass
class TenantConfig:
    id: int
    slug: str
    business_name: str
    business_context: str
    assistant_owner_name: str
    personality_level: int
    whatsapp_token: str
    whatsapp_phone_number_id: str
    openai_model: str
    max_history_messages: int
    plan: str
    monthly_message_limit: int
    notify_phone: str = ""


def resolve_business_context(
    business_context: str,
    business_context_file: str,
    base_dir: Path,
) -> str:
    if business_context_file:
        path = Path(business_context_file)
        if not path.is_absolute():
            path = base_dir / path
        if path.exists():
            return path.read_text(encoding="utf-8").strip()
    return business_context.strip()
