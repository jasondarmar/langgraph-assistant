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
from app.audit_log import AuditLogger
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


def search_appointments_by_name(
    patient_partial_name: str,
    days_back: int = 30,
    days_forward: int = 90,
) -> list[dict]:
    """
    Busca citas en Google Calendar por nombre parcial del paciente.
    Usa fuzzy matching: 'José Pérez' coincide con 'José Antonio Pérez'.

    Retorna lista de eventos que coinciden, ordenados por fecha.
    Cada evento incluye: id, summary, start, description, nombre_paciente.
    """
    settings = get_settings()
    try:
        service = _get_calendar_service()
        tz = pytz.timezone("America/Bogota")
        now = datetime.now(tz)

        # Rango de búsqueda: últimos 30 días y próximos 90 días
        time_min = (now - timedelta(days=days_back)).isoformat()
        time_max = (now + timedelta(days=days_forward)).isoformat()

        result = service.events().list(
            calendarId=settings.google_calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = result.get("items", [])
        matches = []

        # Normalizar nombre de búsqueda: dividir en partes y lowercase
        search_parts = [p.lower().strip() for p in patient_partial_name.split()]
        if not search_parts or not search_parts[0]:
            return []

        for ev in events:
            summary = ev.get("summary", "")
            description = ev.get("description", "")

            # Extraer nombre del paciente del summary: "Sede - Nombre - Servicio - Doctor"
            # O del description: "Sede: ... | Paciente: NombrePaciente | ..."
            patient_name = ""

            if "Paciente:" in description:
                # Extraer del description
                try:
                    parts = description.split("|")
                    for part in parts:
                        if "Paciente:" in part:
                            patient_name = part.split("Paciente:")[1].strip()
                            break
                except Exception:
                    pass

            if not patient_name and summary:
                # Fallback: extraer del summary (segundo elemento)
                try:
                    summary_parts = summary.split(" - ")
                    if len(summary_parts) >= 2:
                        patient_name = summary_parts[1].strip()
                except Exception:
                    pass

            if not patient_name:
                continue

            # Fuzzy matching: todas las partes del nombre de búsqueda deben estar en el nombre
            patient_name_lower = patient_name.lower()
            if all(part in patient_name_lower for part in search_parts):
                matches.append({
                    "id": ev.get("id"),
                    "summary": summary,
                    "start": ev.get("start", {}).get("dateTime"),
                    "description": description,
                    "nombre_paciente": patient_name,
                })

        logger.info(f"[Calendar] search_appointments_by_name('{patient_partial_name}'): {len(matches)} coincidencias")
        return matches

    except Exception as e:
        logger.error(f"[Calendar] Error en search_appointments_by_name: {e}")
        return []


def delete_appointment(event_id: str) -> bool:
    """
    Elimina un evento del calendario por su ID.
    Retorna True si fue eliminado, False si falló.
    Registra la cancelación en el audit log.
    """
    settings = get_settings()
    try:
        service = _get_calendar_service()
        service.events().delete(
            calendarId=settings.google_calendar_id,
            eventId=event_id,
        ).execute()
        logger.info(f"[Calendar] Evento eliminado: {event_id}")

        # Audit logging
        AuditLogger.log_appointment_cancelled(
            wa_id="system",
            conv_id=None,
            event_id=event_id,
            motivo="User requested cancellation",
        )

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

        # Rechazar domingos
        if dt_start.weekday() == 6:
            logger.warning(f"[Calendar] Domingo rechazado: {dt_start.date()}")
            return {
                **state,
                "datos_capturados": {**datos, "fecha_cita": None, "hora_cita": None},
                "estado_conversacion": "en_proceso",
                "error": "Domingo no disponible",
                "respuesta": (
                    "Los domingos no tenemos atención 😊. "
                    "Estamos disponibles de lunes a sábado. ¿Qué otro día te queda bien?"
                ),
            }

        # Rechazar fechas en el pasado
        tz = pytz.timezone("America/Bogota")
        if dt_start < datetime.now(tz).replace(tzinfo=None):
            logger.warning(f"[Calendar] Fecha en el pasado rechazada: {dt_start}")
            return {
                **state,
                "datos_capturados": {**datos, "fecha_cita": None, "hora_cita": None},
                "estado_conversacion": "en_proceso",
                "error": "Fecha en el pasado",
                "respuesta": (
                    "Esa fecha ya pasó 😊. Por favor indícame una fecha futura "
                    "para agendar tu cita."
                ),
            }

        # Rechazar horarios fuera del rango permitido (8AM–6PM)
        if not (8 <= dt_start.hour < 18):
            logger.warning(f"[Calendar] Horario fuera de rango rechazado: {dt_start.hour}:{dt_start.minute:02d}")
            return {
                **state,
                "datos_capturados": {**datos, "hora_cita": None},
                "estado_conversacion": "en_proceso",
                "error": "Horario fuera de rango",
                "respuesta": (
                    "Nuestro horario de atención es de 8:00 AM a 6:00 PM, "
                    "lunes a sábado 😊. ¿A qué hora te queda mejor dentro de ese rango?"
                ),
            }
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
        wa_id = state.get("wa_id", "")
        conv_id = state.get("conversation_id")
        tenant = await get_tenant_by_inbox_id(inbox_id) if inbox_id else None
        if tenant:
            # costo_acumulado incluye todos los turnos de la conversación;
            # si no está disponible, usamos solo el del turno actual como fallback
            costo_total = state.get("costo_acumulado") or state.get("costo_estimado", 0.0)
            # Sumar el turno actual al acumulado (aún no se sumó en save_session_node)
            costo_total += state.get("costo_estimado", 0.0)
            await save_appointment(
                tenant_id=tenant["id"],
                wa_id=wa_id,
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

        # Formatear hora para el mensaje de confirmación
        try:
            hora_dt = datetime.strptime(hora_clean, "%H:%M")
            hora_fmt = hora_dt.strftime("%I:%M %p").lstrip("0")
        except Exception:
            hora_fmt = hora

        return {
            **state,
            "datos_capturados": {**datos, "event_id": new_event_id},
            "estado_conversacion": "finalizado",
            "cita_recien_creada": True,
            "respuesta": (
                f"✅ ¡Tu cita ha sido confirmada, {nombre}!\n"
                f"📅 Fecha: {fecha}\n"
                f"🕐 Hora: {hora_fmt}\n"
                f"👨‍⚕️ Doctor: {doctor}\n"
                f"📍 Sede: {sede}\n"
                f"🦷 Servicio: {servicio}\n\n"
                "Te esperamos 😊"
            ),
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
            # Sin event_id: intentar buscar citas por nombre
            nombre_parcial = datos.get("nombre_paciente", "")
            intent = state.get("intent", "")

            if intent in ("cancelar_cita", "modificar_cita") and nombre_parcial and nombre_parcial not in _NULL_VALS:
                # Buscar citas coincidentes
                matches = search_appointments_by_name(nombre_parcial)

                if len(matches) == 1:
                    # Solo una coincidencia → usar directamente
                    event_id = matches[0]["id"]
                    logger.info(f"[Calendar] Única coincidencia encontrada: {matches[0]['nombre_paciente']}")
                    # Continuar con el delete
                elif len(matches) > 1:
                    # Múltiples coincidencias → pedir que elija
                    opciones = []
                    for i, m in enumerate(matches, 1):
                        fecha = m.get("start", "").split("T")[0] if m.get("start") else "fecha desconocida"
                        hora = m.get("start", "").split("T")[1][:5] if m.get("start") else "hora desconocida"
                        opciones.append(
                            f"{i}️⃣ {m['nombre_paciente']} - {m['summary'].split(' - ')[2] if ' - ' in m['summary'] else 'Servicio'} - {fecha} {hora}"
                        )

                    respuesta = (
                        "Encontré múltiples citas a tu nombre. ¿Cuál deseas cancelar?\n\n" +
                        "\n".join(opciones) +
                        "\n\nResponde con el número (ej: 1️⃣)"
                    )
                    logger.info(f"[Calendar] Múltiples coincidencias encontradas: {len(matches)}")
                    return {
                        **state,
                        "respuesta": respuesta,
                        "accion_calendario": None,
                        "pending_cancellation_matches": matches,
                    }
                else:
                    # Sin coincidencias
                    logger.warning(f"[Calendar] Sin coincidencias para '{nombre_parcial}'")
                    return {
                        **state,
                        "datos_capturados": {},
                        "estado_conversacion": "en_proceso",
                        "accion_calendario": None,
                        "respuesta": f"No encontré citas a nombre de '{nombre_parcial}'. Por favor, proporciona más detalles (nombre completo o fecha). 😊",
                    }

            else:
                logger.warning("[Calendar] accion=delete sin event_id y sin nombre — ignorando delete")
                return {
                    **state,
                    "accion_calendario": None,
                    "respuesta": "No encontré una cita activa en tu nombre. ¿Te gustaría agendar una nueva cita? 😊",
                }

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

        # Solo sobreescribir fecha_cita si el usuario mencionó una fecha
        # explícitamente en ESTE turno (fecha_calculada_turno).
        # Si el usuario solo cambió la hora ("el mismo sábado pero más temprano"),
        # fecha_calculada_turno será None y respetamos la fecha que ya está en datos.
        # Usar la fecha de sesión (fecha_calculada) solo como último recurso
        # cuando fecha_cita está completamente vacía.
        fecha_calculada_turno = state.get("fecha_calculada_turno")
        if fecha_calculada_turno and fecha_calculada_turno not in _NULL_VALS:
            logger.info(
                f"[Calendar] Modificación: fecha explícita en este turno "
                f"{nuevos_datos.get('fecha_cita')} → {fecha_calculada_turno}"
            )
            nuevos_datos["fecha_cita"] = fecha_calculada_turno
        elif nuevos_datos.get("fecha_cita") in _NULL_VALS:
            # fecha_cita está vacía — intentar con la de sesión como fallback
            fecha_calculada = state.get("fecha_calculada")
            if fecha_calculada and fecha_calculada not in _NULL_VALS:
                logger.info(
                    f"[Calendar] Modificación: fecha_cita vacía, usando sesión: {fecha_calculada}"
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
                result["cita_recien_creada"] = True
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
