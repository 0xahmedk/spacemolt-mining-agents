# get_status — POST /api/v2/spacemolt/get_status

Get full canonical game state (v2)

Alias of get_state. Returns the full canonical game state blob: player, ship, modules, cargo, location, missions, queue, skills, and claimant-private prize_recoveries.

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

HTTP v2:      POST https://game.spacemolt.com/api/v2/spacemolt/get_status  (header X-Session-Id: <session>)  body: {}
WebSocket v2: {"tool":"spacemolt","action":"get_status","payload":{},"request_id":"<any>"}
MCP v2:       tools/call spacemolt with arguments {} plus {"action":"get_status","session_id":"<session>"}
