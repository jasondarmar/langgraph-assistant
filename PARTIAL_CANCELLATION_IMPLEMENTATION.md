# Partial Name Appointment Cancellation Implementation

## Overview
Implemented a complete flow allowing users to cancel appointments using partial names (e.g., "José Pérez" instead of "José Antonio Pérez").

## Changes Made

### 1. **app/state.py** - Added Selection Tracking Fields
```python
pending_cancellation_matches: Optional[list]  # Stores found appointments from search
selected_match_index: Optional[int]           # Tracks which appointment user selects
```

### 2. **tools/appointments.py** - Search and Selection Logic

#### `search_appointments_by_name(patient_partial_name, days_back=30, days_forward=90)`
- Queries Google Calendar for events in a time range (30 days back, 90 days forward)
- Extracts patient name from event summary format: `"Sede - Nombre - Servicio - Doctor"`
- Uses **fuzzy matching**: splits search name by spaces, all parts must appear in event name (case-insensitive)
- Returns list of matching events with: id, summary, start datetime, description, nombre_paciente

**Example:**
```python
matches = search_appointments_by_name("José Pérez")
# Matches "José Antonio Pérez" from calendar
```

#### Modified `handle_calendar_action` DELETE Branch
When `accion == "delete"` but no `event_id`:
1. **Single match found** → Use directly, proceed with delete
2. **Multiple matches found** → Return respuesta showing numbered list (1️⃣ 2️⃣ etc.), set `pending_cancellation_matches`, don't delete yet
3. **No matches found** → Return respuesta saying no appointment found with that name

### 3. **agents/responder.py** - Selection Detection

Added early-exit selection detection (runs BEFORE LLM):
```python
pending_matches = state.get("pending_cancellation_matches")
if pending_matches:
    # Extract number from user message: "1", "1️⃣", etc.
    # Get event_id from selected match
    # Return state with event_id set, accion_calendario="delete"
```

When user responds with a number:
- Extracts numeric selection (handles "1", "1️⃣", emoji numbers, etc.)
- Validates selection index is in range
- Sets `event_id` in `datos_capturados`
- Sets `accion_calendario = "delete"`
- Sets `estado_conversacion = "finalizado"` (pure cancellation)
- Returns with confirmation message (bypasses LLM)

## Complete Flow Example

### Turn 1: User provides partial name for cancellation
```
User: "Quiero cancelar mi cita, me llamo José Pérez"

Classifier: intent = "cancelar_cita"
Responder: No pending_matches → calls LLM
LLM: Returns accion_calendario="delete", estado="finalizado"
Calendar Handler: No event_id → searches "José Pérez"
  Found 3 matches:
    1️⃣ José Antonio Pérez - Limpieza - 2026-04-05 14:00
    2️⃣ José Pérez García - Ortodoncia - 2026-04-06 10:00
    3️⃣ José Luis Pérez - Extracción - 2026-04-12 15:00
  
Bot: "Encontré múltiples citas a tu nombre. ¿Cuál deseas cancelar?
     1️⃣ José Antonio Pérez - Limpieza - 2026-04-05 14:00
     2️⃣ José Pérez García - Ortodoncia - 2026-04-06 10:00
     3️⃣ José Luis Pérez - Extracción - 2026-04-12 15:00
     Responde con el número (ej: 1️⃣)"

State Update:
  pending_cancellation_matches = [match1, match2, match3]
  accion_calendario = null  # Don't delete yet, wait for selection
```

### Turn 2: User selects from list
```
User: "1"

Classifier: intent = "otro" (just a number)
Responder: pending_matches exists → detects selection!
  Extracts: selected_idx = 0 (1-based to 0-based)
  Gets: event_id = "event123" from matches[0]
  Sets: event_id in datos_capturados
  Returns: accion_calendario="delete", estado="finalizado"
  
Calendar Handler: event_id is set → delete directly
  Calls: delete_appointment(event_id)
  Updates DB: estado = "cancelada"
  
Bot: "¡Listo! Tu cita para el 5 de abril a las 14:00 con el Dr. Luna ha sido cancelada. 😊"
```

## Key Design Decisions

1. **Single Selection Detection**
   - When 1 match found → use directly, no need to ask
   - When multiple → ask user to choose

2. **Numeric Input Only**
   - User responds with number (1, 1️⃣, etc.)
   - Handles emoji numbers correctly
   - Falls back to normal LLM flow if input doesn't match pattern

3. **State Cleanup**
   - `pending_cancellation_matches` cleared after selection
   - No residual state that could interfere with next messages

4. **Database Tracking**
   - Uses existing `update_appointment_estado()` to mark as "cancelada"
   - Preserves full conversation context for audit trail

5. **LLM Bypass**
   - Selection detection happens in responder BEFORE LLM call
   - Avoids confusion or hallucination by LLM
   - Pure programmatic logic

## Testing Checklist

- [ ] Search finds appointments with fuzzy matching (e.g., "José Pérez" matches "José Antonio Pérez")
- [ ] Single match is used directly without asking user
- [ ] Multiple matches show numbered list with patient name, service, date, time
- [ ] User can select by number (1, 2, etc.)
- [ ] User can select by emoji number (1️⃣, 2️⃣, etc.)
- [ ] Invalid selection (out of range) falls back to normal flow
- [ ] Appointment is deleted correctly in Google Calendar
- [ ] Database is updated with "cancelada" status
- [ ] Confirmation message is sent to user
- [ ] Conversation state is cleaned up for next interaction

## Edge Cases Handled

1. **No matches** → User informed, can provide more details
2. **Single match** → Used directly, no selection prompt needed
3. **Invalid numeric input** → Falls through to normal LLM flow (can ask again)
4. **Out of range selection** → Falls through to normal LLM flow
5. **Empty pending_matches on next turn** → Normal LLM flow proceeds

## System Prompt Notes

The system prompt (config/prompts.py) R10 rule requires `[CITA ACTIVA]` context for cancellation via LLM. This implementation works **outside** the normal LLM flow:
- Responder detects selection BEFORE calling LLM
- LLM never sees the pending_cancellation_matches state
- No conflict with existing R10 rule
