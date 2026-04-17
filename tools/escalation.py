"""
Escalation — escalamiento a agente humano vía API de Chatwoot.
Asigna la conversación, cambia estado a 'pending' y envía nota privada.
"""
import logging
import os
import httpx
from app.state import AgentState
from app.audit_log import AuditLogger
from config.settings import get_settings

# Ruta base de fotos relativa al directorio del proyecto
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "doctors")

DOCTOR_PHOTOS: dict[str, str] = {
    "Dr. Enrique Luna":    os.path.join(_ASSETS_DIR, "dr_enrique_luna.jpg"),
    "Dr. Sebastián Luna":  os.path.join(_ASSETS_DIR, "dr_sebastian_luna.jpg"),
    "Dra. Mónica González": os.path.join(_ASSETS_DIR, "dra_monica_gonzalez.jpg"),
}

logger = logging.getLogger(__name__)


def _chatwoot_headers() -> dict:
    settings = get_settings()
    return {
        "api_access_token": settings.chatwoot_api_token,
        "Content-Type": "application/json",
    }


def _base_url() -> str:
    settings = get_settings()
    return f"{settings.chatwoot_base_url}/api/v1/accounts/{settings.chatwoot_account_id}"


async def send_doctor_photo(conv_id: int, doctor: str) -> bool:
    """
    Envía la foto del doctor como adjunto en la conversación de Chatwoot.
    Retorna True si el envío fue exitoso.
    """
    photo_path = DOCTOR_PHOTOS.get(doctor)
    if not photo_path:
        logger.warning(f"[DoctorPhoto] Sin foto registrada para: {doctor}")
        return False
    if not os.path.isfile(photo_path):
        logger.warning(f"[DoctorPhoto] Archivo no encontrado: {photo_path}")
        return False

    base = _base_url()
    headers = {"api_access_token": _chatwoot_headers()["api_access_token"]}

    try:
        with open(photo_path, "rb") as f:
            file_bytes = f.read()

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{base}/conversations/{conv_id}/messages",
                headers=headers,
                data={"message_type": "outgoing", "private": "false"},
                files={"attachments[]": (os.path.basename(photo_path), file_bytes, "image/jpeg")},
            )
            resp.raise_for_status()

        logger.info(f"[DoctorPhoto] Foto enviada para {doctor} en conv {conv_id}")
        return True

    except Exception as e:
        logger.error(f"[DoctorPhoto] Error enviando foto de {doctor}: {e}")
        return False


async def escalate_to_human(state: AgentState) -> AgentState:
    """
    Nodo de escalación humana. Se ejecuta cuando requiere_humano=True.
    1. Asigna la conversación al agente admin (id=1)
    2. Cambia estado a 'pending'
    3. Envía nota privada con el resumen al agente
    Registra la escalación en el audit log.
    """
    if not state.get("requiere_humano", False):
        return state

    conv_id = state.get("conversation_id")
    wa_id = state.get("wa_id", "")
    razon_escalacion = state.get("razon_escalacion", "Bot unable to handle - requires human intervention")
    resumen = state.get("resumen_conversacion", "").strip()
    if not resumen:
        # Fallback: construir resumen básico con los datos capturados
        datos = state.get("datos_capturados", {})
        intent = state.get("intent", "desconocida")
        nombre = datos.get("nombre_paciente", "desconocido")
        resumen = (
            f"Intención detectada: {intent}. "
            f"Paciente: {nombre}. "
            "No se generó resumen automático — revisar historial de la conversación."
        )

    if not conv_id:
        logger.error("[Escalation] conversation_id es None, no se puede escalar")
        return state

    # Audit logging
    AuditLogger.log_escalation(
        wa_id=wa_id,
        conv_id=conv_id,
        razon=razon_escalacion,
    )

    base = _base_url()
    headers = _chatwoot_headers()

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. Asignar al agente admin
        try:
            resp = await client.post(
                f"{base}/conversations/{conv_id}/assignments",
                headers=headers,
                json={"assignee_id": 1},
            )
            resp.raise_for_status()
            logger.info(f"[Escalation] Conversación {conv_id} asignada al admin")
        except Exception as e:
            logger.error(f"[Escalation] Error asignando: {e}")

        # 2. Cambiar estado a pending
        try:
            resp = await client.post(
                f"{base}/conversations/{conv_id}/toggle_status",
                headers=headers,
                json={"status": "pending"},
            )
            resp.raise_for_status()
            logger.info(f"[Escalation] Conversación {conv_id} → pending")
        except Exception as e:
            logger.error(f"[Escalation] Error cambiando estado: {e}")

        # 3. Nota privada con resumen
        try:
            nota = (
                f"🤖 *Resumen de la conversación con el asistente Yanny:*\n\n"
                f"{resumen}\n\n"
                f"_El paciente solicitó atención humana o se detectó una situación que requiere intervención._"
            )
            resp = await client.post(
                f"{base}/conversations/{conv_id}/messages",
                headers=headers,
                json={
                    "content": nota,
                    "message_type": "outgoing",
                    "private": True,
                },
            )
            resp.raise_for_status()
            logger.info(f"[Escalation] Nota privada enviada en conversación {conv_id}")
        except Exception as e:
            logger.error(f"[Escalation] Error enviando nota: {e}")

    return state
