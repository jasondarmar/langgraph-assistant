"""
DB Repository — operaciones CRUD multi-tenant sobre PostgreSQL.

Todas las funciones son no bloqueantes (async) y tolerantes a fallos:
si la DB no está disponible, registran el error pero no rompen el flujo.
"""
import logging
from datetime import datetime
from typing import Optional
from uuid import UUID

import pytz

from config.database import get_pool

logger = logging.getLogger(__name__)


# ─── Tenants ──────────────────────────────────────────────────────────────────

async def get_tenant_by_inbox_id(inbox_id: int) -> Optional[dict]:
    """Retorna el tenant correspondiente a un inbox_id de Chatwoot."""
    pool = get_pool()
    if not pool:
        return None
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id, slug, name, timezone FROM tenants WHERE inbox_id = $1 AND active = true",
                inbox_id,
            )
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"[DB] get_tenant_by_inbox_id error: {e}")
        return None


# ─── Appointments ─────────────────────────────────────────────────────────────

async def save_appointment(
    tenant_id: UUID,
    wa_id: str,
    nombre_paciente: Optional[str],
    sede: Optional[str],
    servicio: Optional[str],
    doctor: Optional[str],
    fecha_cita: Optional[str],      # "YYYY-MM-DD"
    hora_cita: Optional[str],
    event_id: Optional[str],
    resumen_conversacion: Optional[str],
    modelo_usado: Optional[str],
    tokens_entrada: int,
    tokens_salida: int,
    costo_estimado: float,
) -> Optional[str]:
    """
    Inserta una cita nueva. Retorna el UUID generado o None si falla.
    """
    pool = get_pool()
    if not pool:
        logger.warning("[DB] save_appointment: pool no disponible, skip.")
        return None
    try:
        fecha = None
        if fecha_cita:
            fecha = datetime.strptime(fecha_cita, "%Y-%m-%d").date()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO appointments (
                    tenant_id, wa_id, nombre_paciente, sede, servicio, doctor,
                    fecha_cita, hora_cita, event_id, estado,
                    resumen_conversacion, modelo_usado,
                    tokens_entrada, tokens_salida, costo_estimado
                ) VALUES (
                    $1, $2, $3, $4, $5, $6,
                    $7, $8, $9, 'agendada',
                    $10, $11,
                    $12, $13, $14
                )
                RETURNING id::text
                """,
                tenant_id, wa_id, nombre_paciente, sede, servicio, doctor,
                fecha, hora_cita, event_id,
                resumen_conversacion, modelo_usado,
                tokens_entrada, tokens_salida, costo_estimado,
            )
            appointment_id = row["id"]
            logger.info(f"[DB] Cita guardada: {appointment_id} — {nombre_paciente} ({wa_id})")
            return appointment_id
    except Exception as e:
        logger.error(f"[DB] save_appointment error: {e}")
        return None


async def update_appointment_estado(
    event_id: str,
    estado: str,
    resumen_conversacion: Optional[str] = None,
) -> bool:
    """
    Actualiza el estado de una cita por su event_id de Google Calendar.
    estado: 'agendada' | 'cancelada' | 'completada'
    """
    pool = get_pool()
    if not pool:
        logger.warning("[DB] update_appointment_estado: pool no disponible, skip.")
        return False
    try:
        tz = pytz.timezone("America/Bogota")
        now = datetime.now(tz)

        async with pool.acquire() as conn:
            if resumen_conversacion:
                result = await conn.execute(
                    """
                    UPDATE appointments
                    SET estado = $1, resumen_conversacion = $2, updated_at = $3
                    WHERE event_id = $4
                    """,
                    estado, resumen_conversacion, now, event_id,
                )
            else:
                result = await conn.execute(
                    "UPDATE appointments SET estado = $1, updated_at = $2 WHERE event_id = $3",
                    estado, now, event_id,
                )
            updated = result.split()[-1] != "0"
            if updated:
                logger.info(f"[DB] Cita actualizada a '{estado}': event_id={event_id}")
            else:
                logger.warning(f"[DB] No se encontró cita con event_id={event_id}")
            return updated
    except Exception as e:
        logger.error(f"[DB] update_appointment_estado error: {e}")
        return False
