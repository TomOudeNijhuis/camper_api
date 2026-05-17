# GUI changes required after the firmware/API upgrade

The PIC firmware was upgraded to a new binary protocol and the camper-api was
rewritten to match. This changes a few wire formats the GUI must adapt to.

## 1. `household_state` and `pump_state` values are now `"0"` / `"1"`

Previously these entities held `"ON"` / `"OFF"` (and, for household,
occasionally `"PENDING"`). The new firmware exposes them as raw bits in the
telemetry frame, and the API stores them as `"0"` or `"1"` strings.

### Read side

Anywhere the GUI compared against `"ON"` / `"OFF"`:

```python
# OLD
if self.entity_states["household_state"] == "OFF":
    ...
```

becomes:

```python
# NEW
if self.entity_states["household_state"] == "0":
    ...
```

Same for `pump_state`. Truthy interpretation also works:
`bool(int(state_str))` → `False` when `"0"`, `True` when `"1"`.

### Write side (action POST)

Action bodies must now send `0` or `1` (int or string), not `"ON"` / `"OFF"`.

```python
# OLD
self._api_action("household_state", "ON")
self._api_action("pump_state",      "OFF")

# NEW
self._api_action("household_state", 1)
self._api_action("pump_state",      0)
```

The request body shape is unchanged: `POST /action_by_name/camper/household_state`
with JSON `{"state": 1}`. The response is `{"state": "1"}`.

### `PENDING` is gone

The firmware no longer has a pending state — `SET_HOUSEHOLD 1` either succeeds
within 30 s and reports `"1"`, or the firmware pulses OFF and reports `"0"`
together with the `HOUSEHOLD_SWITCH_FAILED` error bit (see §3). Any UI that
shows a "pending" spinner can drop that case; treat the response as a final
state.

## 2. New `errors` entity

A new entity `errors` holds the current firmware error bitmask as a hex
string, e.g. `"0x0000"` (clean) or `"0x0042"` (multiple bits set). It updates
on every telemetry push, so it appears in:

- `GET /sensors/camper/states/` (latest cached value, alongside the other
  seven entities).
- `GET /entities/{errors_entity_id}/states` (history).

### Decoding bits

```python
ERROR_BITS = {
    0x0001: "HOUSEHOLD_SWITCH_FAILED",
    0x0002: "VOLTAGE_HOUSEHOLD_LOW",
    0x0004: "VOLTAGE_STARTER_LOW",
    0x0008: "VOLTAGE_MAINS_LOW",
    0x0010: "WATER_LOW",
    0x0020: "WASTE_HIGH",
    0x0040: "WASTE_FULL",
    0x0080: "ADC_STUCK",
    0x0100: "PROTOCOL_CRC",
    0x0200: "PROTOCOL_OVERRUN",
    0x0400: "BROWN_OUT",
}

mask = int(state_str, 0)
active = [name for bit, name in ERROR_BITS.items() if mask & bit]
```

### Clearing errors

Clearing uses the same `/action/...` endpoint as `household_state` and
`pump_state`. The body is a mask of bits to clear (`"0xFFFF"` clears all):

```
POST /action_by_name/camper/errors
{"mask": "0xFFFF"}
```

Response: `{"state": "0x0000", "bits": []}` — `state` is the remaining mask
after clearing (also written to the entity history); `bits` is the decoded
list of names still active.

Recommended UI treatment (from PROTOCOL.md):

- Tank / voltage errors → user-visible warnings; prompt the user to
  acknowledge, then POST to clear.
- Protocol errors (`PROTOCOL_CRC`, `PROTOCOL_OVERRUN`) → silently log and
  clear; they fire on line noise.
- `BROWN_OUT` → show once on first connect, then clear.
- `ADC_STUCK` → escalate; firmware likely lost its periodic schedule.

## 3. Fast updates: `subscribe_telemetry=true` query parameter

The firmware now pushes telemetry on its own schedule:

- **Idle:** one push every ~60 s.
- **Subscribed:** one push every ~1 s, for ~30 s after the last subscribe.

The GUI tells the API "I'm actively watching" by adding
`?subscribe_telemetry=true` to the existing states endpoint:

```
GET /sensors/camper/states/?subscribe_telemetry=true
```

Each such call extends the fast-push window by 30 s. The GUI should hit this
endpoint while a relevant view is open (e.g. once every few seconds, or on
each refresh). When the user navigates away, drop the flag (or stop hitting
the endpoint) and the firmware falls back to idle mode on its own.

This is a best-effort hint; the rest of the response is unchanged whether the
flag is set or not. Cached state values continue to flow regardless of
cadence.

## 4. No new endpoints, no schema changes

The endpoint surface is unchanged apart from the query parameter above:
`/sensors/`, `/sensors/{id}/states/`, `/entities/...`, `/action/{entity_id}`,
and `/action_by_name/{sensor}/{entity}` all behave the same way. The SQLite
state schema is unchanged.
