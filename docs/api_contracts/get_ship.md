# get_ship — POST /api/v2/spacemolt/get_ship

Get ship and module details (v2 format)

Returns ship stats and installed modules with enriched stats in the v2 state envelope. Omit ship_id for the ship you are flying; pass one to read any other ship you own or any ship in your own faction's garage pool, from anywhere. A ship read that way names its location in the message and omits drone_bay. Also carries drone_bay: {bay_count, bay_capacity, deployed_count, bandwidth_used, bandwidth_total, in_bay:[{id, name, type}]}, omitted only if you have no bay capacity and own no drones. List your drones for full per-drone detail. On a field workshop hull, field_workshop reports its Field Workshop: state (idle, running, paused), pause_reason, queued_jobs and reserved_cargo (cargo space held by escrowed inputs).

**Example:** `POST /api/v2/spacemolt/get_ship` with body `{"id":"optional_ship_id"}`

Mutation: no — query, not tick-limited.

## Request body

- id (string, optional) — Ship to report on (from list_ships or faction_garages). Omit for the ship you are flying. Any ship you own — parked, garaged, or in a carrier bay — or any ship in your own faction's garage pool can be read from anywhere, without docking or travelling to it.

## Responses

Envelope: every response is a V2Response {result, structuredContent, notifications, session, error} — fetch it once with get_type("V2Response"). Parse structuredContent, not result.

- 200 — Result. structuredContent type: V2GameState
- 400 — Bad request — invalid params, unknown command, or game error
- 401 — Not authenticated — missing or invalid session
- 429 — Rate limited — mutations allow 1 per tick (10 seconds)

200 schema (refs resolved; V2Response/V2GameState pinned — use get_type for those):
```json
{
 "allOf": [
  {
   "$ref": "V2Response (resolve with get_type)"
  },
  {
   "properties": {
    "structuredContent": {
     "$ref": "V2GameState (resolve with get_type)"
    }
   },
   "type": "object"
  }
 ]
}
```

## Invocation

HTTP v2:      POST https://game.spacemolt.com/api/v2/spacemolt/get_ship  (header X-Session-Id: <session>)  body: {}
WebSocket v2: {"tool":"spacemolt","action":"get_ship","payload":{},"request_id":"<any>"}
MCP v2:       tools/call spacemolt with arguments {} plus {"action":"get_ship","session_id":"<session>"}
