from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    business_name: Mapped[str] = mapped_column(String(120))
    business_context: Mapped[str] = mapped_column(Text, default="")
    business_context_file: Mapped[str] = mapped_column(String(255), default="")
    assistant_owner_name: Mapped[str] = mapped_column(String(80), default="Gilberto")
    personality_level: Mapped[int] = mapped_column(Integer, default=4)
    whatsapp_phone_number_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    whatsapp_token: Mapped[str] = mapped_column(Text)
    openai_model: Mapped[str] = mapped_column(String(64), default="gpt-4o-mini")
    max_history_messages: Mapped[int] = mapped_column(Integer, default=12)
    plan: Mapped[str] = mapped_column(String(32), default="business")
    monthly_message_limit: Mapped[int] = mapped_column(Integer, default=2500)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    phone: Mapped[str] = mapped_column(String(32), index=True)
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )


class TenantUsage(Base):
    __tablename__ = "tenant_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True)
    period: Mapped[str] = mapped_column(String(7), index=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)


def _database_url() -> str:
    url = settings.database_url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def _create_engine():
    url = _database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, connect_args=connect_args)


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _migrate_tenants_table() -> None:
    inspector = inspect(engine)
    if "tenants" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("tenants")}
    with engine.begin() as conn:
        if "plan" not in columns:
            conn.execute(text("ALTER TABLE tenants ADD COLUMN plan VARCHAR(32) DEFAULT 'business'"))
        if "monthly_message_limit" not in columns:
            conn.execute(text("ALTER TABLE tenants ADD COLUMN monthly_message_limit INTEGER DEFAULT 2500"))


def _migrate_messages_table() -> None:
    inspector = inspect(engine)
    if "messages" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("messages")}
    if "tenant_id" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE messages ADD COLUMN tenant_id INTEGER"))
            default_tenant = conn.execute(text("SELECT id FROM tenants ORDER BY id LIMIT 1")).fetchone()
            if default_tenant:
                conn.execute(
                    text("UPDATE messages SET tenant_id = :tenant_id WHERE tenant_id IS NULL"),
                    {"tenant_id": default_tenant[0]},
                )


def seed_default_tenant_from_env() -> None:
    if not settings.whatsapp_phone_number_id or not settings.whatsapp_token:
        return

    with SessionLocal() as db:
        existing = (
            db.query(Tenant)
            .filter(Tenant.whatsapp_phone_number_id == settings.whatsapp_phone_number_id)
            .first()
        )
        if existing:
            return

        slug = settings.business_name.lower().replace(" ", "-")[:64] or "cliente-default"
        tenant = Tenant(
            slug=slug,
            name=settings.business_name,
            business_name=settings.business_name,
            business_context=settings.business_context,
            business_context_file=settings.business_context_file,
            assistant_owner_name=settings.assistant_owner_name,
            personality_level=settings.personality_level,
            whatsapp_phone_number_id=settings.whatsapp_phone_number_id,
            whatsapp_token=settings.whatsapp_token,
            openai_model=settings.openai_model,
            max_history_messages=settings.max_history_messages,
            plan="business",
            monthly_message_limit=2500,
            is_active=True,
        )
        db.add(tenant)
        db.commit()


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    _migrate_tenants_table()
    _migrate_messages_table()
    seed_default_tenant_from_env()
