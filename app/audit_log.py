"""
Audit Log — registra todas las operaciones sensibles para compliance.
"""
import logging
import json
from datetime import datetime
from typing import Optional, Any
import pytz

logger = logging.getLogger(__name__)


class AuditLogger:
    """Registra eventos sensibles para auditoría."""

    # Eventos auditables
    EVENT_APPOINTMENT_CREATED = "appointment_created"
    EVENT_APPOINTMENT_MODIFIED = "appointment_modified"
    EVENT_APPOINTMENT_CANCELLED = "appointment_cancelled"
    EVENT_ESCALATION = "escalation_to_human"
    EVENT_SESSION_STARTED = "session_started"
    EVENT_SESSION_ENDED = "session_ended"
    EVENT_DATA_DELETED = "data_deleted"
    EVENT_ERROR = "error"

    @staticmethod
    def log_event(
        event_type: str,
        wa_id: str,
        conv_id: Optional[int] = None,
        details: Optional[dict] = None,
        severity: str = "INFO",
    ) -> None:
        """
        Registra un evento auditable.

        Args:
            event_type: Tipo de evento (EVENT_*)
            wa_id: WhatsApp ID del usuario
            conv_id: Conversation ID en Chatwoot
            details: Detalles adicionales del evento
            severity: Severidad del evento (INFO, WARNING, ERROR, CRITICAL)
        """
        tz = pytz.timezone("America/Bogota")
        timestamp = datetime.now(tz).isoformat()

        audit_entry = {
            "timestamp": timestamp,
            "event_type": event_type,
            "wa_id": wa_id,
            "conv_id": conv_id,
            "severity": severity,
            "details": details or {},
        }

        # Log en JSON para fácil parsing
        log_line = json.dumps(audit_entry)

        if severity == "CRITICAL":
            logger.critical(f"[AUDIT] {log_line}")
        elif severity == "ERROR":
            logger.error(f"[AUDIT] {log_line}")
        elif severity == "WARNING":
            logger.warning(f"[AUDIT] {log_line}")
        else:
            logger.info(f"[AUDIT] {log_line}")

    @staticmethod
    def log_appointment_created(
        wa_id: str,
        conv_id: int,
        nombre: str,
        fecha: str,
        doctor: str,
        costo: float,
        event_id: str,
    ) -> None:
        """Registra creación de cita."""
        AuditLogger.log_event(
            event_type=AuditLogger.EVENT_APPOINTMENT_CREATED,
            wa_id=wa_id,
            conv_id=conv_id,
            details={
                "nombre_paciente": nombre,
                "fecha_cita": fecha,
                "doctor": doctor,
                "costo": costo,
                "event_id": event_id,
            },
            severity="INFO",
        )

    @staticmethod
    def log_appointment_modified(
        wa_id: str,
        conv_id: int,
        event_id: str,
        cambios: dict,
    ) -> None:
        """Registra modificación de cita."""
        AuditLogger.log_event(
            event_type=AuditLogger.EVENT_APPOINTMENT_MODIFIED,
            wa_id=wa_id,
            conv_id=conv_id,
            details={
                "event_id": event_id,
                "cambios": cambios,
            },
            severity="INFO",
        )

    @staticmethod
    def log_appointment_cancelled(
        wa_id: str,
        conv_id: int,
        event_id: str,
        motivo: Optional[str] = None,
    ) -> None:
        """Registra cancelación de cita."""
        AuditLogger.log_event(
            event_type=AuditLogger.EVENT_APPOINTMENT_CANCELLED,
            wa_id=wa_id,
            conv_id=conv_id,
            details={
                "event_id": event_id,
                "motivo": motivo,
            },
            severity="INFO",
        )

    @staticmethod
    def log_escalation(
        wa_id: str,
        conv_id: int,
        razon: str,
    ) -> None:
        """Registra escalación a humano."""
        AuditLogger.log_event(
            event_type=AuditLogger.EVENT_ESCALATION,
            wa_id=wa_id,
            conv_id=conv_id,
            details={
                "razon": razon,
            },
            severity="WARNING",
        )

    @staticmethod
    def log_data_deleted(
        wa_id: str,
        tipo_datos: str,
        cantidad: int,
    ) -> None:
        """Registra borrado de datos (GDPR)."""
        AuditLogger.log_event(
            event_type=AuditLogger.EVENT_DATA_DELETED,
            wa_id=wa_id,
            conv_id=None,
            details={
                "tipo_datos": tipo_datos,
                "cantidad_registros": cantidad,
                "razon": "GDPR data retention policy",
            },
            severity="WARNING",
        )

    @staticmethod
    def log_error(
        wa_id: str,
        conv_id: Optional[int],
        error_type: str,
        error_msg: str,
    ) -> None:
        """Registra error."""
        AuditLogger.log_event(
            event_type=AuditLogger.EVENT_ERROR,
            wa_id=wa_id,
            conv_id=conv_id,
            details={
                "error_type": error_type,
                "error_message": error_msg,
            },
            severity="ERROR",
        )
