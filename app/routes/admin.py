from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.config import settings
from app.services.tenant import create_tenant, list_tenants, update_tenant

router = APIRouter(prefix="/admin", tags=["admin"])


class TenantCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64)
    name: str = Field(min_length=2, max_length=120)
    business_name: str = Field(min_length=2, max_length=120)
    whatsapp_phone_number_id: str = Field(min_length=5, max_length=32)
    whatsapp_token: str = Field(min_length=10)
    business_context: str = ""
    business_context_file: str = ""
    assistant_owner_name: str = "Gilberto"
    personality_level: int = 4
    openai_model: str = "gpt-4o-mini"
    max_history_messages: int = 12
    plan: str = "business"
    monthly_message_limit: int | None = None
    is_active: bool = True


class TenantUpdate(BaseModel):
    slug: str | None = None
    name: str | None = None
    business_name: str | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_token: str | None = None
    business_context: str | None = None
    business_context_file: str | None = None
    assistant_owner_name: str | None = None
    personality_level: int | None = None
    openai_model: str | None = None
    max_history_messages: int | None = None
    plan: str | None = None
    monthly_message_limit: int | None = None
    is_active: bool | None = None


def _require_admin_key(x_admin_key: str | None) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY no configurada")
    if x_admin_key != settings.admin_api_key:
        raise HTTPException(status_code=401, detail="No autorizado")


@router.get("/tenants")
def get_tenants(x_admin_key: str | None = Header(default=None)) -> list[dict[str, Any]]:
    _require_admin_key(x_admin_key)
    return list_tenants()


@router.post("/tenants", status_code=201)
def post_tenant(
    payload: TenantCreate,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_key(x_admin_key)
    try:
        return create_tenant(payload.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/tenants/{tenant_id}")
def patch_tenant(
    tenant_id: int,
    payload: TenantUpdate,
    x_admin_key: str | None = Header(default=None),
) -> dict[str, Any]:
    _require_admin_key(x_admin_key)
    updated = update_tenant(tenant_id, payload.model_dump(exclude_unset=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    return updated
