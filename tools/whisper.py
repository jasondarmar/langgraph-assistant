"""
Whisper — transcripción de mensajes de audio desde Chatwoot Active Storage.
El audio llega como URL autenticada de Chatwoot, se descarga y se envía a Whisper.
"""
import logging
import httpx
from app.state import AgentState
from app.ssrf_protection import SSRFProtection
from config.settings import get_settings

logger = logging.getLogger(__name__)


async def transcribe_audio_node(state: AgentState) -> AgentState:
    """
    Nodo de transcripción. Solo se ejecuta si media_type == 'audio'.
    Descarga el audio desde Chatwoot y lo transcribe con OpenAI Whisper.
    Valida la URL contra SSRF attacks.
    """
    if state.get("media_type") != "audio":
        return state

    audio_url = state.get("audio_url")
    if not audio_url:
        logger.warning("[Whisper] media_type=audio pero audio_url es None")
        return {**state, "mensaje_actual": "", "transcription": ""}

    # ─── SSRF Protection ───────────────────────────────────────────────
    is_valid, error_msg = SSRFProtection.validate_audio_url(audio_url)
    if not is_valid:
        logger.error(f"[Whisper] SSRF validation failed: {error_msg}")
        return {
            **state,
            "mensaje_actual": "",
            "transcription": "",
            "error": f"Audio URL no válida: {error_msg}",
        }

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

            # ─── Validar Content-Type ──────────────────────────────────
            content_type = resp.headers.get("content-type", "")
            is_valid_type, type_error = SSRFProtection.validate_content_type(content_type)
            if not is_valid_type:
                logger.error(f"[Whisper] Invalid content-type: {type_error}")
                return {
                    **state,
                    "mensaje_actual": "",
                    "transcription": "",
                    "error": f"Tipo de archivo no válido: {type_error}",
                }

            # ─── Validar tamaño ────────────────────────────────────────
            content_length = resp.headers.get("content-length")
            is_valid_size, size_error = SSRFProtection.validate_file_size(content_length)
            if not is_valid_size:
                logger.error(f"[Whisper] File size validation failed: {size_error}")
                return {
                    **state,
                    "mensaje_actual": "",
                    "transcription": "",
                    "error": f"Archivo demasiado grande: {size_error}",
                }

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
