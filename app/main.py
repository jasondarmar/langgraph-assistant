"""
Main — FastAPI app con endpoints de webhook y health check.
"""
import logging
import sys
import os
from contextlib import asynccontextmanager
from datetime import datetime

import pytz
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks, Depends
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.graph import dental_agent
from app.memory import reset_human_mode, clear_session
from app.security import verify_chatwoot_signature, mask_sensitive_data, validate_rate_limit_key
from app.schemas import WebhookPayloadValidated
from config.database import init_pool, close_pool
from config.settings import get_settings

# ─── Logging ─────────────────────────────────────────────────────────────────
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─── Rate Limiting ───────────────────────────────────────────────────────────
limiter = Limiter(key_func=lambda request: validate_rate_limit_key(get_remote_address(request)))

# Estadísticas en memoria para el endpoint /stats
_stats = {
    "total_messages": 0,
    "total_cost_usd": 0.0,
    "model_usage": {},
    "started_at": datetime.now(pytz.timezone("America/Bogota")).isoformat(),
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 LangGraph Dental Assistant arrancando...")
    if settings.database_url:
        await init_pool(settings.database_url)
    else:
        logger.warning("[DB] DATABASE_URL no configurado — registro en DB desactivado.")
    yield
    await close_pool()
    logger.info("🛑 LangGraph Dental Assistant detenido.")


app = FastAPI(
    title="LangGraph Dental Assistant — Tech Ideas Lab",
    description="Asistente virtual dental para Luna González. WhatsApp + Google Calendar.",
    docs_url=None if os.getenv("ENVIRONMENT") == "production" else "/docs",
    redoc_url=None if os.getenv("ENVIRONMENT") == "production" else "/redoc",
    version="1.0.0",
    lifespan=lifespan,
)

# Agregar rate limiter a la app
app.state.limiter = limiter


# ─── Rate Limit Exception Handler ────────────────────────────────────────────
@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    logger.warning(f"[RateLimit] Límite excedido para {get_remote_address(request)}")
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests. Please try again later."},
    )


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    tz = pytz.timezone("America/Bogota")
    return {
        "status": "ok",
        "timestamp": datetime.now(tz).isoformat(),
        "service": "dental-assistant-langgraph",
    }


# ─── Stats ───────────────────────────────────────────────────────────────────
@app.get("/stats")
async def stats():
    return {
        **_stats,
        "avg_cost_per_message": (
            _stats["total_cost_usd"] / _stats["total_messages"]
            if _stats["total_messages"] > 0 else 0
        ),
    }


