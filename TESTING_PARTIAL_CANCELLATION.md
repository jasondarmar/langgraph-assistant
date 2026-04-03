# Testing Guide: Partial Name Appointment Cancellation

## Prerequisites

Ensure you have:
1. At least 2-3 appointments in Google Calendar with similar patient names
   - Example: "Jason Dario Marles", "Jason Marles", "Jason Antonio Marles"
2. All appointments must follow the format: `"Sede - Nombre - Servicio - Doctor"`
3. Docker container running with latest code

## Test Scenario 1: Single Match (Direct Deletion)

### Setup
- Create an appointment: "Bogotá - Juan García Pérez - Limpieza - Dr. Luna"
- No other appointments with "Juan García" in the name

### Test Steps
1. User sends WhatsApp message: "Quiero cancelar mi cita, me llamo Juan García"
2. Bot should:
   - Classify intent as "cancelar_cita"
   - Search for appointments by "Juan García"
   - Find 1 match (no need to ask)
   - Delete immediately
   - Send: "¡Listo! Tu cita para [fecha] a las [hora] ha sido cancelada. 😊"
3. Verify in Google Calendar: appointment is gone
4. Verify in PostgreSQL: appointment status = "cancelada"

### Expected Outcome
- ✅ Appointment deleted without requiring user to select
- ✅ Confirmation sent immediately
- ✅ DB updated with correct status

---

## Test Scenario 2: Multiple Matches (With Selection)

### Setup
- Create 3 appointments:
  - "Bogotá - José Antonio Pérez - Limpieza - Dr. Luna" (Saturday, 2:00 PM)
  - "La Vega - José Pérez García - Ortodoncia - Dra. González" (Sunday, 10:00 AM)
  - "Villeta - José Luis Pérez - Extracción - Dr. Sebastian" (Next week, 3:00 PM)

### Test Steps

#### Turn 1: User initiates cancellation
1. User sends: "Quiero cancelar mi cita, me llamo José Pérez"
2. Bot should respond:
   ```
   Encontré múltiples citas a tu nombre. ¿Cuál deseas cancelar?

   1️⃣ José Antonio Pérez - Limpieza - 2026-04-05 14:00
   2️⃣ José Pérez García - Ortodoncia - 2026-04-06 10:00
   3️⃣ José Luis Pérez - Extracción - 2026-04-12 15:00

   Responde con el número (ej: 1️⃣)
   ```
3. Verify no appointment was deleted yet

#### Turn 2: User selects from list
4. User sends: "1" (or "1️⃣")
5. Bot should:
   - Respond: "Cancelando tu cita... 😊"
   - Delete the first appointment from Google Calendar
   - Update DB with "cancelada" status
6. Verify:
   - ✅ Correct appointment deleted (José Antonio Pérez on Saturday)
   - ✅ Other appointments still exist
   - ✅ DB shows correct cancellation

#### Turn 3: Continue conversation
7. User sends another message (e.g., "Quiero agendar una nueva")
8. Conversation should proceed normally
9. Verify `pending_cancellation_matches` is cleared from state

### Expected Outcome
- ✅ List shows all matching appointments with dates/times
- ✅ User can select by number
- ✅ Only selected appointment is deleted
- ✅ Confirmation is clear and accurate

---

## Test Scenario 3: Invalid Selection

### Setup
- Same as Scenario 2 (3 appointments)

### Test Steps
1. Turn 1: User initiates with "José Pérez"
2. Bot shows list of 3 options
3. User sends: "5" (out of range)
4. Bot should:
   - Fall back to normal LLM flow
   - Ask user to try again or provide more details
   - NOT delete anything

### Expected Outcome
- ✅ Out-of-range selection doesn't cause crash
- ✅ User can recover by providing correct input
- ✅ No appointments deleted unintentionally

---

## Test Scenario 4: No Matches Found

### Setup
- Create appointment: "Bogotá - Juan García López - Limpieza - Dr. Luna"

### Test Steps
1. User sends: "Quiero cancelar mi cita, me llamo María Rodríguez"
2. Bot should respond:
   ```
   No encontré citas a nombre de 'María Rodríguez'. Por favor, proporciona más detalles (nombre completo o fecha). 😊
   ```
3. Verify no deletion attempted

### Expected Outcome
- ✅ User informed no matches found
- ✅ Conversation can continue
- ✅ User can provide more details

---

## Test Scenario 5: Fuzzy Name Matching

### Setup
- Create appointment: "Bogotá - José Antonio María Pérez González - Limpieza - Dr. Luna"

### Test Steps
1. User sends: "Quiero cancelar mi cita, me llamo José Pérez"
2. Bot should:
   - Search with fuzzy match: "josé pérez"
   - Find the appointment (both words match the longer name)
   - Either delete directly (if only match) or show in list

### Expected Outcome
- ✅ Fuzzy matching works (all search parts must appear in name)
- ✅ "José Pérez" matches "José Antonio María Pérez González"
- ✅ Case-insensitive matching

---

## Test Scenario 6: User Changes Mind (Invalid Emoji Numbers)

### Setup
- Same as Scenario 2

### Test Steps
1. Turn 1: User initiates with "José Pérez"
2. Bot shows list
3. User sends: "ninguno" (none of them) or some random text
4. Bot should:
   - Not treat as selection
   - Fall back to normal LLM flow
   - Can ask for clarification

### Expected Outcome
- ✅ Non-numeric responses don't trigger selection
- ✅ User can cancel the cancellation by not selecting
- ✅ Conversation can continue naturally

---

## Logging Verification

### Check Application Logs
Look for these log entries when testing:

```
[Calendar] search_appointments_by_name('José Pérez'): 3 coincidencias
[Calendar] Múltiples coincidencias encontradas: 3
[Responder] Selección de cita: usuario eligió índice 1, event_id=event123
[Calendar] Evento eliminado: event123
[Calendar] Appointment delete: update estado=cancelada
```

### Check Database
```sql
SELECT * FROM appointments 
WHERE estado = 'cancelada' 
ORDER BY updated_at DESC 
LIMIT 5;
```

---

## Performance Considerations

- Google Calendar search is limited to 30 days back, 90 days forward
- Fuzzy matching is case-insensitive string matching (efficient)
- Database update is async, should complete within 1-2 seconds

---

## Rollback Plan (if issues found)

If severe issues are discovered:
1. Set `pending_cancellation_matches` field to `None` in state parser
2. This disables the feature but doesn't break existing cancellation with event_id
3. Existing cancellations (when event_id is known) still work

---

## Success Criteria

All scenarios should pass with:
- ✅ No crashes or exceptions
- ✅ Correct appointments deleted
- ✅ Database properly updated
- ✅ User receives clear confirmations
- ✅ Conversation context preserved
- ✅ Fuzzy matching works as expected
