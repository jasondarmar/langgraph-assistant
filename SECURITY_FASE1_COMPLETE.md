# 🔒 FASE 1 - IMPLEMENTACIÓN COMPLETA

## Status: ✅ COMPLETADA

### Resumen de Cambios

#### 1. ✅ Validación de Entrada (app/schemas.py - NUEVO)
- `AppointmentDataValidated` - valida toda la información de citas
  - nombre_paciente: 2-100 caracteres, solo letras/acentos/guiones
  - sede: solo Bogotá, La Vega, Villeta
  - servicio: solo servicios válidos
  - doctor: solo doctores registrados
  - fecha_cita: no pasado, máximo 1 año futuro, formato YYYY-MM-DD
  - hora_cita: formato HH:MM, horario clínica (8AM-6PM lunes-viernes, 8AM-1PM sábado)
  - event_id: alfanumérico, máximo 255 caracteres

- `WebhookPayloadValidated` - valida payloads de Chatwoot
  - conversation_id, inbox_id: números válidos
  - wa_id: 10+ dígitos
  - sender_name: máximo 100 caracteres, sin patrones maliciosos
  - raw_content: máximo 5000 caracteres
  - audio_url: URL válida https, máximo 2048 caracteres

**Previene:** Overflow de buffers, inyección de SQL/code, formato inválido

---

#### 2. ✅ Funciones de Seguridad (app/security.py - NUEVO)
- `verify_chatwoot_signature()` - Validación HMAC-SHA256
  - Compara firma enviada con firma calculada
  - Timing-safe comparison (previene timing attacks)
  - Retorna True/False

- `sanitize_for_prompt()` - Sanitiza inputs antes de LLM
  - Limita longitud (máximo 100 chars)
  - Remueve caracteres de control
  - Bloquea patrones peligrosos: `"""`, `[SYSTEM`, `eval`, `import`, etc.
  - Limpia múltiples espacios/newlines

- `sanitize_for_query()` - Sanitiza para búsquedas
  - Solo caracteres seguros: letras, números, espacios, guiones, acentos
  - Máximo 100 caracteres

- `mask_sensitive_data()` - Redacta PII en logs
  - Números telefónicos → [PHONE]
  - Emails → [EMAIL]
  - IPs → [IP]
  - Document IDs → [DOC_ID]
  - Event IDs → [EVENT_ID]

- `is_safe_url()` - Previene SSRF attacks
  - Valida que URL sea https/http
  - Verifica host contra whitelist permitida
  - Máximo 2048 caracteres

**Previene:** Prompt injection, SSRF, data leakage en logs

---

#### 3. ✅ Webhook Seguro (app/main.py)
**Cambios en endpoint `/webhook/chatwoot`:**

```python
@app.post("/webhook/chatwoot")
@limiter.limit("10/minute")  # Rate limiting: máximo 10 por minuto
async def webhook_chatwoot(request: Request, background_tasks: BackgroundTasks):
    # 1. Obtener body raw
    body_raw = await request.body()
    
    # 2. Obtener firma del header
    signature = request.headers.get("X-Chatwoot-Webhook-Signature", "")
    
    # 3. Validar firma HMAC-SHA256
    if not verify_chatwoot_signature(body_raw, signature, settings.chatwoot_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    
    # 4. Validar estructura con Pydantic
    validated_payload = WebhookPayloadValidated(...)
    
    # 5. Log sin PII
    logger.info(f"[Webhook] conv_id={conv_id}")  # Sin incluir datos sensibles
```

**Previene:**
- Webhooks falsos (validación HMAC)
- DoS por spam de webhooks (rate limiting)
- Datos malformados (Pydantic validation)
- PII exposure en logs

---

#### 4. ✅ Endpoint de Testing Protegido (app/main.py)
**Cambios en `/test/message`:**

```python
@app.post("/test/message")
@limiter.limit("30/minute")  # Rate limit más permisivo
async def test_message(request: Request):
    # 1. Deshabilitar en producción
    if os.getenv("ENVIRONMENT") == "production":
        raise HTTPException(status_code=404)
    
    # 2. Validar token en desarrollo (opcional)
    auth_header = request.headers.get("Authorization", "")
    test_token = os.getenv("TEST_TOKEN")
    if test_token and auth_header.replace("Bearer ", "") != test_token:
        raise HTTPException(status_code=401)
```

**Previene:**
- Exposición del endpoint en producción
- Testing no autorizado en desarrollo

---

#### 5. ✅ Sanitización en Prompts (agents/responder.py)
Todos los inputs del usuario ahora se sanitizan antes de inyectar en prompts:

```python
# Antes (VULNERABLE):
context_lines.append(f"[NOMBRE: {nombre_paciente}]")  # Del usuario

# Después (SEGURO):
nombre_safe = sanitize_for_prompt(nombre_paciente, max_length=100)
context_lines.append(f"[NOMBRE: {nombre_safe}]")
```

**Previene:** Prompt injection attacks

---

#### 6. ✅ Configuración Segura (config/settings.py)
**Nuevos parámetros:**
- `chatwoot_webhook_secret` - Secret para validar webhooks
- `environment` - "development" o "production"
- `test_token` - Token para /test/message en desarrollo

