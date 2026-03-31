"""
Graph — definición del StateGraph de LangGraph para el asistente dental.

Flujo:
  parse_input → [audio? → transcribe] → classify_intent
      → [human_mode? → skip] → generate_response
      → handle_calendar → send_response
      → [requiere_humano? → escalate]
      → save_session → END
"""
import logging
from langgraph.graph import StateGraph, END

from app.state import AgentState
from app.memory import get_history_text, get_session_data, update_history, update_session_data
from agents.classifier import classify_intent
from agents.responder import generate_response
from tools.whisper import transcribe_audio_node
from tools.appointments import handle_calendar_action
from tools.escalation import escalate_to_human
from config.settings import get_settings

logger = logging.getLogger(__name__)


# ─── Nodo: parse_input ───────────────────────────────────────────────────────
def parse_input(state: AgentState) -> AgentState:
    """
    Recupera el historial y datos de sesión del usuario desde memoria.
    Determina si es texto o audio.
    """
    wa_id = state.get("wa_id", "")

    session_data = get_session_data(wa_id)
    historial_texto = get_history_text(wa_id)

    # Determinar mensaje actual
    raw_content = state.get("raw_content", "")
    audio_url = state.get("audio_url")
    media_type = "audio" if audio_url else "text"

    mensaje_actual = raw_content if media_type == "text" else ""

    from datetime import datetime
    import pytz
    tz = pytz.timezone("America/Bogota")
    now = datetime.now(tz)
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    fecha_actual = now.strftime("%Y-%m-%d")
    fecha_actual_texto = f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}"

    logger.info(f"[Parser] wa_id={wa_id} media_type={media_type} human_mode={session_data.get('human_mode')}")

    return {
        **state,
        "media_type": media_type,
        "mensaje_actual": mensaje_actual,
        "historial_texto": historial_texto,
        "datos_capturados": session_data.get("datos_capturados", {}),
        "human_mode": session_data.get("human_mode", False),
        "active_session": session_data.get("active_session", False),
        "fecha_calculada": session_data.get("fecha_calculada"),
        "costo_acumulado": session_data.get("costo_acumulado", 0.0),
        "fecha_actual": fecha_actual,
        "fecha_actual_texto": fecha_actual_texto,
        "skip_llm": False,
        "requiere_humano": False,
        "error": None,
    }


# ─── Nodo: send_response ─────────────────────────────────────────────────────
async def send_response_node(state: AgentState) -> AgentState:
    """Envía la respuesta del agente al paciente vía API de Chatwoot."""
    import httpx
    settings = get_settings()

    respuesta = state.get("respuesta", "")
    conv_id = state.get("conversation_id")

    if not respuesta or not conv_id:
        logger.warning("[Send] Sin respuesta o conv_id para enviar")
        return state

    base = f"{settings.chatwoot_base_url}/api/v1/accounts/{settings.chatwoot_account_id}"
    headers = {
        "api_access_token": settings.chatwoot_api_token,
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base}/conversations/{conv_id}/messages",
                headers=headers,
                json={
                    "content": respuesta,
                    "message_type": "outgoing",
                    "private": False,
                },
            )
            resp.raise_for_status()
        logger.info(f"[Send] Respuesta enviada a conv {conv_id}: {respuesta[:200]}")
    except Exception as e:
        logger.error(f"[Send] Error enviando respuesta: {e}")
        return {**state, "error": str(e)}

    return state


# ─── Nodo: save_session ──────────────────────────────────────────────────────
def save_session_node(state: AgentState) -> AgentState:
    """Persiste el historial y datos de sesión actualizados."""
    wa_id = state.get("wa_id", "")
    if not wa_id:
        return state

    # Agregar mensajes al historial
    mensaje = state.get("mensaje_actual", "")
    respuesta = state.get("respuesta", "")
    if mensaje:
        update_history(wa_id, "user", mensaje)
    if respuesta:
        update_history(wa_id, "assistant", respuesta)

    # Actualizar datos de sesión
    estado_conv = state.get("estado_conversacion", "en_proceso")
    costo_turno = state.get("costo_estimado", 0.0)
    costo_prev = state.get("costo_acumulado", 0.0)
    # Acumular costo del turno; resetear cuando la conversación finaliza
    if estado_conv == "finalizado":
        nuevo_costo_acumulado = 0.0
    else:
        nuevo_costo_acumulado = costo_prev + costo_turno
    update_session_data(wa_id, {
        "datos_capturados": state.get("datos_capturados", {}),
        "human_mode": state.get("requiere_humano", False),
        "active_session": estado_conv not in ("finalizado",),
        "fecha_calculada": state.get("fecha_calculada"),
        "costo_acumulado": nuevo_costo_acumulado,
    })

    logger.info(f"[Session] Sesión guardada para wa_id={wa_id}")
    return state


# ─── Routing functions ───────────────────────────────────────────────────────
def route_audio(state: AgentState) -> str:
    if state.get("media_type") == "audio":
        return "transcribe"
    return "classify"


def route_after_classify(state: AgentState) -> str:
    if state.get("skip_llm", False):
        return "send"
    return "respond"


def route_after_respond(state: AgentState) -> str:
    accion = state.get("accion_calendario")
    estado = state.get("estado_conversacion")
    if accion == "delete" or estado == "datos_completos":
        return "calendar"
    return "send"


def route_after_calendar(state: AgentState) -> str:
    return "send"


def route_after_send(state: AgentState) -> str:
    if state.get("requiere_humano", False):
        return "escalate"
    return "save"


# ─── Build Graph ─────────────────────────────────────────────────────────────
def build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    # Nodos
    graph.add_node("parse",    parse_input)
    graph.add_node("transcribe", transcribe_audio_node)
    graph.add_node("classify", classify_intent)
    graph.add_node("respond",  generate_response)
    graph.add_node("calendar", handle_calendar_action)
    graph.add_node("send",     send_response_node)
    graph.add_node("escalate", escalate_to_human)
    graph.add_node("save",     save_session_node)

    # Entry point
    graph.set_entry_point("parse")

    # Edges
    graph.add_conditional_edges("parse",    route_audio, {
        "transcribe": "transcribe",
        "classify":   "classify",
    })
    graph.add_edge("transcribe", "classify")
    graph.add_conditional_edges("classify", route_after_classify, {
        "respond": "respond",
        "send":    "send",
    })
    graph.add_conditional_edges("respond",  route_after_respond, {
        "calendar": "calendar",
        "send":     "send",
    })
    graph.add_edge("calendar", "send")
    graph.add_conditional_edges("send",     route_after_send, {
        "escalate": "escalate",
        "save":     "save",
    })
    graph.add_edge("escalate", "save")
    graph.add_edge("save", END)

    return graph.compile()


# Instancia global del grafo compilado
dental_agent = build_graph()
