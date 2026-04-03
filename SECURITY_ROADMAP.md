# 🔒 Roadmap de Seguridad - 3 Fases

## **FASE 1 - CRÍTICAS (Esta semana)**
Vulnerabilidades directamente explotables en producción.

- [ ] **1.1** Agregar validación de firma Chatwoot webhook (HMAC-SHA256)
- [ ] **1.2** Implementar rate limiting en todos los endpoints
- [ ] **1.3** Mover credenciales a environment variables seguros (no en .env)
- [ ] **1.4** Sanitizar inputs antes de inyectar en prompts LLM
- [ ] **1.5** Validar estructuralmente todos los inputs del usuario

### Archivos a modificar:
- `app/main.py` - webhooks, rate limiting
- `config/settings.py` - credential management
- `agents/responder.py` - prompt injection prevention
- `app/schemas.py` - NEW - input validation

---

## **FASE 2 - ALTAS (2ª semana)**
Vulnerabilidades que requieren acceso previo o combinación con otras.

- [ ] **2.1** Remover endpoint `/test/message` o protegerlo
- [ ] **2.2** Implementar descarga segura de audio (SSRF prevention)
- [ ] **2.3** Agregar filtrado de PII en logs
- [ ] **2.4** Validación de tiempos en database (no pasado, límite futuro)
- [ ] **2.5** Error handling: no exponer stack traces

### Archivos a modificar:
- `app/main.py` - remover test endpoint
- `tools/whisper.py` - SSRF prevention
- `app/logging.py` - NEW - PII filtering
- `tools/appointments.py` - validaciones adicionales

---

## **FASE 3 - MEDIAS (Semana 3-4)**
Defensa profunda y compliance.

- [ ] **3.1** CORS/CSRF protection
- [ ] **3.2** Encrypt sensitive fields en database
- [ ] **3.3** Audit logging para operaciones sensibles
- [ ] **3.4** Data retention policies (GDPR compliance)
- [ ] **3.5** Session hijacking prevention
- [ ] **3.6** Credential rotation mechanism

### Archivos a modificar:
- `app/main.py` - CORS middleware
- `tools/db_repository.py` - field encryption
- `app/audit_log.py` - NEW - audit logging
- `app/memory.py` - session security

---

## Progreso

| Fase | Estado | Completado |
|------|--------|-----------|
| Fase 1 | ✅ COMPLETADA | 5/5 |
| Fase 2 | 📋 Pendiente | 0/5 |
| Fase 3 | 📋 Pendiente | 0/5 |

---

## Fase 1 - Resumen de Implementación ✅

**Commit:** `6d32ebf` - security: implement FASE 1 - critical vulnerabilities

**Lo que se implementó:**
1. ✅ Validación de entrada con Pydantic (app/schemas.py)
2. ✅ Webhook HMAC-SHA256 signature validation
3. ✅ Rate limiting (slowapi): 10/min en webhooks
4. ✅ Sanitización de inputs en prompts LLM
5. ✅ Protección del endpoint /test/message
6. ✅ Redacción de PII en logs
7. ✅ Hiding de Swagger docs en producción

**Vulnerabilidades corregidas:** 7 críticas/altas

**Próximo paso:** Implementar Fase 2 (SSRF, DB encryption, CORS)