**Nunca guardes en .env:**
```bash
# ❌ MALO - en .env o en git
OPENAI_API_KEY=sk-...
CHATWOOT_API_TOKEN=...

# ✅ BUENO - en environment variables seguras
export OPENAI_API_KEY=sk-... # Del secret manager
export CHATWOOT_WEBHOOK_SECRET=... # Chatwoot → Settings
```

---

#### 7. ✅ Rate Limiting (app/main.py)
**Usando library slowapi:**
```python
from slowapi import Limiter

limiter = Limiter(key_func=lambda r: validate_rate_limit_key(get_remote_address(r)))

@app.post("/webhook/chatwoot")
@limiter.limit("10/minute")
async def webhook_chatwoot(...): ...

@app.post("/test/message")
@limiter.limit("30/minute")
async def test_message(...): ...
```

**Limites:**
- `/webhook/chatwoot`: 10 por minuto (máximo)
- `/test/message`: 30 por minuto (desarrollo)

**Previene:** DoS attacks, spam de webhooks

---

#### 8. ✅ Hiding Swagger Docs en Producción
```python
app = FastAPI(
    docs_url=None if os.getenv("ENVIRONMENT") == "production" else "/docs",
    redoc_url=None if os.getenv("ENVIRONMENT") == "production" else "/redoc",
)
```

**Previene:** Information disclosure (atacantes reconocimiento)

---

### Archivos Modificados

| Archivo | Cambios |
|---------|---------|
| `app/security.py` | ✨ NUEVO - funciones de seguridad |
| `app/schemas.py` | ✨ NUEVO - validadores Pydantic |
| `app/main.py` | ✏️ Webhook signature + rate limiting |
| `agents/responder.py` | ✏️ Sanitización en prompts |
| `config/settings.py` | ✏️ Parámetros de seguridad |
| `requirements.txt` | ✏️ Agregar slowapi |

### Archivos NO Modificados (para Fase 2)
- `tools/appointments.py` - SSRF prevention en audio
- `tools/whisper.py` - Validación de descargas
- Logging y data retention

---

## Cómo Aplicar

### 1. Instalar nuevas dependencias
```bash
pip install slowapi
```

### 2. Configurar variables de entorno
```bash
# En .env o en tu sistema:
ENVIRONMENT=development  # o "production"
TEST_TOKEN=your-test-token-here
CHATWOOT_WEBHOOK_SECRET=your-chatwoot-webhook-secret

# El webhook secret lo obtienes de Chatwoot:
# Settings → Integrations → Webhooks → Signature Key
```

### 3. Para producción
```bash
export ENVIRONMENT=production
export CHATWOOT_WEBHOOK_SECRET=$(aws secretsmanager get-secret-value --secret-id webhook-secret --query SecretString --output text)
```

### 4. Testear cambios
```bash
# Test webhook signature
curl -X POST http://localhost:8001/webhook/chatwoot \
  -H "X-Chatwoot-Webhook-Signature: invalid" \
  -H "Content-Type: application/json" \
  -d '{"event":"message_created"}'
# Esperado: 401 Unauthorized

# Test rate limiting (enviar 11 requests en 1 minuto)
for i in {1..11}; do
  curl -X POST http://localhost:8001/webhook/chatwoot ...
done
# Esperado: 429 Too Many Requests en el 11°

# Test /test/message sin token
curl -X POST http://localhost:8001/test/message \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
# Esperado: 401 Unauthorized (en development con TEST_TOKEN configurado)

# Test /test/message con token
curl -X POST http://localhost:8001/test/message \
  -H "Authorization: Bearer your-test-token-here" \
  -H "Content-Type: application/json" \
  -d '{"message":"hola"}'
# Esperado: 200 OK
```

---

## Vulnerabilidades Corregidas

| Vulnerabilidad | Severidad | Solución |
|---|---|---|
| Webhooks sin autenticación | 🔴 CRÍTICA | Validación HMAC-SHA256 |
| Sin rate limiting | 🔴 CRÍTICA | slowapi: 10/min webhooks |
| Inyección en prompts LLM | 🔴 CRÍTICA | sanitize_for_prompt() |
| Endpoint público `/test/message` | 🔴 CRÍTICA | Proteger con token + disable en prod |
| Validación de entrada deficiente | 🟠 ALTA | Pydantic schemas completos |
| Credenciales en plaintext | 🟠 ALTA | Usar variables de entorno |
| PII exposure en logs | 🟠 ALTA | mask_sensitive_data() en logs |

---

## Pendiente Fase 2

- [ ] SSRF prevention en audio downloads
- [ ] Encrypt sensitive DB fields
- [ ] CORS/CSRF protection
- [ ] Audit logging
- [ ] Log filtering with PII masking
- [ ] Data retention policies

---

## Testing Checklist

- [ ] Webhook sin firma → 401
- [ ] Webhook con firma válida → 200
- [ ] 11 webhooks en 60s → 11° retorna 429
- [ ] `/test/message` sin token en dev → 401
- [ ] `/test/message` con token válido → 200
- [ ] `/test/message` en producción → 404
- [ ] Sanitización remueve patrones peligrosos
- [ ] Validadores rechazan datos inválidos
- [ ] Logs no contienen PII

---

## Next Steps

1. Hacer commit de Fase 1
2. Deploy a staging y testear
3. Pasar a Fase 2 (SSRF, DB encryption)
