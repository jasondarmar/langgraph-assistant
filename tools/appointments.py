"""
Appointments — herramientas de Google Calendar para gestión de citas.
Implementa: get_availability, create_appointment, delete_appointment.
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import pytz
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.state import AgentState
from config.settings import get_settings
from tools.db_repository import get_tenant_by_inbox_id, save_appointment, update_appointment_estado

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _get_calendar_service():
    """Crea y retorna el servicio de Google Calendar."""
    settings = get_settings()
    creds_dict = json.loads(settings.google_credentials_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return build("calendar", "v3", credentials=creds)


def get_availability(
    fecha_hora_inicio: str,
    fecha_hora_fin: str,
) -> list[dict]:
    """
    Consulta eventos en el calendario para un rango de tiempo.
    Retorna lista de eventos con id, summary y description.

    Usa esta herramienta para consultar los eventos existentes en el calendario
    ANTES de crear una cita. Consulta siempre el rango de 1 hora alrededor del
    horario solicitado.
    La respuesta incluirá los eventos con su título en formato
    [Sede] - [Nombre paciente] - [Servicio] - [Doctor].
    Debes analizar los títulos de los eventos retornados para verificar si el
    doctor solicitado ya tiene una cita en esa franja horaria.
    Si encuentras un evento cuyo título TERMINA con el nombre del doctor
    (ej: "- Dr. Enrique Luna"), ese doctor NO está disponible en ese horario.
    Para confirmar la sede de una cita encontrada, revisa el campo Description
    del evento que contiene "Sede: [sede]".
    """
    settings = get_settings()
    try:
        service = _get_calendar_service()
        result = service.events().list(
            calendarId=settings.google_calendar_id,
            timeMin=fecha_hora_inicio,
            timeMax=fecha_hora_fin,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        simplified = []
        for ev in events:
            simplified.append({
                "id": ev.get("id"),
                "summary": ev.get("summary", ""),
                "description": ev.get("description", ""),
                "start": ev.get("start", {}).get("dateTime"),
                "end": ev.get("end", {}).get("dateTime"),
            })

        logger.info(f"[Calendar] get_availability: {len(simplified)} eventos encontrados")
        return simplified

    except HttpError as e:
        logger.error(f"[Calendar] Error get_availability: {e}")
        return []


def create_appointment(
    summary: str,
    description: str,
    start_datetime: str,
    end_datetime: str,
) -> Optional[dict]:
    """
    Crea un evento en el calendario.
    - summary: "[Sede] - [Nombre paciente] - [Servicio] - [Doctor]"
    - description: "Sede: [sede] | Paciente: [nombre] | Servicio: [servicio] | Doctor: [doctor]"
    - start/end: ISO 8601 con timezone -05:00
    Retorna el evento creado o None si falla.
    """
    settings = get_settings()
    try:
        service = _get_calendar_service()
        event = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_datetime, "timeZone": "America/Bogota"},
            "end":   {"dateTime": end_datetime,   "timeZone": "America/Bogota"},
        }
        created = service.events().insert(
            calendarId=settings.google_calendar_id,
            body=event,
        ).execute()
        logger.info(f"[Calendar] Evento creado: {created.get('id')} — {summary}")
        return created

    except HttpError as e:
        logger.error(f"[Calendar] Error create_appointment: {e}")
        return None


def delete_appointment(event_id: str) -> bool:
    """
    Elimina un evento del calendario por su ID.
    Retorna True si fue eliminado, False si falló.
    """
    settings = get_settings()
    try:
        service = _get_calendar_service()
        service.events().delete(
            calendarId=settings.google_calendar_id,
            eventId=event_id,
        ).execute()
        logger.info(f"[Calendar] Evento eliminado: {event_id}")
        return True

    except HttpError as e:
        if e.resp.status == 404:
            logger.warning(f"[Calendar] Evento no encontrado (ya eliminado?): {event_id}")
            return True  # Idempotente — si no existe, consideramos éxito
        logger.error(f"[Calendar] Error delete_appointment: {e}")
        return False


_NULL_VALS = {"null", "", None}


async def _execute_create(state: AgentState, datos: dict) -> AgentState | None:
    """
    Intenta crear la cita en Calendar y guardarla en DB.
    Retorna el estado actualizado o None si faltan campos o falla sin recuperación.
    """
    nombre = datos.get("nombre_paciente")
    sede = datos.get("sede")
    servicio = datos.get("servicio")
    doctor = datos.get("doctor")
    fecha = datos.get("fecha_cita")
    hora = datos.get("hora_cita")

    missing = [k for k, v in {
        "nombre": nombre, "sede": sede, "servicio": servicio,
        "doctor": doctor, "fecha": fecha, "hora": hora,
    }.items() if v in _NULL_VALS]

    if missing:
        logger.warning(f"[Calendar] _execute_create: campos faltantes {missing} — abortando")
        return None

    try:
        hora_lower = hora.lower().strip()
        hora_clean = hora_lower.replace("pm", "").replace("am", "").strip()
        if hora_clean.count(":") == 2:
            hora_clean = hora_clean.rsplit(":", 1)[0]
        if ":" not in hora_clean:
            hora_clean += ":00"
        dt_start = datetime.strptime(f"{fecha} {hora_clean}", "%Y-%m-%d %H:%M")
        if "pm" in hora_lower and dt_start.hour < 12:
            dt_start = dt_start.replace(hour=dt_start.hour + 12)
        dt_end = dt_start + timedelta(hours=1)
        start_iso = dt_start.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"
        end_iso = dt_end.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"

        # Verificar disponibilidad
        existing = get_availability(start_iso, end_iso)
        for ev in existing:
            if ev.get("summary", "").endswith(doctor):
                logger.warning(f"[Calendar] Doctor {doctor} no disponible en {start_iso}")
                return {
                    **state,
                    "datos_capturados": datos,
                    "error": f"Doctor {doctor} no disponible en ese horario",
                    "respuesta": (
                        f"Lamentablemente el {doctor} no está disponible en ese horario. "
                        "¿Quieres elegir otro horario? 😊"
                    ),
                }

        summary_ev = f"{sede} - {nombre} - {servicio} - {doctor}"
        description = f"Sede: {sede} | Paciente: {nombre} | Servicio: {servicio} | Doctor: {doctor}"
        created = create_appointment(summary_ev, description, start_iso, end_iso)

        if not created:
            return None

        new_event_id = created.get("id")
        inbox_id = state.get("inbox_id")
        tenant = await get_tenant_by_inbox_id(inbox_id) if inbox_id else None
        if tenant:
            # costo_acumulado incluye todos los turnos de la conversación;
            # si no está disponible, usamos solo el del turno actual como fallback
            costo_total = state.get("costo_acumulado") or state.get("costo_estimado", 0.0)
            # Sumar el turno actual al acumulado (aún no se sumó en save_session_node)
            costo_total += state.get("costo_estimado", 0.0)
            await save_appointment(
                tenant_id=tenant["id"],
                wa_id=state.get("wa_id", ""),
                nombre_paciente=nombre,
                sede=sede,
                servicio=servicio,
                doctor=doctor,
                fecha_cita=fecha,
                hora_cita=hora,
                event_id=new_event_id,
                resumen_conversacion=state.get("resumen_conversacion"),
                modelo_usado=state.get("modelo_usado"),
                tokens_entrada=state.get("tokens_entrada", 0),
                tokens_salida=state.get("tokens_salida", 0),
                costo_estimado=costo_total,
            )
        else:
            logger.warning(
                f"[DB] Tenant no encontrado para inbox_id={inbox_id} — cita no registrada en DB."
            )

        return {
            **state,
            "datos_capturados": {**datos, "event_id": new_event_id},
            "estado_conversacion": "finalizado",
        }

    except Exception as e:
        logger.error(f"[Calendar] Error en _execute_create: {e}")
        return {**state, "error": str(e)}


async def handle_calendar_action(state: AgentState) -> AgentState:
    """
    Nodo que ejecuta acciones de calendario según lo que el agente indicó:
    - accion_calendario == "delete" → elimina el evento
      - Cancelación (estado=finalizado): limpia fecha/hora y termina.
      - Modificación (estado=en_proceso): conserva datos, actualiza fecha con
        fecha_calculada si está disponible, e intenta crear la nueva cita
        inmediatamente en el mismo turno para evitar loops de conversación.
    - datos_capturados completos + estado == "datos_completos" → crea la cita
    """
    accion = state.get("accion_calendario")
    datos = state.get("datos_capturados", {})

    # ─── DELETE ──────────────────────────────────────────────────────────
    if accion == "delete":
        event_id = datos.get("event_id")
        if not event_id or event_id in _NULL_VALS:
            intent = state.get("intent", "")
            if intent in ("cancelar_cita", "modificar_cita"):
                logger.warning("[Calendar] accion=delete sin event_id en flujo cancel/modify — limpiando sesión")
                return {
                    **state,
                    "datos_capturados": {},
                    "estado_conversacion": "en_proceso",
                    "accion_calendario": None,
                    "respuesta": "No encontré una cita activa en tu nombre. ¿Te gustaría agendar una nueva cita? 😊",
                }
            else:
                logger.warning("[Calendar] accion=delete sin event_id — ignorando delete, continuando normal")
                return {**state, "accion_calendario": None}

        success = delete_appointment(event_id)
        if not success:
            return {
                **state,
                "error": f"No se pudo eliminar el evento {event_id}",
                "accion_calendario": None,
            }

        await update_appointment_estado(
            event_id=event_id,
            estado="cancelada",
            resumen_conversacion=state.get("resumen_conversacion"),
        )

        estado_conv = state.get("estado_conversacion", "en_proceso")
        is_cancel = (estado_conv == "finalizado")
        nuevos_datos = {**datos, "event_id": None}

        if is_cancel:
            # Pure cancellation: clear booking fields to start fresh
            nuevos_datos["fecha_cita"] = None
            nuevos_datos["hora_cita"] = None
            return {
                **state,
                "datos_capturados": nuevos_datos,
                "estado_conversacion": estado_conv,
                "accion_calendario": None,
            }

        # ── Modification path ────────────────────────────────────────────
        logger.info(
            f"[Calendar] Modificación: iniciando reagendamiento. "
            f"datos={{{', '.join(f'{k}={v}' for k, v in nuevos_datos.items() if k != 'event_id')}}}"
        )

        # Override stale fecha_cita with fecha_calculada when available.
        # The LLM often retains the old appointment date in datos_capturados
        # during the confirmation turn; fecha_calculada is computed from the
        # user's original message ("para el jueves") and is always correct.
        fecha_calculada = state.get("fecha_calculada")
        if fecha_calculada and fecha_calculada not in _NULL_VALS:
            logger.info(
                f"[Calendar] Modificación: actualizando fecha_cita "
                f"{nuevos_datos.get('fecha_cita')} → {fecha_calculada}"
            )
            nuevos_datos["fecha_cita"] = fecha_calculada

        nombre = nuevos_datos.get("nombre_paciente", "")

        # Attempt immediate create so the user doesn't need another message turn
        state_for_create = {
            **state,
            "datos_capturados": nuevos_datos,
            "estado_conversacion": "datos_completos",
            "accion_calendario": None,
        }
        result = await _execute_create(state_for_create, nuevos_datos)
        if result is not None:
            if result.get("error") is None:
                # Successful immediate create — add a clear confirmation message
                fecha = nuevos_datos.get("fecha_cita", "")
                hora = nuevos_datos.get("hora_cita", "")
                doctor = nuevos_datos.get("doctor", "")
                sede = nuevos_datos.get("sede", "")
                result["respuesta"] = (
                    f"¡Listo, {nombre}! Tu cita ha sido reagendada para el {fecha} "
                    f"a las {hora} con {doctor} en la sede {sede}. 😊"
                )
                logger.info("[Calendar] Modificación completada: delete + create en un solo turno")
            else:
                # Create failed with error (e.g. doctor not available) — inform user
                logger.warning(f"[Calendar] Modificación: create falló con error: {result.get('error')}")
            return result

        # If immediate create couldn't run (missing fields), fall back to normal flow
        # Override the LLM response so the user knows what happened
        missing = [k for k, v in {
            "nombre": nuevos_datos.get("nombre_paciente"),
            "sede": nuevos_datos.get("sede"),
            "servicio": nuevos_datos.get("servicio"),
            "doctor": nuevos_datos.get("doctor"),
            "fecha": nuevos_datos.get("fecha_cita"),
            "hora": nuevos_datos.get("hora_cita"),
        }.items() if v in _NULL_VALS]
        logger.warning(
            f"[Calendar] Modificación: create inmediato falló — campos faltantes: {missing}"
        )
        return {
            **state,
            "datos_capturados": nuevos_datos,
            "estado_conversacion": "en_proceso",
            "accion_calendario": None,
            "respuesta": (
                f"Tu cita anterior ha sido cancelada exitosamente, {nombre}. "
                "Ahora vamos a reagendar. "
                + (f"Solo necesito que me confirmes: {'la ' if len(missing) == 1 else ''}"
                   f"{', '.join(missing)}. 😊"
                   if missing else
                   "¿Puedes confirmarme los datos para la nueva cita? 😊")
            ),
        }

    # ─── CREATE ──────────────────────────────────────────────────────────
    estado_conv = state.get("estado_conversacion")
    if estado_conv == "datos_completos":
        # Skip create if user already has an active appointment (event_id set)
        existing_event_id = datos.get("event_id")
        if existing_event_id and existing_event_id not in _NULL_VALS:
            logger.info(f"[Calendar] Skipping create — cita activa existente: {existing_event_id}")
            return state

        missing = [k for k, v in {
            "nombre": datos.get("nombre_paciente"),
            "sede": datos.get("sede"),
            "servicio": datos.get("servicio"),
            "doctor": datos.get("doctor"),
            "fecha": datos.get("fecha_cita"),
            "hora": datos.get("hora_cita"),
        }.items() if v in _NULL_VALS]

        if missing:
            logger.warning(f"[Calendar] datos_completos pero campos inválidos: {missing} — abortando create")
            return {**state, "estado_conversacion": "en_proceso"}

        result = await _execute_create(state, datos)
        if result is not None:
            return result

    return state
