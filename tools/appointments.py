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


async def handle_calendar_action(state: AgentState) -> AgentState:
    """
    Nodo que ejecuta acciones de calendario según lo que el agente indicó:
    - accion_calendario == "delete" → elimina el evento
    - datos_capturados completos + estado == "datos_completos" → crea la cita
    """
    accion = state.get("accion_calendario")
    datos = state.get("datos_capturados", {})

    # ─── DELETE ──────────────────────────────────────────────────────────
    if accion == "delete":
        event_id = datos.get("event_id")
        if not event_id:
            logger.warning("[Calendar] accion=delete pero event_id es None, skip")
            return {**state, "accion_calendario": None}

        success = delete_appointment(event_id)
        if success:
            # Registrar cancelación en DB
            await update_appointment_estado(
                event_id=event_id,
                estado="cancelada",
                resumen_conversacion=state.get("resumen_conversacion"),
            )
            # Clear time-specific fields so next turn doesn't auto-recreate old appointment
            nuevos_datos = {
                **datos,
                "event_id": None,
                "fecha_cita": None,
                "hora_cita": None,
            }
            return {
                **state,
                "datos_capturados": nuevos_datos,
                "estado_conversacion": "en_proceso",
                "accion_calendario": None,
            }
        else:
            return {
                **state,
                "error": f"No se pudo eliminar el evento {event_id}",
                "accion_calendario": None,
            }

    # ─── CREATE ──────────────────────────────────────────────────────────
    estado_conv = state.get("estado_conversacion")
    if estado_conv == "datos_completos":
        # Skip create if user already has an active appointment (event_id set)
        # They must cancel first before a new one can be created
        existing_event_id = datos.get("event_id")
        if existing_event_id and existing_event_id not in {"null", "", None}:
            logger.info(f"[Calendar] Skipping create — cita activa existente: {existing_event_id}")
            return state
        _null_vals = {"null", "", None}
        nombre = datos.get("nombre_paciente")
        sede = datos.get("sede")
        servicio = datos.get("servicio")
        doctor = datos.get("doctor")
        fecha = datos.get("fecha_cita")
        hora = datos.get("hora_cita")

        def _valid(v: any) -> bool:
            return v not in _null_vals

        missing = [k for k, v in {"nombre": nombre, "sede": sede, "servicio": servicio,
                                    "doctor": doctor, "fecha": fecha, "hora": hora}.items()
                   if not _valid(v)]
        if missing:
            logger.warning(f"[Calendar] datos_completos pero campos inválidos: {missing} — abortando create")
            return {**state, "estado_conversacion": "en_proceso"}

        if all(_valid(v) for v in [nombre, sede, servicio, doctor, fecha, hora]):
            # Construir datetimes
            try:
                hora_clean = hora.replace("pm", "").replace("am", "").strip()
                if ":" not in hora_clean:
                    hora_clean += ":00"
                # Manejar PM/AM
                hora_lower = hora.lower()
                dt_start = datetime.strptime(f"{fecha} {hora_clean}", "%Y-%m-%d %H:%M")
                if "pm" in hora_lower and dt_start.hour < 12:
                    dt_start = dt_start.replace(hour=dt_start.hour + 12)
                dt_end = dt_start + timedelta(hours=1)

                start_iso = dt_start.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"
                end_iso = dt_end.strftime("%Y-%m-%dT%H:%M:%S") + "-05:00"

                # Primero verificar disponibilidad
                existing = get_availability(start_iso, end_iso)
                for ev in existing:
                    if ev.get("summary", "").endswith(doctor):
                        logger.warning(
                            f"[Calendar] Doctor {doctor} no disponible en {start_iso}"
                        )
                        return {
                            **state,
                            "error": f"Doctor {doctor} no disponible en ese horario",
                        }

                # Crear evento
                summary = f"{sede} - {nombre} - {servicio} - {doctor}"
                description = (
                    f"Sede: {sede} | Paciente: {nombre} | "
                    f"Servicio: {servicio} | Doctor: {doctor}"
                )
                created = create_appointment(summary, description, start_iso, end_iso)

                if created:
                    new_event_id = created.get("id")
                    # Guardar cita en DB (identificar tenant por inbox_id)
                    inbox_id = state.get("inbox_id")
                    tenant = await get_tenant_by_inbox_id(inbox_id) if inbox_id else None
                    if tenant:
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
                            costo_estimado=state.get("costo_estimado", 0.0),
                        )
                    else:
                        logger.warning(f"[DB] Tenant no encontrado para inbox_id={inbox_id} — cita no registrada en DB.")
                    nuevos_datos = {**datos, "event_id": new_event_id}
                    return {
                        **state,
                        "datos_capturados": nuevos_datos,
                        "estado_conversacion": "finalizado",
                    }

            except Exception as e:
                logger.error(f"[Calendar] Error creando cita: {e}")
                return {**state, "error": str(e)}

    return state
