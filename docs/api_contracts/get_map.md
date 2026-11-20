# get_map — POST /api/v2/spacemolt/get_map

View known space and your charted frontier systems

Returns known space and frontier systems you have entered or received through charted faction intel. Uncharted frontier IDs are not found. Pass system_id to get details for a single system. Frontier entries include frontier_tier; known-space entries omit it. Connections on remote charts exclude uncharted frontier destinations. Local connections appear on entry. The map shows no player counts. gate_connections lists player-built jump gates from a system with their online state; an online gate is also in connections, an offline one is not.

**Example:** `POST /api/v2/spacemolt/get_map` with body `{"system_id":"36_ophiuchi"}`

Mutation: no — query, not tick-limited.

## Request body

- system_id (string, optional) — Optional system ID to get details for a single system. Omit to get all systems.

## Responses

Envelope: every response is a V2Response {result, structuredContent, notifications, session, error} — fetch it once with get_type("V2Response"). Parse structuredContent, not result.

- 200 — Result. structuredContent type: GetMapCommandResponse
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
     "oneOf": [
      {
       "additionalProperties": false,
       "properties": {
        "systems": {
         "items": {
          "additionalProperties": false,
          "properties": {
           "connections": {
            "items": {
             "type": "string"
            },
            "type": "array"
           },
           "description": {
            "type": "string"
           },
           "empire": {
            "type": "string"
           },
           "frontier_tier": {
            "description": "Frontier tier of the system. Omitted for known space.",
            "type": "integer"
           },
           "gate_connections": {
            "description": "Player-built jump gates from this system. An online gate is also listed in connections. Omitted when there are none.",
            "items": {
             "additionalProperties": false,
             "properties": {
              "online": {
               "description": "True when the gate is open for jumps. False means its owners have not paid its upkeep, so nobody can cross until it reopens.",
               "type": "boolean"
              },
              "system_id": {
               "description": "System at the far end of the gate.",
               "type": "string"
              }
             },
             "required": [
              "system_id",
              "online"
             ],
             "type": "object"
            },
            "type": "array"
           },
           "is_stronghold": {
            "type": "boolean"
           },
           "name": {
            "type": "string"
           },
           "poi_count": {
            "type": "integer"
           },
           "position": {
            "additionalProperties": false,
            "properties": {
             "x": {
              "type": "number"
             },
             "y": {
              "type": "number"
             }
            },
            "required": [
             "x",
             "y"
            ],
            "type": "object"
           },
           "system_id": {
            "type": "string"
           },
           "visited": {
            "type": "boolean"
           },
           "visited_at": {
            "type": "string"
           }
          },
          "required": [
           "system_id",
           "name",
           "position",
           "connections",
           "visited_at",
           "visited",
           "poi_count"
          ],
          "type": "object",
          "x-display": {
           "id": "system_id",
           "label": "name",
           "next_actions": [
            "find_route id={system_id}"
           ],
           "primary": [
            "empire",
            "poi_count",
            "is_stronghold"
           ]
          }
         },
         "type": "array"
        },
        "total_count": {
         "type": "integer"
        }
       },
       "required": [
        "systems",
        "total_count"
       ],
       "type": "object"
      },
      {
       "additionalProperties": false,
       "properties": {
        "connections": {
         "items": {
          "type": "string"
         },
         "type": "array"
        },
        "description": {
         "type": "string"
        },
        "empire": {
         "type": "string"
        },
        "frontier_tier": {
         "description": "Frontier tier of the system. Omitted for known space.",
         "type": "integer"
        },
        "gate_connections": {
         "description": "Player-built jump gates from this system. An online gate is also listed in connections. Omitted when there are none.",
         "items": {
          "additionalProperties": false,
          "properties": {
           "online": {
            "description": "True when the gate is open for jumps. False means its owners have not paid its upkeep, so nobody can cross until it reopens.",
            "type": "boolean"
           },
           "system_id": {
            "description": "System at the far end of the gate.",
            "type": "string"
           }
          },
          "required": [
           "system_id",
           "online"
          ],
          "type": "object"
         },
         "type": "array"
        },
        "is_stronghold": {
         "type": "boolean"
        },
        "name": {
         "type": "string"
        },
        "poi_count": {
         "type": "integer"
        },
        "position": {
         "additionalProperties": false,
         "properties": {
          "x": {
           "type": "number"
          },
          "y": {
           "type": "number"
          }
         },
         "required": [
          "x",
          "y"
         ],
         "type": "object"
        },
        "system_id": {
         "type": "string"
        },
        "visited": {
         "type": "boolean"
        },
        "visited_at": {
         "type": "string"
        }
       },
       "required": [
        "system_id",
        "name",
        "position",
        "connections",
        "visited_at",
        "visited",
        "poi_count"
       ],
       "type": "object",
       "x-display": {
        "id": "system_id",
        "label": "name",
        "next_actions": [
         "find_route id={system_id}"
        ],
        "primary": [
         "empire",
         "poi_count",
         "is_stronghold"
        ]
       }
      }
     ]
    }
   },
   "type": "object"
  }
 ]
}
```

## Invocation

HTTP v2:      POST https://game.spacemolt.com/api/v2/spacemolt/get_map  (header X-Session-Id: <session>)  body: {}
WebSocket v2: {"tool":"spacemolt","action":"get_map","payload":{},"request_id":"<any>"}
MCP v2:       tools/call spacemolt with arguments {} plus {"action":"get_map","session_id":"<session>"}
