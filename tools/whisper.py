"""
Whisper — transcripción de mensajes de audio desde Chatwoot Active Storage.
El audio llega como URL autenticada de Chatwoot, se descarga y se envía a Whisper.
"""
import logging
import httpx
from app.state import AgentState
from config.settings import get_settings

logger = logging.getLogger(__name__)


async def transcribe_audio_node(state: AgentState) -> AgentState:
    """
    Nodo de transcripción. Solo se ejecuta si media_type == 'audio'.
    Descarga el audio desde Chatwoot y lo transcribe con OpenAI Whisper.
    """
    if state.get("media_type") != "audio":
        return state

    audio_url = state.get("audio_url")
    if not audio_url:
        logger.warning("[Whisper] media_type=audio pero audio_url es None")
        return {**state, "mensaje_actual": "", "transcription": ""}

    settings = get_settings()

    try:
        # Descargar audio desde Chatwoot (requiere autenticación)
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                audio_url,
                headers={"api_access_token": settings.chatwoot_api_token},
                follow_redirects=True,
            )
            resp.raise_for_status()
            audio_bytes = resp.content

        logger.info(f"[Whisper] Audio descargado: {len(audio_bytes)} bytes")

        # Enviar a OpenAI Whisper
        import openai
        client_oai = openai.AsyncOpenAI(api_key=settings.openai_api_key)

        transcript = await client_oai.audio.transcriptions.create(
            model="whisper-1",
            file=("audio.ogg", audio_bytes, "audio/ogg"),
            language="es",
        )
        text = transcript.text.strip()
        logger.info(f"[Whisper] Transcripción: {text}")

        return {
            **state,
            "transcription": text,
            "mensaje_actual": text,
        }

    except httpx.HTTPStatusError as e:
        logger.error(f"[Whisper] Error descargando audio: {e.response.status_code}")
        return {**state, "transcription": "", "mensaje_actual": "", "error": str(e)}
    except Exception as e:
        logger.error(f"[Whisper] Error inesperado: {e}")
        return {**state, "transcription": "", "mensaje_actual": "", "error": str(e)}
