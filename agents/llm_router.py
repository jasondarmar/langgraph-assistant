"""
LLM Router — selección dinámica de modelo según complejidad de la intención.
"""
import logging
from langchain_openai import ChatOpenAI
from config.models import TIER1_INTENTS, TIER2_INTENTS, MODELS, estimate_cost
from config.settings import get_settings

logger = logging.getLogger(__name__)


def get_model_for_intent(intent: str | None) -> tuple[ChatOpenAI, str]:
    """
    Retorna el modelo adecuado y su ID según la intención detectada.
    - Tier 1 (gpt-4o-mini): intenciones simples ~80% de los casos
    - Tier 2 (gpt-4o): agendamiento, modificación, emergencias ~20%
    """
    settings = get_settings()

    if intent in TIER2_INTENTS:
        model_id = settings.llm_tier2_model
        tier = "tier2"
    else:
        model_id = settings.llm_tier1_model
        tier = "tier1"

    logger.info(f"[LLM Router] intent={intent} → {tier} ({model_id})")

    model = ChatOpenAI(
        model=model_id,
        temperature=settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        api_key=settings.openai_api_key,
    )
    return model, model_id


def log_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Loguea y retorna el costo estimado de la llamada."""
    cost = estimate_cost(model_id, input_tokens, output_tokens)
    logger.info(
        f"[Cost] model={model_id} "
        f"input={input_tokens} output={output_tokens} "
        f"cost=${cost:.6f}"
    )
    return cost
