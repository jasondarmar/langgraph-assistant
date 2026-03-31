"""
AgentState — estado compartido entre todos los nodos del grafo LangGraph.
"""
from typing import TypedDict, Optional, Literal
from langchain_core.messages import BaseMessage


class DatosCita(TypedDict, total=False):
    nombre_paciente: Optional[str]
    sede: Optional[str]           # Bogotá | La Vega | Villeta
    servicio: Optional[str]
    doctor: Optional[str]
    fecha_cita: Optional[str]     # YYYY-MM-DD
    hora_cita: Optional[str]
    event_id: Optional[str]


class AgentState(TypedDict, total=False):
    # ─── Entrada desde Chatwoot ──────────────────────────────────────────
    conversation_id: int
    inbox_id: int
    wa_id: str                    # número WhatsApp sin +
    sender_name: str
    raw_content: Optional[str]    # texto o None si es audio
    audio_url: Optional[str]      # URL de Chatwoot Active Storage
    media_type: Literal["text", "audio", "unknown"]

    # ─── Procesamiento ───────────────────────────────────────────────────
    transcription: Optional[str]  # texto del audio transcrito
    mensaje_actual: str           # mensaje final (texto o transcripción)

    # ─── Contexto de sesión (desde Redis/memoria) ────────────────────────
    historial: list[BaseMessage]
    historial_texto: str
    active_session: bool
    human_mode: bool
    fecha_actual: str             # YYYY-MM-DD
    fecha_actual_texto: str       # "martes 25 de marzo de 2026"
    fecha_calculada: Optional[str]
    datos_capturados: DatosCita

    # ─── Salida del agente ───────────────────────────────────────────────
    intent: Optional[str]
    respuesta: Optional[str]
    estado_conversacion: Literal["inicio", "en_proceso", "datos_completos", "finalizado"]
    accion_calendario: Optional[Literal["delete"]]
    requiere_humano: bool
    resumen_conversacion: str
    modelo_usado: Optional[str]
    tokens_entrada: int
    tokens_salida: int
    costo_estimado: float         # costo del turno actual
    costo_acumulado: float        # suma de todos los turnos de la conversación

    # ─── Control de flujo ────────────────────────────────────────────────
    error: Optional[str]
    skip_llm: bool                # True si human_mode activo
