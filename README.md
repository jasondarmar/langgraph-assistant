# 🦷 LangGraph Dental Assistant — Tech Ideas Lab

Asistente virtual para WhatsApp del consultorio odontológico **Luna González**.
Construido con LangGraph + FastAPI + OpenAI GPT-4o.

## Stack

| Componente | Tecnología |
|---|---|
| Orquestación | LangGraph (StateGraph) |
| API | FastAPI + Uvicorn |
| LLM | GPT-4o-mini (80%) + GPT-4o (20%) |
| Audio | OpenAI Whisper |
| Calendario | Google Calendar API |
| Memoria | Redis (o dict en memoria) |
| Panel de soporte | Chatwoot |
| Mensajería | WhatsApp Business API (vía Chatwoot) |
| Infraestructura | Hetzner CPX21 + Docker + Cloudflare Tunnel |

---

## Estructura del proyecto

```
langgraph-assistant/
├── app/
│   ├── main.py          # FastAPI app, webhooks, /health, /stats, /test/message
│   ├── graph.py         # StateGraph LangGraph — flujo completo del agente
│   ├── state.py         # AgentState TypedDict
│   ├── memory.py        # Gestión de sesiones (Redis / memoria local)
│   └── dependencies.py  # Inyección de dependencias
├── agents/
│   ├── classifier.py    # Nodo clasificador de intención (gpt-4o-mini)
│   ├── responder.py     # Nodo generador de respuesta (router LLM)
│   └── llm_router.py    # Selección dinámica de modelo según intención
├── tools/
│   ├── whisper.py       # Transcripción de audio (OpenAI Whisper)
│   ├── appointments.py  # Google Calendar: get_availability, create, delete
│   ├── escalation.py    # Escalamiento a humano vía Chatwoot API
│   └── knowledge_base.py # Servicios, doctores, sedes, FAQ
├── config/
│   ├── settings.py      # Pydantic Settings desde .env
│   ├── models.py        # Configuración LLMs, costos, tiers
│   └── prompts.py       # System prompts centralizados
├── tests/
│   ├── test_agent.py    # Tests unitarios e integración
│   └── scenarios/       # JSONs con escenarios de prueba
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

---

## Instalación rápida (servidor)

```bash
# 1. Clonar repositorio
git clone https://github.com/jasondarmar/langgraph-assistant.git
cd langgraph-assistant

# 2. Crear archivo de configuración
cp .env.example .env
# Editar .env con tus API keys

# 3. Construir y levantar
docker compose up -d --build

# 4. Verificar
curl http://localhost:8001/health
```

---

## Instalación local (desarrollo / debug)

```bash
# 1. Python 3.11+
python --version  # debe ser 3.11+

# 2. Entorno virtual
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# 3. Dependencias
pip install -r requirements.txt

# 4. Configuración
cp .env.example .env
# Editar .env

# 5. Levantar en modo debug
DEBUG=true python -m uvicorn app.main:app --reload --port 8001
```

---

## Variables de entorno requeridas

| Variable | Descripción |
|---|---|
| `OPENAI_API_KEY` | API key de OpenAI |
| `CHATWOOT_BASE_URL` | URL base de Chatwoot (`https://chatwoot.techideaslab.com`) |
| `CHATWOOT_API_TOKEN` | Token de acceso a Chatwoot |
| `CHATWOOT_ACCOUNT_ID` | ID de la cuenta en Chatwoot (default: 1) |
| `WHATSAPP_TOKEN` | Token de WhatsApp Business API |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número de teléfono en Meta |
| `GOOGLE_CREDENTIALS_JSON` | JSON completo de la service account de Google |
| `GOOGLE_CALENDAR_ID` | ID del calendario (default: `primary`) |

Opcionales:
| Variable | Default |
|---|---|
| `ANTHROPIC_API_KEY` | (vacío) |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `USE_REDIS` | `false` |
| `LLM_TIER1_MODEL` | `gpt-4o-mini` |
| `LLM_TIER2_MODEL` | `gpt-4o` |
| `APP_PORT` | `8001` |
| `DEBUG` | `false` |
| `LOG_LEVEL` | `INFO` |

---

## Endpoints

| Método | Endpoint | Descripción |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/stats` | Estadísticas de uso y costos |
| `POST` | `/webhook/chatwoot` | Webhook principal desde Chatwoot |
| `POST` | `/test/message` | Prueba directa sin Chatwoot |

### Prueba rápida con /test/message

```bash
curl -X POST http://localhost:8001/test/message \
  -H "Content-Type: application/json" \
  -d '{"wa_id": "573001234567", "message": "Hola", "conversation_id": 1}'
```

Respuesta esperada:
```json
{
  "respuesta": "¡Hola! Soy Yanny 👩‍⚕️✨, tu asistente virtual del consultorio Luna González.",
  "intent": "saludo",
  "estado": "inicio",
  "modelo_usado": "gpt-4o-mini",
  "costo_estimado": 0.000045
}
```

---

## Tests

```bash
# Tests unitarios (sin API keys)
pytest tests/ -v

# Tests de integración (requiere .env con keys reales)
pytest tests/ -v -m integration

# Test específico
pytest tests/test_agent.py::test_health_endpoint -v
```

---

## Flujo del agente

```
Webhook Chatwoot (message_created)
        ↓
    parse_input
    (carga sesión desde Redis/memoria)
        ↓
    ¿Es audio? → transcribe_audio (Whisper)
        ↓
    classify_intent (gpt-4o-mini)
        ↓
    ¿human_mode? → skip al send
        ↓
    generate_response (tier1 o tier2 según intención)
        ↓
    ¿accion_calendario o datos_completos? → handle_calendar
        ↓
    send_response (POST Chatwoot API)
        ↓
    ¿requiere_humano? → escalate_to_human
        ↓
    save_session (Redis/memoria)
        ↓
    END
```

---

## Sedes y configuración de la clínica

| Sede | Horario |
|---|---|
| Bogotá | Lun–Vie 8AM–6PM, Sáb 8AM–1PM |
| La Vega | Lun–Vie 8AM–6PM, Sáb 8AM–1PM |
| Villeta | Lun–Vie 8AM–6PM, Sáb 8AM–1PM |

**Doctores:** Dr. Enrique Luna · Dr. Sebastián Luna · Dra. Mónica González

**Servicios:** Odontología general · Ortodoncia · Blanqueamiento dental · Endodoncia · Prótesis dental · Radiografía dental

---

## Cloudflare Tunnel (agregar al servidor)

```bash
# Agregar en /etc/cloudflared/config.yml
- hostname: agent.techideaslab.com
  service: http://localhost:8001
```

---

## Migración desde n8n

Ver documento: `Plan_Migracion_LangGraph_TechIdeasLab.docx`

Fases:
1. ✅ Preparación del entorno
2. ✅ Grafo base del agente
3. ✅ Router inteligente de LLMs
4. ✅ Herramientas y memoria
5. ⏳ Testing en paralelo con n8n
6. ⏳ Corte y descomisionamiento de n8n

---

## Notas técnicas

- El contenedor comparte red con Chatwoot (`voc0cwk0k40sscw08gs8g44w`) para comunicación interna
- n8n se mantiene activo en `/opt/n8n/` hasta completar validación en Fase 5
- Puerto 8001 para no colisionar con n8n (:5678) ni Chatwoot (:3000)
- Redis usa puerto 6380 para no colisionar con Redis de Chatwoot (:6379)

---

*Tech Ideas Lab · Jason Darío Marles Torres · 2026*
