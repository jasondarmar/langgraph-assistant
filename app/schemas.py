"""
Schemas — validadores Pydantic para datos de entrada.
Previene inyección, overflow, y datos malformados.
"""
import re
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class AppointmentDataValidated(BaseModel):
    """Validación estructurada de datos de cita."""

    nombre_paciente: str = Field(..., min_length=2, max_length=100)
    sede: str = Field(...)
    servicio: str = Field(..., max_length=100)
    doctor: str = Field(..., max_length=100)
    fecha_cita: str = Field(...)
    hora_cita: str = Field(...)
    event_id: Optional[str] = Field(None, max_length=255)

    @field_validator('nombre_paciente')
    @classmethod
    def validate_nombre(cls, v: str) -> str:
        """Valida nombre del paciente."""
        if not v or not v.strip():
            raise ValueError("Nombre no puede estar vacío")

        # Solo letras, números, espacios, guiones, acentos
        if not re.match(r"^[\w\s\-áéíóúñÁÉÍÓÚÑ\.]+$", v):
            raise ValueError("Nombre contiene caracteres inválidos")

        # Prevenir inyección de prompts
        dangerous_patterns = ['"""', "'''", "[SYSTEM", "[ADMIN", "ignore", "bypass"]
        for pattern in dangerous_patterns:
            if pattern.lower() in v.lower():
                raise ValueError("Nombre contiene patrones reservados")

        return v.strip()

    @field_validator('sede')
    @classmethod
    def validate_sede(cls, v: str) -> str:
        """Valida sede (debe ser una de las conocidas)."""
        valid_sedes = {"Bogotá", "La Vega", "Villeta"}
        if v not in valid_sedes:
            raise ValueError(f"Sede inválida. Debe ser una de: {valid_sedes}")
        return v

    @field_validator('servicio')
    @classmethod
    def validate_servicio(cls, v: str) -> str:
        """Valida servicio."""
        if not v or not v.strip():
            raise ValueError("Servicio no puede estar vacío")

        valid_servicios = {
            "Odontología general",
            "Ortodoncia",
            "Blanqueamiento dental",
            "Endodoncia",
            "Prótesis dental",
            "Radiografía dental",
        }

        if v not in valid_servicios:
            raise ValueError(f"Servicio inválido. Debe ser uno de: {valid_servicios}")

        return v

    @field_validator('doctor')
    @classmethod
    def validate_doctor(cls, v: str) -> str:
        """Valida nombre del doctor."""
        if not v or not v.strip():
            raise ValueError("Doctor no puede estar vacío")

        valid_doctors = {
            "Dr. Enrique Luna",
            "Dr. Sebastián Luna",
            "Dra. Mónica González",
        }

        if v not in valid_doctors:
            raise ValueError(f"Doctor inválido. Debe ser uno de: {valid_doctors}")

        return v

    @field_validator('fecha_cita')
    @classmethod
    def validate_fecha(cls, v: str) -> str:
        """Valida fecha de cita."""
        try:
            fecha = datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Formato de fecha inválido. Usa YYYY-MM-DD")

        # No fechas en el pasado
        if fecha < datetime.now():
            raise ValueError("No puedes agendar en fechas pasadas")

        # No más de 1 año en el futuro
        max_date = datetime.now() + timedelta(days=365)
        if fecha > max_date:
            raise ValueError("Fecha demasiado lejana. Máximo 1 año")

        return v

    @field_validator('hora_cita')
    @classmethod
    def validate_hora(cls, v: str) -> str:
        """Valida hora de cita."""
        v_clean = v.lower().strip()

        # Soportar: "14:30", "2:30 pm", "14:30:00", etc.
        v_clean = v_clean.replace(" am", "").replace(" pm", "")

        try:
            time_obj = datetime.strptime(v_clean.split(":")[0] + ":" + v_clean.split(":")[1], "%H:%M")
        except (ValueError, IndexError):
            raise ValueError("Formato de hora inválido. Usa HH:MM")

        # Validar horario clínica: 8AM-6PM lunes-viernes, 8AM-1PM sábado
        hour = time_obj.hour
        if not (8 <= hour < 18):
            raise ValueError("Hora fuera del horario. Disponible 8AM-6PM")

        return v

    @field_validator('event_id')
    @classmethod
    def validate_event_id(cls, v: Optional[str]) -> Optional[str]:
        """Valida event_id de Google Calendar."""
        if not v:
            return None

        # Google Calendar IDs son alfanuméricos
        if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
            raise ValueError("Event ID inválido")

        if len(v) > 255:
            raise ValueError("Event ID demasiado largo")

        return v


class WebhookPayloadValidated(BaseModel):
    """Validación de payload de webhook Chatwoot."""

    conversation_id: int = Field(...)
    inbox_id: int = Field(...)
    wa_id: str = Field(...)
    sender_name: str = Field(..., max_length=100)
    raw_content: Optional[str] = Field(None, max_length=5000)
    audio_url: Optional[str] = Field(None, max_length=2048)

    @field_validator('wa_id')
    @classmethod
    def validate_wa_id(cls, v: str) -> str:
        """Valida WhatsApp ID."""
        # Debe ser 10+ dígitos
        if not re.match(r"^\d{10,}$", v):
            raise ValueError("WhatsApp ID inválido")
        return v

    @field_validator('sender_name')
    @classmethod
    def validate_sender_name(cls, v: str) -> str:
        """Valida nombre del remitente."""
        if not v or not v.strip():
            raise ValueError("Sender name no puede estar vacío")

        # Prevenir inyección
        if any(p in v.lower() for p in ['eval', 'exec', 'import', '__(', '__']):
            raise ValueError("Sender name contiene patrones sospechosos")

        return v[:100]

    @field_validator('raw_content')
    @classmethod
    def validate_content(cls, v: Optional[str]) -> Optional[str]:
        """Valida contenido del mensaje."""
        if not v:
            return None

        # Limitar tamaño
        if len(v) > 5000:
            raise ValueError("Mensaje demasiado largo")

        return v[:5000]

    @field_validator('audio_url')
    @classmethod
    def validate_audio_url(cls, v: Optional[str]) -> Optional[str]:
        """Valida URL de audio."""
        if not v:
            return None

        if len(v) > 2048:
            raise ValueError("URL demasiado larga")

        # Debe ser URL válida
        if not v.startswith(("http://", "https://")):
            raise ValueError("URL de audio inválida")

        return v
