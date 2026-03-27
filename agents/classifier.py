"""
Classifier — nodo que clasifica la intención del mensaje del paciente.
Siempre usa gpt-4o-mini (barato y rápido para clasificación).
"""
import logging
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from app.state import AgentState
from config.prompts import INTENT_CLASSIFIER_PROMPT
from config.settings import get_settings

logger = logging.getLogger(__name__)


def classify_intent(state: AgentState) -> AgentState:
    """
    Nodo clasificador. Usa gpt-4o-mini para detectar la intención
    del mensaje actual del paciente.
    """
    # Si human_mode activo, no clasificar — el humano atiende
    if state.get("human_mode", False):
        logger.info("[Classifier] human_mode=True, skip classification")
        return {**state, "intent": "human_mode", "skip_llm": True}

    mensaje = state.get("mensaje_actual", "")
    if not mensaje:
        logger.warning("[Classifier] mensaje_actual vacío")
        return {**state, "intent": "otro", "skip_llm": False}

    settings = get_settings()
    model = ChatOpenAI(
        model=settings.llm_tier1_model,
        temperature=0.0,
        max_tokens=20,
        api_key=settings.openai_api_key,
    )

    try:
        response = model.invoke([
            SystemMessage(content=INTENT_CLASSIFIER_PROMPT),
            HumanMessage(content=mensaje),
        ])
        intent = response.content.strip().lower()

        # Validar que sea una intención conocida
        valid_intents = {
            "saludo", "consulta_servicios", "consulta_doctores",
            "consulta_sedes", "agendar_cita", "modificar_cita",
            "cancelar_cita", "despedida", "emergencia",
            "fuera_de_alcance", "otro",
        }
        if intent not in valid_intents:
            logger.warning(f"[Classifier] Intención desconocida: {intent}, usando 'otro'")
            intent = "otro"

        logger.info(f"[Classifier] intent={intent} para mensaje: {mensaje[:50]}")
        return {**state, "intent": intent, "skip_llm": False}

    except Exception as e:
        logger.error(f"[Classifier] Error: {e}")
        return {**state, "intent": "otro", "skip_llm": False, "error": str(e)}
