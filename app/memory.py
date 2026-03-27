"""
Memory — gestión de historial conversacional por wa_id.
Usa Redis si está disponible, dict en memoria como fallback.
"""
import json
import logging
from typing import Optional
from datetime import datetime
import pytz

logger = logging.getLogger(__name__)

# Fallback en memoria (para desarrollo sin Redis)
_memory_store: dict[str, dict] = {}


def _get_redis():
    """Intenta conectar a Redis. Retorna cliente o None."""
    try:
        from config.settings import get_settings
        settings = get_settings()
        if not settings.use_redis:
            return None
        import redis
        r = redis.from_url(settings.redis_url, decode_responses=True)
        r.ping()
        return r
    except Exception as e:
        logger.warning(f"[Memory] Redis no disponible: {e}. Usando memoria local.")
        return None


def _session_key(wa_id: str) -> str:
    return f"session:{wa_id}"


def get_session(wa_id: str) -> dict:
    """Retorna la sesión actual del usuario o un dict vacío."""
    r = _get_redis()
    try:
        if r:
            raw = r.get(_session_key(wa_id))
            if raw:
                return json.loads(raw)
        else:
            return _memory_store.get(wa_id, {})
    except Exception as e:
        logger.error(f"[Memory] Error get_session: {e}")
    return {}


def save_session(wa_id: str, session: dict, ttl_seconds: int = 86400) -> None:
    """Guarda la sesión. TTL default 24 horas."""
    r = _get_redis()
    try:
        if r:
            r.setex(_session_key(wa_id), ttl_seconds, json.dumps(session))
        else:
            _memory_store[wa_id] = session
    except Exception as e:
        logger.error(f"[Memory] Error save_session: {e}")


def clear_session(wa_id: str) -> None:
    """Elimina la sesión de un usuario."""
    r = _get_redis()
    try:
        if r:
            r.delete(_session_key(wa_id))
        else:
            _memory_store.pop(wa_id, None)
    except Exception as e:
        logger.error(f"[Memory] Error clear_session: {e}")


def update_history(wa_id: str, role: str, content: str) -> None:
    """Agrega un mensaje al historial de la sesión."""
    session = get_session(wa_id)
    history = session.get("history", [])
    history.append({"role": role, "content": content})
    # Mantener últimos 20 mensajes para no exceder contexto
    if len(history) > 20:
        history = history[-20:]
    session["history"] = history
    save_session(wa_id, session)


def get_history_text(wa_id: str) -> str:
    """Retorna el historial como texto para el system prompt."""
    session = get_session(wa_id)
    history = session.get("history", [])
    lines = []
    for msg in history:
        role_label = "Paciente" if msg["role"] == "user" else "Yanny"
        lines.append(f"{role_label}: {msg['content']}")
    return "\n".join(lines)


def get_session_data(wa_id: str) -> dict:
    """Retorna datos de la sesión: datos_capturados, human_mode, etc."""
    session = get_session(wa_id)
    return {
        "datos_capturados": session.get("datos_capturados", {}),
        "human_mode": session.get("human_mode", False),
        "active_session": session.get("active_session", False),
        "fecha_calculada": session.get("fecha_calculada"),
    }


def update_session_data(wa_id: str, data: dict) -> None:
    """Actualiza campos de la sesión sin reemplazar el historial."""
    session = get_session(wa_id)
    session.update(data)
    save_session(wa_id, session)