# ─── Webhook principal (desde Chatwoot) ──────────────────────────────────────
@app.post("/webhook/chatwoot")
@limiter.limit("10/minute")  # 10 webhooks por minuto (máximo)
async def webhook_chatwoot(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe eventos de Chatwoot (message_created).
    Procesa en background para responder rápido a Chatwoot.

    Valida firma HMAC-SHA256 del webhook para garantizar que viene de Chatwoot.
    """
    # ─── 1. Validar firma del webhook ────────────────────────────────────────
    try:
        body_raw = await request.body()
        body = await request.json()
    except Exception as e:
        logger.error(f"[Webhook] Error parsing JSON: {e}")
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Obtener firma del header
    signature = request.headers.get("X-Chatwoot-Webhook-Signature", "")

    # Validar firma (requiere secret en settings)
    if settings.chatwoot_webhook_secret:
        if not verify_chatwoot_signature(body_raw, signature, settings.chatwoot_webhook_secret):
            logger.warning(f"[Webhook] ❌ Signature validation failed from {get_remote_address(request)}")
            raise HTTPException(status_code=401, detail="Invalid webhook signature")
        logger.debug(f"[Webhook] ✅ Signature validation passed")
    else:
        logger.warning("[Webhook] ⚠️  No webhook secret configured — signature validation skipped")

    event = body.get("event")

    # ── Conversación resuelta → limpiar sesión completa ───────────────────
    if event == "conversation_status_changed":
        status = body.get("status") or body.get("conversation", {}).get("status")
        wa_id = body.get("conversation", {}).get("contact_inbox", {}).get("source_id", "")
        if wa_id:
            if status == "resolved":
                clear_session(wa_id)
                logger.info(f"[Webhook] Sesión limpiada para wa_id={wa_id} (conversación resuelta)")
            elif status == "open":
                reset_human_mode(wa_id)
                logger.info(f"[Webhook] Bot retoma conversación para wa_id={wa_id} (status→open)")
        return {"status": "processed", "reason": "conversation_status_changed"}

    # ── Filtrar solo mensajes entrantes del paciente ──────────────────────
    if event != "message_created":
        return {"status": "ignored", "reason": "not message_created"}

    msg_type = body.get("message_type")
    private = body.get("private", False)
    sender_type = body.get("sender", {}).get("type")

    if msg_type != "incoming" or private or sender_type not in ("contact", None):
        return {"status": "ignored", "reason": "not from contact or is private"}

    # ─── 2. Extraer y validar datos del webhook ──────────────────────────────
    conversation = body.get("conversation", {})
    conv_id = conversation.get("id")
    inbox_id = conversation.get("inbox_id")
    wa_id = conversation.get("contact_inbox", {}).get("source_id", "")

    sender = body.get("sender", {})
    sender_name = sender.get("name", "Paciente")

    # Texto o audio
    content = body.get("content")
    attachments = body.get("attachments", [])
    audio_url = None

    for att in attachments:
        if att.get("file_type") == "audio":
            audio_url = att.get("data_url")
            break

    if not content and not audio_url:
        return {"status": "ignored", "reason": "no content or audio"}

    # Validar payload con Pydantic schema
    try:
        validated_payload = WebhookPayloadValidated(
            conversation_id=conv_id,
            inbox_id=inbox_id,
            wa_id=wa_id,
            sender_name=sender_name,
            raw_content=content,
            audio_url=audio_url,
        )
    except Exception as e:
        logger.error(f"[Webhook] Validation error: {e}")
        raise HTTPException(status_code=400, detail=f"Invalid payload: {str(e)[:100]}")

    # Log con datos redactados (sin PII)
    logger.info(
        f"[Webhook] conv_id={conv_id} inbox_id={inbox_id} "
        f"audio={'si' if audio_url else 'no'}"
    )

    # Construir estado inicial
    initial_state = {
        "conversation_id": conv_id,
        "inbox_id": inbox_id,
        "wa_id": wa_id,
        "sender_name": sender_name,
        "raw_content": content,
        "audio_url": audio_url,
        "media_type": "audio" if audio_url else "text",
        "historial": [],
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "costo_estimado": 0.0,
    }

    background_tasks.add_task(_process_message, initial_state)
    return {"status": "accepted"}


async def _process_message(initial_state: dict):
    """Ejecuta el grafo LangGraph en background."""
    try:
        result = await dental_agent.ainvoke(initial_state)

        # Actualizar estadísticas
        _stats["total_messages"] += 1
        cost = result.get("costo_estimado", 0.0)
        _stats["total_cost_usd"] += cost
        model = result.get("modelo_usado", "unknown")
        _stats["model_usage"][model] = _stats["model_usage"].get(model, 0) + 1

        logger.info(
            f"[Process] ✅ conv={initial_state.get('conversation_id')} "
            f"model={model} cost=${cost:.6f}"
        )

    except Exception as e:
        logger.error(f"[Process] ❌ Error en grafo: {e}", exc_info=True)


# ─── Webhook de prueba local (para testing sin Chatwoot) ─────────────────────
@app.post("/test/message")
@limiter.limit("30/minute")  # Rate limit más permisivo para testing
async def test_message(request: Request):
    """
    Endpoint de prueba. Envía un mensaje directamente al agente.
    ⚠️  SOLO DISPONIBLE EN DESARROLLO. Requiere TEST_TOKEN en Authorization header.

    Body: { "wa_id": "573001234567", "message": "Hola, quiero una cita" }
    Headers: Authorization: Bearer <TEST_TOKEN>
    """
    # Deshabilitar en producción
    if os.getenv("ENVIRONMENT") == "production":
        logger.warning(f"[Test] Unauthorized access attempt from {get_remote_address(request)}")
        raise HTTPException(status_code=404, detail="Not found")

    # Verificar token en desarrollo
    auth_header = request.headers.get("Authorization", "")
    test_token = os.getenv("TEST_TOKEN")

    if test_token:
        token = auth_header.replace("Bearer ", "")
        if token != test_token:
            logger.warning(f"[Test] Invalid token from {get_remote_address(request)}")
            raise HTTPException(status_code=401, detail="Invalid test token")

    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    wa_id = body.get("wa_id", "test_user")
    message = body.get("message", "")
    conv_id = body.get("conversation_id", 999)

    initial_state = {
        "conversation_id": conv_id,
        "inbox_id": 1,
        "wa_id": wa_id,
        "sender_name": "Test User",
        "raw_content": message,
        "audio_url": None,
        "media_type": "text",
        "historial": [],
        "tokens_entrada": 0,
        "tokens_salida": 0,
        "costo_estimado": 0.0,
    }

    try:
        result = await dental_agent.ainvoke(initial_state)
        return {
            "respuesta": result.get("respuesta"),
            "intent": result.get("intent"),
            "estado": result.get("estado_conversacion"),
            "datos_capturados": result.get("datos_capturados"),
            "modelo_usado": result.get("modelo_usado"),
            "costo_estimado": result.get("costo_estimado"),
            "error": result.get("error"),
        }
    except Exception as e:
        logger.error(f"[Test] Error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        log_level=settings.log_level.lower(),
    )
