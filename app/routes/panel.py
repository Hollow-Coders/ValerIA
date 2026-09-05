from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.responses import Response

from app.config import settings
from app.services.plans import PLANS, get_plan_limit
from app.services.handoff import count_pending_handoffs, list_conversations, pause_bot, resume_bot
from app.services.tenant import create_tenant, get_tenant_by_id, get_tenant_config_by_id, update_tenant
from app.services.conversation import get_thread, save_message
from app.services.usage import get_dashboard_metrics, get_tenant_usage_summary
from app.services.whatsapp import send_text_message

router = APIRouter(prefix="/panel", tags=["panel"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("panel_auth"))


def _require_auth(request: Request) -> RedirectResponse | None:
    if not _is_authenticated(request):
        return RedirectResponse("/panel/login", status_code=303)
    return None


@router.get("/login", response_class=HTMLResponse, response_model=None)
def login_page(request: Request) -> Response:
    if _is_authenticated(request):
        return RedirectResponse("/panel/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": None},
    )


@router.post("/login", response_model=None)
def login_submit(request: Request, password: str = Form(...)) -> Response:
    if not settings.admin_api_key:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "ADMIN_API_KEY no configurada en el servidor."},
            status_code=503,
        )
    if password != settings.admin_api_key:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Contraseña incorrecta."},
            status_code=401,
        )

    request.session["panel_auth"] = True
    return RedirectResponse("/panel/", status_code=303)


@router.get("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return RedirectResponse("/panel/login", status_code=303)


@router.get("/", response_class=HTMLResponse, response_model=None)
def dashboard(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    metrics = get_dashboard_metrics()
    metrics["pending_handoffs"] = count_pending_handoffs()
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "metrics": metrics, "plans": PLANS},
    )


@router.get("/tenants/new", response_class=HTMLResponse, response_model=None)
def new_tenant_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    return templates.TemplateResponse(
        "tenant_form.html",
        {"request": request, "tenant": None, "plans": PLANS, "error": None},
    )


