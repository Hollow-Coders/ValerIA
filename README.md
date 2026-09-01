# ValerIA

Asistente de WhatsApp con IA, multi-cliente (SaaS).

## Qué hace

- Un solo servidor atiende **varios clientes/negocios**
- Detecta el cliente por `phone_number_id` de WhatsApp
- Cada cliente tiene su contexto, personalidad y credenciales
- Historial de chat separado por cliente y por contacto

## Setup rápido

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Al arrancar, si no hay clientes en la BD, crea uno con los datos del `.env`.

## Webhook (Meta)

- Callback URL: `https://TU_DOMINIO/webhook`
- Verify token: `WHATSAPP_VERIFY_TOKEN`
- Suscríbete a `messages`

## Panel admin (para ustedes)

URL: `http://localhost:8000/panel/login`

- Contraseña: la misma de `ADMIN_API_KEY` en `.env`
- Dashboard con métricas de uso por cliente
- Crear / editar clientes
- Límites por plan (Starter 500, Business 2500, Pro 8000 msgs/mes)
- Si un cliente llega al límite, ValerIA deja de responder con IA y avisa al usuario

## Agregar un cliente nuevo (API admin)

Header: `X-Admin-Key: tu_ADMIN_API_KEY`

```bash
curl -X POST http://localhost:8000/admin/tenants ^
  -H "Content-Type: application/json" ^
  -H "X-Admin-Key: valeria_admin_secret" ^
  -d "{\"slug\":\"clinica-sol\",\"name\":\"Clinica Sol\",\"business_name\":\"Clinica Sol\",\"whatsapp_phone_number_id\":\"OTRO_PHONE_ID\",\"whatsapp_token\":\"OTRO_TOKEN\",\"business_context_file\":\"app/contexts/seguros_mexicali_plus.txt\",\"assistant_owner_name\":\"Ana\",\"personality_level\":4}"
```

Listar clientes:

```bash
curl http://localhost:8000/admin/tenants -H "X-Admin-Key: valeria_admin_secret"
```

## Arquitectura

```
WhatsApp Cliente A  --phone_number_id A-->  ValerIA  --> contexto A
WhatsApp Cliente B  --phone_number_id B-->  ValerIA  --> contexto B
```

## Contexto por cliente

Crea un archivo en `app/contexts/` por negocio y pásalo en `business_context_file` al crear el tenant.
