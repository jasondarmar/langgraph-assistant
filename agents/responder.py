"""
Responder — nodo principal del agente. Genera la respuesta usando el LLM
seleccionado por el router según la intención detectada.
"""
import json
import logging
from datetime import datetime, timedelta
import pytz

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage

from app.state import AgentState, DatosCita
from agents.llm_router import get_model_for_intent, log_cost
from config.prompts import get_system_prompt
from config.settings import get_settings

logger = logging.getLogger(__name__)


def _get_fecha_context() -> tuple[str, str]:
    """Retorna (fecha_actual YYYY-MM-DD, fecha_actual_texto)."""
    tz = pytz.timezone("America/Bogota")
    now = datetime.now(tz)
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = [
        "enero", "febrero", "marzo", "abril", "mayo", "junio",
        "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    ]
    fecha_str = now.strftime("%Y-%m-%d")
    texto = f"{dias[now.weekday()]} {now.day} de {meses[now.month - 1]} de {now.year}"
    return fecha_str, texto


def _calcular_fecha(mensaje: str, fecha_actual: str) -> str | None:
    """Detecta palabras clave de fechas relativas en el mensaje."""
    tz = pytz.timezone("America/Bogota")
    hoy = datetime.strptime(fecha_actual, "%Y-%m-%d").replace(tzinfo=tz)
    texto = mensaje.lower()

    dias_semana = {
        "lunes": 0, "martes": 1, "miércoles": 2, "miercoles": 2,
        "jueves": 3, "viernes": 4, "sábado": 5, "sabado": 5, "domingo": 6,
    }

    if "pasado mañana" in texto or "pasado manana" in texto:
        return (hoy + timedelta(days=2)).strftime("%Y-%m-%d")
    elif "mañana" in texto or "manana" in texto:
        return (hoy + timedelta(days=1)).strftime("%Y-%m-%d")
    elif "hoy" in texto:
        return fecha_actual
    else:
        for dia, num in dias_semana.items():
            if dia in texto:
                hoy_num = hoy.weekday()
                dias_hasta = num - hoy_num
                if dias_hasta <= 0:
                    dias_hasta += 7
                return (hoy + timedelta(days=dias_hasta)).strftime("%Y-%m-%d")
    return None


def generate_response(state: AgentState) -> AgentState:
    """
    Nodo principal: construye el contexto, llama al LLM apropiado
    y parsea la respuesta JSON del agente.
    """
    if state.get("skip_llm", False):
        logger.info("[Responder] skip_llm=True, omitiendo generación")
        return state

    # ─── Contexto de fecha ───────────────────────────────────────────────
    fecha_actual = state.get("fecha_actual", "")
    fecha_actual_texto = state.get("fecha_actual_texto", "")

    if not fecha_actual:
        fecha_actual, fecha_actual_texto = _get_fecha_context()

    mensaje = state.get("mensaje_actual", "")
    fecha_calculada = state.get("fecha_calculada")

    # Intentar calcular fecha si no está calculada
    if mensaje and not fecha_calculada:
        fecha_calculada = _calcular_fecha(mensaje, fecha_actual)

    datos = state.get("datos_capturados", {})
    event_id_actual = datos.get("event_id")
    sede_actual = datos.get("sede")

    # ─── System prompt dinámico ──────────────────────────────────────────
    system_prompt = get_system_prompt(
        fecha_actual=fecha_actual,
        fecha_actual_texto=fecha_actual_texto,
        fecha_calculada=fecha_calculada,
        event_id_actual=event_id_actual,
        sede_actual=sede_actual,
    )

    # ─── Historial + contexto ────────────────────────────────────────────
    historial_texto = state.get("historial_texto", "")
    tz = pytz.timezone("America/Bogota")
    now = datetime.now(tz)
    manana = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    context_lines = [
        f"[FECHA ACTUAL: {fecha_actual_texto} ({fecha_actual}). Zona horaria: America/Bogota (UTC-5)]",
    ]
    if fecha_calculada:
        context_lines.append(
            f"[FECHA CALCULADA PARA LA CITA: {fecha_calculada}. USA ESTA FECHA EXACTA.]"
        )
    if event_id_actual:
        context_lines.append(
            f"[EVENT_ID CITA ACTUAL: {event_id_actual}. Úsalo para delete si el paciente confirma.]"
        )
    if sede_actual:
        context_lines.append(f"[SEDE SELECCIONADA: {sede_actual}.]")

    contexto = "\n".join(context_lines)
    historial_completo = f"{contexto}\n{historial_texto}"
    if mensaje:
        historial_completo += f"\nPaciente: {mensaje}"

    # ─── Selección de modelo ─────────────────────────────────────────────
    intent = state.get("intent", "otro")
    model, model_id = get_model_for_intent(intent)

    # ─── Llamada al LLM ──────────────────────────────────────────────────
    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=historial_completo),
        ]

        response = model.invoke(messages)
        raw = response.content.strip()

        # Limpiar posibles markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        parsed = json.loads(raw)

        # Extraer campos del JSON del agente
        respuesta = parsed.get("respuesta", "")
        estado_conv = parsed.get("estado", "en_proceso")
        nuevos_datos: DatosCita = parsed.get("datos_capturados", {})
        accion_cal = parsed.get("accion_calendario")
        requiere_humano = parsed.get("requiere_humano", False)
        resumen = parsed.get("resumen_conversacion", "")

        # Merge: preserve existing session values for fields where LLM returned null
        _null_values: set = {"null", "", None}
        datos_merged: DatosCita = {}
        for key in ("nombre_paciente", "sede", "servicio", "doctor", "fecha_cita", "hora_cita", "event_id"):
            llm_val = nuevos_datos.get(key)
            existing_val = datos.get(key)
            if llm_val not in _null_values:
                datos_merged[key] = llm_val
            elif existing_val not in _null_values:
                datos_merged[key] = existing_val
            else:
                datos_merged[key] = llm_val

        # Tokens y costo
        usage = response.response_metadata.get("token_usage", {})
        input_tokens = usage.get("prompt_tokens", 0)
        output_tokens = usage.get("completion_tokens", 0)
        costo = log_cost(model_id, input_tokens, output_tokens)

        logger.info(
            f"[Responder] intent={intent} model={model_id} "
            f"estado={estado_conv} accion_cal={accion_cal}"
        )

        return {
            **state,
            "fecha_actual": fecha_actual,
            "fecha_actual_texto": fecha_actual_texto,
            "fecha_calculada": fecha_calculada,
            "respuesta": respuesta,
            "estado_conversacion": estado_conv,
            "datos_capturados": datos_merged,
            "accion_calendario": accion_cal if accion_cal == "delete" else None,
            "requiere_humano": requiere_humano,
            "resumen_conversacion": resumen,
            "modelo_usado": model_id,
            "tokens_entrada": input_tokens,
            "tokens_salida": output_tokens,
            "costo_estimado": costo,
            "error": None,
        }

    except json.JSONDecodeError as e:
        logger.error(f"[Responder] JSON parse error: {e}\nRaw: {raw}")
        return {
            **state,
            "respuesta": "Disculpa, tuve un problema técnico. ¿Puedes repetir tu mensaje? 😊",
            "estado_conversacion": "en_proceso",
            "error": f"JSON parse error: {e}",
        }
    except Exception as e:
        logger.error(f"[Responder] Error inesperado: {e}")
        return {
            **state,
            "respuesta": "Disculpa, ocurrió un error. Por favor intenta nuevamente. 😊",
            "estado_conversacion": "en_proceso",
            "error": str(e),
        }
