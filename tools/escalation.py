"""
Escalation — escalamiento a agente humano vía API de Chatwoot.
Asigna la conversación, cambia estado a 'pending' y envía nota privada.
"""
import logging
import httpx
from app.state import AgentState
from config.settings import get_settings

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


async def escalate_to_human(state: AgentState) -> AgentState:
    """
    Nodo de escalación humana. Se ejecuta cuando requiere_humano=True.
    1. Asigna la conversación al agente admin (id=1)
    2. Cambia estado a 'pending'
    3. Envía nota privada con el resumen al agente
    """
    if not state.get("requiere_humano", False):
        return state

    conv_id = state.get("conversation_id")
    resumen = state.get("resumen_conversacion", "Sin resumen disponible.")

    if not conv_id:
        logger.error("[Escalation] conversation_id es None, no se puede escalar")
        return state

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
