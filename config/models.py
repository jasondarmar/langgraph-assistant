"""
Models — configuración de modelos LLM y costos por token.
"""
from dataclasses import dataclass

# Precios aproximados USD por 1M tokens (Marzo 2026)
MODEL_COSTS = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4o":      {"input": 2.50, "output": 10.00},
    "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
}

# Intenciones que van a tier 1 (modelo económico)
TIER1_INTENTS = {
    "saludo",
    "despedida",
    "consulta_servicios",
    "consulta_doctores",
    "consulta_sedes",
    "fuera_de_alcance",
    "otro",
}

# Intenciones que van a tier 2 (modelo full)
TIER2_INTENTS = {
    "agendar_cita",
    "modificar_cita",
    "cancelar_cita",
    "emergencia",
}


@dataclass
class ModelConfig:
    model_id: str
    tier: int
    description: str


MODELS = {
    "tier1": ModelConfig(
        model_id="gpt-4o-mini",
        tier=1,
        description="Saludos, consultas simples, información general",
    ),
    "tier2": ModelConfig(
        model_id="gpt-4o",
        tier=2,
        description="Agendamiento, modificación, cancelación, emergencias",
    ),
}


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Estima el costo en USD de una llamada al modelo."""
    if model_id not in MODEL_COSTS:
        return 0.0
    costs = MODEL_COSTS[model_id]
    return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1_000_000
