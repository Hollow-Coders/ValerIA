from app.database import Message, SessionLocal
from app.models.tenant_config import TenantConfig


def save_message(tenant: TenantConfig, phone: str, role: str, content: str) -> None:
    with SessionLocal() as db:
        db.add(
            Message(
                tenant_id=tenant.id,
                phone=phone,
                role=role,
                content=content,
            )
        )
        db.commit()


def get_history(tenant: TenantConfig, phone: str) -> list[dict[str, str]]:
    with SessionLocal() as db:
        rows = (
            db.query(Message)
            .filter(Message.tenant_id == tenant.id, Message.phone == phone)
            .order_by(Message.id.desc())
            .limit(tenant.max_history_messages)
            .all()
        )

    rows.reverse()
    return [{"role": row.role, "content": row.content} for row in rows]
