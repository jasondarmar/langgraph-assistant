"""
Main — FastAPI app con endpoints de webhook y health check.
"""
import logging
import sys
from contextlib import asynccontextmanager
from datetime import datetime

import pytz
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse

from app.graph import dental_agent
from config.settings import get_settings

# ─── Logging ─────────────────────────────────────────────────────────────────
settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

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
    yield
    logger.info("🛑 LangGraph Dental Assistant detenido.")


app = FastAPI(
    title="LangGraph Dental Assistant — Tech Ideas Lab",
    description="Asistente virtual dental para Luna González. WhatsApp + Google Calendar.",
    version="1.0.0",
    lifespan=lifespan,
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
async def webhook_chatwoot(request: Request, background_tasks: BackgroundTasks):
    """
    Recibe eventos de Chatwoot (message_created).
    Procesa en background para responder rápido a Chatwoot.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Filtrar solo mensajes entrantes del paciente
    event = body.get("event")
    if event != "message_created":
        return {"status": "ignored", "reason": "not message_created"}

    msg_type = body.get("message_type")
    private = body.get("private", False)
    sender_type = body.get("sender", {}).get("type")

    if msg_type != "incoming" or private or sender_type != "contact":
        return {"status": "ignored", "reason": "not from contact or is private"}

    # Extraer datos del webhook
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

    logger.info(
        f"[Webhook] conv_id={conv_id} wa_id={wa_id} "
        f"audio={'si' if audio_url else 'no'} content={str(content)[:40]}"
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
async def test_message(request: Request):
    """
    Endpoint de prueba. Envía un mensaje directamente al agente.
    Body: { "wa_id": "573001234567", "message": "Hola, quiero una cita" }
    """
    body = await request.json()
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
