from datetime import datetime, timezone

from app.database import SessionLocal, Tenant, TenantUsage
from app.services.plans import get_plan_label


def current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _get_or_create_usage(db, tenant_id: int, period: str) -> TenantUsage:
    usage = (
        db.query(TenantUsage)
        .filter(TenantUsage.tenant_id == tenant_id, TenantUsage.period == period)
        .first()
    )
    if usage:
        return usage

    usage = TenantUsage(tenant_id=tenant_id, period=period, message_count=0)
    db.add(usage)
    db.flush()
    return usage


def get_usage(tenant_id: int, period: str | None = None) -> int:
    period = period or current_period()
    with SessionLocal() as db:
        usage = (
            db.query(TenantUsage)
            .filter(TenantUsage.tenant_id == tenant_id, TenantUsage.period == period)
            .first()
        )
        return usage.message_count if usage else 0


def increment_usage(tenant_id: int) -> int:
    period = current_period()
    with SessionLocal() as db:
        usage = _get_or_create_usage(db, tenant_id, period)
        usage.message_count += 1
        db.commit()
        return usage.message_count


def is_within_limit(tenant_id: int, monthly_limit: int) -> bool:
    return get_usage(tenant_id) < monthly_limit


def usage_percent(used: int, limit: int) -> int:
    if limit <= 0:
        return 100
    return min(100, round((used / limit) * 100))


def get_tenant_usage_summary(tenant: Tenant) -> dict:
    used = get_usage(tenant.id)
    limit = tenant.monthly_message_limit
    return {
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "percent": usage_percent(used, limit),
        "period": current_period(),
        "plan": tenant.plan,
        "plan_label": get_plan_label(tenant.plan),
    }


def get_dashboard_metrics() -> dict:
    period = current_period()
    with SessionLocal() as db:
        tenants = db.query(Tenant).order_by(Tenant.id).all()
        rows = []
        total_used = 0
        total_limit = 0
        active_count = 0
        near_limit = 0
        at_limit = 0

        for tenant in tenants:
            summary = get_tenant_usage_summary(tenant)
            total_used += summary["used"]
            total_limit += summary["limit"]
            if tenant.is_active:
                active_count += 1
            if summary["percent"] >= 100:
                at_limit += 1
            elif summary["percent"] >= 80:
                near_limit += 1

            rows.append(
                {
                    "id": tenant.id,
                    "slug": tenant.slug,
                    "name": tenant.name,
                    "business_name": tenant.business_name,
                    "is_active": tenant.is_active,
                    "plan": tenant.plan,
                    "plan_label": summary["plan_label"],
                    "used": summary["used"],
                    "limit": summary["limit"],
                    "remaining": summary["remaining"],
                    "percent": summary["percent"],
                }
            )

    return {
        "period": period,
        "tenant_count": len(rows),
        "active_count": active_count,
        "total_used": total_used,
        "total_limit": total_limit,
        "near_limit": near_limit,
        "at_limit": at_limit,
        "tenants": rows,
    }
