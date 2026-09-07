import asyncio
import logging

from app.services.reminders import (
    build_due_message,
    fetch_due_reminders,
    mark_reminder_failed,
    mark_reminder_sent,
)
from app.services.tenant import get_tenant_config_by_id
from app.services.whatsapp import send_text_message

logger = logging.getLogger("valeria")

_scheduler_task: asyncio.Task | None = None


async def process_due_reminders() -> int:
    due = fetch_due_reminders(limit=50)
    sent = 0
    for reminder in due:
        tenant = get_tenant_config_by_id(reminder.tenant_id)
        if not tenant or not tenant.notify_phone:
            mark_reminder_sent(reminder.id)
            continue

        to_phone = reminder.advisor_phone or tenant.notify_phone
        try:
            message = build_due_message(tenant, reminder)
            await send_text_message(tenant, to_phone, message)
            mark_reminder_sent(reminder.id)
            sent += 1
            logger.info(
                "Recordatorio enviado id=%s tenant=%s to=%s",
                reminder.id,
                tenant.slug,
                to_phone,
            )
        except Exception:
            logger.exception("Error enviando recordatorio id=%s", reminder.id)
            mark_reminder_failed(reminder.id)
    return sent


async def _scheduler_loop(interval_seconds: int = 45) -> None:
    logger.info("Scheduler de recordatorios iniciado (cada %ss)", interval_seconds)
    while True:
        try:
            await process_due_reminders()
        except Exception:
            logger.exception("Error en ciclo de recordatorios")
        await asyncio.sleep(interval_seconds)


def start_reminder_scheduler() -> None:
    global _scheduler_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("No hay event loop para iniciar scheduler")
        return

    if _scheduler_task and not _scheduler_task.done():
        return
    _scheduler_task = loop.create_task(_scheduler_loop())