@router.post("/tenants/new", response_model=None)
def create_tenant_submit(
    request: Request,
    slug: str = Form(...),
    name: str = Form(...),
    business_name: str = Form(...),
    whatsapp_phone_number_id: str = Form(...),
    whatsapp_token: str = Form(...),
    assistant_owner_name: str = Form("Gilberto"),
    personality_level: int = Form(4),
    plan: str = Form("business"),
    monthly_message_limit: int | None = Form(None),
    business_context_file: str = Form(""),
    notify_phone: str = Form(""),
    is_active: str | None = Form(None),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    try:
        create_tenant(
            {
                "slug": slug.strip(),
                "name": name.strip(),
                "business_name": business_name.strip(),
                "whatsapp_phone_number_id": whatsapp_phone_number_id.strip(),
                "whatsapp_token": whatsapp_token.strip(),
                "assistant_owner_name": assistant_owner_name.strip(),
                "personality_level": personality_level,
                "plan": plan,
                "monthly_message_limit": monthly_message_limit or get_plan_limit(plan),
                "business_context_file": business_context_file.strip(),
                "notify_phone": notify_phone.strip(),
                "is_active": is_active == "on",
            }
        )
        return RedirectResponse("/panel/", status_code=303)
    except Exception as exc:
        return templates.TemplateResponse(
            "tenant_form.html",
            {
                "request": request,
                "tenant": None,
                "plans": PLANS,
                "error": str(exc),
            },
            status_code=400,
        )


@router.get("/tenants/{tenant_id}", response_class=HTMLResponse, response_model=None)
def edit_tenant_page(request: Request, tenant_id: int) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return RedirectResponse("/panel/", status_code=303)

    usage = get_tenant_usage_summary(tenant)
    return templates.TemplateResponse(
        "tenant_form.html",
        {"request": request, "tenant": tenant, "usage": usage, "plans": PLANS, "error": None},
    )


@router.post("/tenants/{tenant_id}", response_model=None)
def update_tenant_submit(
    request: Request,
    tenant_id: int,
    slug: str = Form(...),
    name: str = Form(...),
    business_name: str = Form(...),
    whatsapp_phone_number_id: str = Form(...),
    whatsapp_token: str = Form(...),
    assistant_owner_name: str = Form("Gilberto"),
    personality_level: int = Form(4),
    plan: str = Form("business"),
    monthly_message_limit: int = Form(...),
    business_context_file: str = Form(""),
    notify_phone: str = Form(""),
    is_active: str | None = Form(None),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    try:
        update_tenant(
            tenant_id,
            {
                "slug": slug.strip(),
                "name": name.strip(),
                "business_name": business_name.strip(),
                "whatsapp_phone_number_id": whatsapp_phone_number_id.strip(),
                "whatsapp_token": whatsapp_token.strip(),
                "assistant_owner_name": assistant_owner_name.strip(),
                "personality_level": personality_level,
                "plan": plan,
                "monthly_message_limit": monthly_message_limit,
                "business_context_file": business_context_file.strip(),
                "notify_phone": notify_phone.strip(),
                "is_active": is_active == "on",
            },
        )
        return RedirectResponse(f"/panel/tenants/{tenant_id}", status_code=303)
    except Exception as exc:
        tenant = get_tenant_by_id(tenant_id)
        usage = get_tenant_usage_summary(tenant) if tenant else None
        return templates.TemplateResponse(
            "tenant_form.html",
            {
                "request": request,
                "tenant": tenant,
                "usage": usage,
                "plans": PLANS,
                "error": str(exc),
            },
            status_code=400,
        )


@router.get("/conversations", response_class=HTMLResponse, response_model=None)
def conversations_page(request: Request) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    conversations = list_conversations()
    return templates.TemplateResponse(
        "conversations.html",
        {"request": request, "conversations": conversations},
    )


@router.get("/conversations/{tenant_id}/{phone}", response_class=HTMLResponse, response_model=None)
def conversation_detail(request: Request, tenant_id: int, phone: str) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    tenant = get_tenant_config_by_id(tenant_id)
    if not tenant:
        return RedirectResponse("/panel/conversations", status_code=303)

    from app.services.handoff import is_bot_enabled

    thread = get_thread(tenant_id, phone)
    return templates.TemplateResponse(
        "conversation_detail.html",
        {
            "request": request,
            "tenant": tenant,
            "phone": phone,
            "thread": thread,
            "bot_enabled": is_bot_enabled(tenant_id, phone),
        },
    )


@router.post("/conversations/{tenant_id}/{phone}/pause", response_model=None)
def pause_conversation(request: Request, tenant_id: int, phone: str) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    pause_bot(tenant_id, phone, reason="manual", advisor_phone="")
    return RedirectResponse(f"/panel/conversations/{tenant_id}/{phone}", status_code=303)


@router.post("/conversations/{tenant_id}/{phone}/resume", response_model=None)
def resume_conversation(request: Request, tenant_id: int, phone: str) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect
    resume_bot(tenant_id, phone)
    return RedirectResponse(f"/panel/conversations/{tenant_id}/{phone}", status_code=303)


@router.post("/conversations/{tenant_id}/{phone}/reply", response_model=None)
async def reply_conversation(
    request: Request,
    tenant_id: int,
    phone: str,
    message: str = Form(...),
) -> Response:
    redirect = _require_auth(request)
    if redirect:
        return redirect

    tenant = get_tenant_config_by_id(tenant_id)
    if not tenant:
        return RedirectResponse("/panel/conversations", status_code=303)

    text = message.strip()
    if text:
        pause_bot(
            tenant_id,
            phone,
            reason="manual",
            advisor_phone=tenant.notify_phone or "",
        )
        await send_text_message(tenant, phone, text)
        save_message(tenant, phone, "human", text)

    return RedirectResponse(f"/panel/conversations/{tenant_id}/{phone}", status_code=303)
