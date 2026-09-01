from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    whatsapp_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = "valeria_webhook_secret"

    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    business_name: str = "Mi Negocio"
    business_context: str = "Atiendes clientes por WhatsApp de forma amable y clara."
    business_context_file: str = ""
    assistant_owner_name: str = "Gilberto"
    personality_level: int = 3
    max_history_messages: int = 12
    admin_api_key: str = ""
    session_secret_key: str = "valeria-session-secret-change-me"

    port: int = 8000
    database_url: str = "sqlite:///./valeria.db"

    def resolved_business_context(self) -> str:
        if self.business_context_file:
            path = Path(self.business_context_file)
            if not path.is_absolute():
                path = Path(__file__).resolve().parent.parent / path
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        return self.business_context


settings = Settings()
