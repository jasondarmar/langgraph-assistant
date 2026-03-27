"""
Tests del agente dental — pruebas de integración y escenarios.
Ejecutar: pytest tests/ -v
Para prueba rápida sin API: pytest tests/ -v -k "not integration"
"""
import json
import pytest
import asyncio
from pathlib import Path
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock, MagicMock


# ─── Tests unitarios del router ──────────────────────────────────────────────
def test_router_tier1_for_simple_intents():
    from agents.llm_router import get_model_for_intent
    _, model_id = get_model_for_intent("saludo")
    assert "mini" in model_id


def test_router_tier2_for_complex_intents():
    from agents.llm_router import get_model_for_intent
    _, model_id = get_model_for_intent("agendar_cita")
    assert model_id in ("gpt-4o", "claude-sonnet-4-20250514")


def test_router_tier1_for_unknown_intent():
    from agents.llm_router import get_model_for_intent
    _, model_id = get_model_for_intent("unknown_intent")
    assert "mini" in model_id


# ─── Tests de knowledge base ─────────────────────────────────────────────────
def test_knowledge_base_services():
    from tools.knowledge_base import get_services
    services = get_services()
    assert "Odontología general" in services
    assert "Ortodoncia" in services
    assert len(services) == 6


def test_knowledge_base_doctors():
    from tools.knowledge_base import get_doctors
    doctors = get_doctors()
    assert "Dr. Enrique Luna" in doctors
    assert "Dra. Mónica González" in doctors
    assert len(doctors) == 3


def test_knowledge_base_sedes():
    from tools.knowledge_base import get_sedes, is_valid_sede
    sedes = get_sedes()
    assert "Bogotá" in sedes
    assert "La Vega" in sedes
    assert "Villeta" in sedes
    assert is_valid_sede("Bogotá")
    assert not is_valid_sede("Medellín")


def test_knowledge_base_valid_service():
    from tools.knowledge_base import is_valid_service
    assert is_valid_service("Ortodoncia")
    assert is_valid_service("blanqueamiento")
    assert not is_valid_service("Cirugía plástica")


def test_knowledge_base_valid_doctor():
    from tools.knowledge_base import is_valid_doctor
    assert is_valid_doctor("Dr. Enrique Luna")
    assert is_valid_doctor("Dra. Mónica González")
    assert not is_valid_doctor("Dr. Juan Pérez")


# ─── Tests de cálculo de fechas ──────────────────────────────────────────────
def test_fecha_manana():
    from agents.responder import _calcular_fecha
    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone("America/Bogota")
    hoy = datetime.now(tz).strftime("%Y-%m-%d")
    resultado = _calcular_fecha("quiero para mañana", hoy)
    esperado = (datetime.now(tz) + timedelta(days=1)).strftime("%Y-%m-%d")
    assert resultado == esperado


def test_fecha_hoy():
    from agents.responder import _calcular_fecha
    from datetime import datetime
    import pytz
    tz = pytz.timezone("America/Bogota")
    hoy = datetime.now(tz).strftime("%Y-%m-%d")
    resultado = _calcular_fecha("lo necesito para hoy", hoy)
    assert resultado == hoy


def test_fecha_pasado_manana():
    from agents.responder import _calcular_fecha
    from datetime import datetime, timedelta
    import pytz
    tz = pytz.timezone("America/Bogota")
    hoy = datetime.now(tz).strftime("%Y-%m-%d")
    resultado = _calcular_fecha("para pasado mañana", hoy)
    esperado = (datetime.now(tz) + timedelta(days=2)).strftime("%Y-%m-%d")
    assert resultado == esperado


# ─── Tests de costo ──────────────────────────────────────────────────────────
def test_cost_estimation():
    from config.models import estimate_cost
    cost = estimate_cost("gpt-4o-mini", 1000, 200)
    assert cost > 0
    assert cost < 0.01  # Menos de $0.01 por mensaje típico


def test_cost_tier2_more_expensive():
    from config.models import estimate_cost
    cost_mini = estimate_cost("gpt-4o-mini", 1000, 200)
    cost_full = estimate_cost("gpt-4o", 1000, 200)
    assert cost_full > cost_mini


# ─── Tests de memoria ────────────────────────────────────────────────────────
def test_memory_save_and_get():
    from app.memory import save_session, get_session, clear_session
    wa_id = "test_573000000000"
    session = {"datos_capturados": {"nombre_paciente": "Test User"}}
    save_session(wa_id, session)
    retrieved = get_session(wa_id)
    assert retrieved.get("datos_capturados", {}).get("nombre_paciente") == "Test User"
    clear_session(wa_id)
    empty = get_session(wa_id)
    assert empty == {}


def test_memory_history():
    from app.memory import update_history, get_history_text, clear_session
    wa_id = "test_history_123"
    clear_session(wa_id)
    update_history(wa_id, "user", "Hola")
    update_history(wa_id, "assistant", "¡Hola! Soy Yanny 👩‍⚕️")
    history = get_history_text(wa_id)
    assert "Hola" in history
    assert "Yanny" in history
    clear_session(wa_id)


# ─── Tests de API (sin llamar a OpenAI real) ─────────────────────────────────
@pytest.mark.asyncio
async def test_health_endpoint():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"


@pytest.mark.asyncio
async def test_stats_endpoint():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/stats")
    assert response.status_code == 200
    data = response.json()
    assert "total_messages" in data
    assert "total_cost_usd" in data


@pytest.mark.asyncio
async def test_webhook_ignores_non_message_events():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/chatwoot", json={
            "event": "conversation_created",
        })
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_webhook_ignores_outgoing_messages():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/webhook/chatwoot", json={
            "event": "message_created",
            "message_type": "outgoing",
            "private": False,
            "sender": {"type": "agent_bot"},
        })
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


# ─── Test de integración completa (requiere .env con API keys reales) ────────
@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_flow_saludo():
    """
    Prueba de integración completa. Requiere OPENAI_API_KEY en .env.
    Ejecutar: pytest tests/ -v -k "integration" --runintegration
    """
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/test/message", json={
            "wa_id": "57300test001",
            "message": "Hola",
            "conversation_id": 9001,
        })
    assert response.status_code == 200
    data = response.json()
    assert data.get("respuesta") is not None
    assert "Yanny" in data.get("respuesta", "")
    print(f"\n✅ Respuesta: {data['respuesta']}")
    print(f"   Modelo: {data['modelo_usado']} | Costo: ${data['costo_estimado']:.6f}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_full_flow_servicios():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/test/message", json={
            "wa_id": "57300test002",
            "message": "¿Qué servicios ofrecen?",
            "conversation_id": 9002,
        })
    assert response.status_code == 200
    data = response.json()
    assert "Odontología" in data.get("respuesta", "")
    print(f"\n✅ Respuesta: {data['respuesta'][:100]}")


# ─── Carga de escenarios desde JSON ─────────────────────────────────────────
def load_scenarios():
    path = Path(__file__).parent / "scenarios" / "dental_scenarios.json"
    with open(path) as f:
        return json.load(f)


def test_scenarios_file_exists():
    path = Path(__file__).parent / "scenarios" / "dental_scenarios.json"
    assert path.exists()
    scenarios = load_scenarios()
    assert len(scenarios) > 0
    print(f"\n✅ {len(scenarios)} escenarios de prueba cargados")
