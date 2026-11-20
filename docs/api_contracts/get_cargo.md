# get_cargo — POST /api/v2/spacemolt/get_cargo

Get cargo contents (v2 format)

Returns cargo items with resolved names and sizes in the v2 state envelope. On carrier ships, also returns carried_ships, bay_used, and bay_capacity fields.

Mutation: no — query, not tick-limited.

## Request body

(no parameters — send an empty JSON object)

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

HTTP v2:      POST https://game.spacemolt.com/api/v2/spacemolt/get_cargo  (header X-Session-Id: <session>)  body: {}
WebSocket v2: {"tool":"spacemolt","action":"get_cargo","payload":{},"request_id":"<any>"}
MCP v2:       tools/call spacemolt with arguments {} plus {"action":"get_cargo","session_id":"<session>"}
