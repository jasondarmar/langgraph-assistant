"""
Data Retention — GDPR compliance. Auto-delete de datos viejos.
"""
import logging
from datetime import datetime, timedelta
import pytz

from tools.db_repository import get_pool
from app.audit_log import AuditLogger

logger = logging.getLogger(__name__)


class DataRetention:
    """Gestiona retención de datos según GDPR."""

    # Retención por defecto (en días)
    RETENTION_APPOINTMENTS = 90  # 3 meses después de completada
    RETENTION_CONVERSATION = 30  # 1 mes después de resuelto
    RETENTION_AUDIT_LOG = 365  # 1 año

    @staticmethod
    async def cleanup_expired_data() -> dict:
        """
        Limpia datos expirados según políticas de retención.

        Retorna:
            {
                "appointments_deleted": int,
                "conversations_deleted": int,
                "total_deleted": int,
            }
        """
        pool = get_pool()
        if not pool:
            logger.warning("[DataRetention] Database pool no disponible")
            return {"appointments_deleted": 0, "conversations_deleted": 0}

        tz = pytz.timezone("America/Bogota")
        now = datetime.now(tz)
        results = {"appointments_deleted": 0, "conversations_deleted": 0}

        try:
            async with pool.acquire() as conn:
                # 1. Limpiar citas completadas hace más de RETENTION_APPOINTMENTS
                cutoff_appointments = now - timedelta(
                    days=DataRetention.RETENTION_APPOINTMENTS
                )
                deleted_appointments = await conn.execute(
                    """
                    DELETE FROM appointments
                    WHERE estado = 'completada'
                    AND updated_at < $1
                    """,
                    cutoff_appointments,
                )
                results["appointments_deleted"] = deleted_appointments.strip()

                # 2. Limpiar conversaciones resueltas
                cutoff_conversations = now - timedelta(
                    days=DataRetention.RETENTION_CONVERSATION
                )
                deleted_conversations = await conn.execute(
                    """
                    DELETE FROM conversations
                    WHERE status = 'resolved'
                    AND updated_at < $1
                    """,
                    cutoff_conversations,
                )
                results["conversations_deleted"] = deleted_conversations.strip()

                results["total_deleted"] = (
                    results["appointments_deleted"]
                    + results["conversations_deleted"]
                )

                logger.info(
                    f"[DataRetention] Cleanup completed: "
                    f"appointments={results['appointments_deleted']}, "
                    f"conversations={results['conversations_deleted']}"
                )

        except Exception as e:
            logger.error(f"[DataRetention] Error during cleanup: {e}")

        return results

    @staticmethod
    async def delete_user_data(wa_id: str) -> bool:
        """
        Borra TODOS los datos de un usuario (GDPR Right-to-be-forgotten).

        Args:
            wa_id: WhatsApp ID del usuario

        Returns:
            True si exitoso
        """
        pool = get_pool()
        if not pool:
            logger.warning("[DataRetention] Database pool no disponible")
            return False

        try:
            async with pool.acquire() as conn:
                # Iniciar transacción
                async with conn.transaction():
                    # 1. Borrar citas
                    appointments_deleted = await conn.execute(
                        "DELETE FROM appointments WHERE wa_id = $1",
                        wa_id,
                    )

                    # 2. Borrar conversaciones
                    conversations_deleted = await conn.execute(
                        "DELETE FROM conversations WHERE wa_id = $1",
                        wa_id,
                    )

                    # 3. Registrar en audit log
                    AuditLogger.log_data_deleted(
                        wa_id=wa_id,
                        tipo_datos="all",
                        cantidad=int(appointments_deleted) + int(conversations_deleted),
                    )

                    logger.warning(
                        f"[DataRetention] GDPR deletion for wa_id={wa_id}: "
                        f"appointments={appointments_deleted}, "
                        f"conversations={conversations_deleted}"
                    )

                    return True

        except Exception as e:
            logger.error(
                f"[DataRetention] Error deleting user data for wa_id={wa_id}: {e}"
            )
            return False

    @staticmethod
    def get_retention_policy() -> dict:
        """Retorna la política de retención actual."""
        return {
            "appointments_days": DataRetention.RETENTION_APPOINTMENTS,
            "conversations_days": DataRetention.RETENTION_CONVERSATION,
            "audit_log_days": DataRetention.RETENTION_AUDIT_LOG,
            "description": "GDPR-compliant data retention policy",
        }
