from pathlib import Path

from app.config import settings
from app.database import PROJECT_ROOT, SessionLocal, Tenant
from app.models.tenant_config import TenantConfig, resolve_business_context
from app.services.plans import get_plan_limit
from app.services.usage import get_tenant_usage_summary


def _to_config(tenant: Tenant) -> TenantConfig:
    return TenantConfig(
        id=tenant.id,
        slug=tenant.slug,
        business_name=tenant.business_name,
        business_context=resolve_business_context(
            tenant.business_context,
            tenant.business_context_file,
            PROJECT_ROOT,
        ),
        assistant_owner_name=tenant.assistant_owner_name,
        personality_level=tenant.personality_level,
        whatsapp_token=tenant.whatsapp_token,
        whatsapp_phone_number_id=tenant.whatsapp_phone_number_id,
        openai_model=tenant.openai_model or settings.openai_model,
        max_history_messages=tenant.max_history_messages or settings.max_history_messages,
        plan=tenant.plan,
        monthly_message_limit=tenant.monthly_message_limit,
        notify_phone=tenant.notify_phone or "",
    )


def get_tenant_by_phone_number_id(phone_number_id: str) -> TenantConfig | None:
    with SessionLocal() as db:
        tenant = (
            db.query(Tenant)
            .filter(
                Tenant.whatsapp_phone_number_id == phone_number_id,
                Tenant.is_active.is_(True),
            )
            .first()
        )
        if not tenant:
            return None
        return _to_config(tenant)


def get_tenant_config_by_id(tenant_id: int) -> TenantConfig | None:
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return None
        return _to_config(tenant)


def get_tenant_by_id(tenant_id: int) -> Tenant | None:
    with SessionLocal() as db:
        return db.query(Tenant).filter(Tenant.id == tenant_id).first()


def list_tenants() -> list[dict]:
    with SessionLocal() as db:
        tenants = db.query(Tenant).order_by(Tenant.id).all()
        result = []
        for tenant in tenants:
            summary = get_tenant_usage_summary(tenant)
            result.append(
                {
                    "id": tenant.id,
                    "slug": tenant.slug,
                    "name": tenant.name,
                    "business_name": tenant.business_name,
                    "assistant_owner_name": tenant.assistant_owner_name,
                    "personality_level": tenant.personality_level,
                    "whatsapp_phone_number_id": tenant.whatsapp_phone_number_id,
                    "openai_model": tenant.openai_model,
                    "max_history_messages": tenant.max_history_messages,
                    "is_active": tenant.is_active,
                    "has_context_file": bool(tenant.business_context_file),
                    "plan": tenant.plan,
                    "monthly_message_limit": tenant.monthly_message_limit,
                    "usage": summary,
                }
            )
        return result


def create_tenant(data: dict) -> dict:
    plan = data.get("plan", "business")
    monthly_limit = data.get("monthly_message_limit") or get_plan_limit(plan)

    with SessionLocal() as db:
        tenant = Tenant(
            slug=data["slug"],
            name=data["name"],
            business_name=data["business_name"],
            business_context=data.get("business_context", ""),
            business_context_file=data.get("business_context_file", ""),
            assistant_owner_name=data.get("assistant_owner_name", "Gilberto"),
            personality_level=data.get("personality_level", 4),
            whatsapp_phone_number_id=data["whatsapp_phone_number_id"],
            whatsapp_token=data["whatsapp_token"],
            openai_model=data.get("openai_model", settings.openai_model),
            max_history_messages=data.get("max_history_messages", settings.max_history_messages),
            plan=plan,
            monthly_message_limit=monthly_limit,
            notify_phone=data.get("notify_phone", ""),
            is_active=data.get("is_active", True),
        )
        db.add(tenant)
        db.commit()
        db.refresh(tenant)
        return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name}


def update_tenant(tenant_id: int, data: dict) -> dict | None:
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
        if not tenant:
            return None

        for field in (
            "slug",
            "name",
            "business_name",
            "business_context",
            "business_context_file",
            "assistant_owner_name",
            "personality_level",
            "whatsapp_phone_number_id",
            "whatsapp_token",
            "openai_model",
            "max_history_messages",
            "plan",
            "monthly_message_limit",
            "notify_phone",
            "is_active",
        ):
            if field in data and data[field] is not None:
                setattr(tenant, field, data[field])

        if "plan" in data and data["plan"] and "monthly_message_limit" not in data:
            tenant.monthly_message_limit = get_plan_limit(data["plan"])

        db.commit()
        db.refresh(tenant)
        return {"id": tenant.id, "slug": tenant.slug, "name": tenant.name, "is_active": tenant.is_active}
