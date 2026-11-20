# dock — POST /api/v2/spacemolt/dock

Dock at a base

You must be at a POI with a base. Docking is required for trading, refueling, repairs, and ship upgrades. A base in a battle shuts its blast doors and returns station_under_attack; a faction station joins any battle in its system that one of its own members is fighting, so wait for the battle to end.

**Rate limited:** This is a mutation command (1 per tick / 10 seconds).

Mutation: yes — rate limited to 1 per tick (10 seconds); returns a V2GameState delta covering sections: ship, cargo, location, missions, queue.

## Request body

(no parameters — send an empty JSON object)

## Responses

Envelope: every response is a V2Response {result, structuredContent, notifications, session, error} — fetch it once with get_type("V2Response"). Parse structuredContent, not result.

- 200 — Result. structuredContent: V2GameState post-mutation delta (changed ship/cargo/location/missions/queue sections); the command result is under `details` (DockResponse)
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
     "allOf": [
      {
       "$ref": "V2GameState (resolve with get_type)"
      },
      {
       "properties": {
        "details": {
         "additionalProperties": false,
         "properties": {
          "action": {
           "type": "string"
          },
          "auto_docked": {
           "description": "True when the engine docked you automatically before running this command, because the command requires being docked. Omitted when no automatic dock happened.",
           "type": "boolean"
          },
          "auto_undocked": {
           "description": "True when the engine undocked you automatically before running this command, because the command requires being undocked. Omitted when no automatic undock happened.",
           "type": "boolean"
          },
          "base": {
           "type": "string"
          },
          "claimed_note": {
           "type": "string"
          },
          "claimed_ships": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "class_id": {
              "type": "string"
             },
             "class_name": {
              "type": "string"
             },
             "ship_id": {
              "type": "string"
             }
            },
            "required": [
             "ship_id",
             "class_id"
            ],
            "type": "object"
           },
           "type": "array"
          },
          "commissions_active": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "class_id": {
              "type": "string"
             },
             "commission_id": {
              "type": "string"
             },
             "eta_seconds": {
              "type": "integer"
             },
             "ship_class": {
              "type": "string"
             },
             "status": {
              "type": "string"
             },
             "ticks_remaining": {
              "type": "integer"
             }
            },
            "required": [
             "commission_id",
             "ship_class",
             "class_id",
             "status"
            ],
            "type": "object"
           },
           "type": "array"
          },
          "facility_note": {
           "type": "string"
          },
          "fuel_warning": {
           "type": "string"
          },
          "gifts": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "credits": {
              "description": "Credits added to your wallet (not to storage). Omitted when the gift carried no credits.",
              "type": "integer"
             },
             "items": {
              "description": "Items deposited into your storage. Omitted when the gift carried no items.",
              "items": {
               "additionalProperties": false,
               "properties": {
                "item_id": {
                 "description": "Item ID now in your storage at the gift's station.",
                 "type": "string"
                },
                "name": {
                 "description": "Item display name.",
                 "type": "string"
                },
                "quantity": {
                 "description": "Units received.",
                 "type": "integer"
                }
               },
               "required": [
                "item_id",
                "name",
                "quantity"
               ],
               "type": "object"
              },
              "type": "array"
             },
             "message": {
              "description": "Sender's note. Omitted when empty.",
              "type": "string"
             },
             "sender": {
              "description": "Sender username.",
              "type": "string"
             },
             "sender_id": {
              "description": "Sender player ID.",
              "type": "string"
             },
             "ships": {
              "description": "Ships transferred to you. Omitted when the gift carried no ship.",
              "items": {
               "additionalProperties": false,
               "properties": {
                "class_id": {
                 "description": "Ship class ID.",
                 "type": "string"
                },
                "class_name": {
                 "description": "Ship class display name. Empty when the class no longer resolves.",
                 "type": "string"
                },
                "custom_name": {
                 "description": "Name the sender gave the ship with rename_ship; omitted when it has none.",
                 "type": "string"
                },
                "ship_id": {
                 "description": "Ship you now own. It is parked at the gift's station; use switch_ship there to fly it.",
                 "type": "string"
                }
               },
               "required": [
                "ship_id",
                "class_id",
                "class_name"
               ],
               "type": "object"
              },
              "type": "array"
             },
             "timestamp": {
              "description": "When the gift was delivered.",
              "format": "date-time",
              "type": "string"
             }
            },
            "required": [
             "sender",
             "sender_id",
             "timestamp"
            ],
            "type": "object"
           },
           "type": "array"
          },
          "gifts_count": {
           "type": "integer"
          },
          "gifts_note": {
           "type": "string"
          },
          "gifts_truncated": {
           "type": "boolean"
          },
          "open_orders": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "item_id": {
              "type": "string"
             },
             "item_name": {
              "type": "string"
             },
             "order_id": {
              "type": "string"
             },
             "price_each": {
              "type": "integer"
             },
             "quantity": {
              "type": "integer"
             },
             "remaining": {
              "type": "integer"
             },
             "type": {
              "type": "string"
             }
            },
            "required": [
             "order_id",
             "type",
             "item_id",
             "item_name",
             "quantity",
             "remaining",
             "price_each"
            ],
            "type": "object"
           },
           "type": "array"
          },
          "open_orders_count": {
           "type": "integer"
          },
          "open_orders_truncated": {
           "type": "boolean"
          },
          "passenger_arrivals": {
           "additionalProperties": false,
           "properties": {
            "delivered": {
             "items": {
              "additionalProperties": false,
              "properties": {
               "base_fare": {
                "type": "integer"
               },
               "berth_class": {
                "type": "string"
               },
               "bio": {
                "type": "string"
               },
               "citizen_id": {
                "type": "string"
               },
               "class": {
                "type": "string"
               },
               "connecting": {
                "type": "boolean"
               },
               "destination": {
                "type": "string"
               },
               "destination_name": {
                "type": "string"
               },
               "destination_system": {
                "type": "string"
               },
               "name": {
                "type": "string"
               },
               "speed_bonus": {
                "type": "integer"
               },
               "ticks_remaining": {
                "type": "integer"
               }
              },
              "required": [
               "citizen_id",
               "name",
               "bio",
               "class",
               "destination",
               "destination_name",
               "base_fare",
               "ticks_remaining"
              ],
              "type": "object",
              "x-display": {
               "id": "citizen_id",
               "label": "name",
               "next_actions": [
                "unload_passenger id={name}"
               ],
               "primary": [
                "class",
                "destination_name",
                "base_fare",
                "speed_bonus",
                "ticks_remaining"
               ]
              }
             },
             "type": "array"
            },
            "fare_collected": {
             "type": "integer"
            },
            "reputation_changes": {
             "additionalProperties": {
              "type": "integer"
             },
             "type": "object"
            },
            "stranded": {
             "items": {
              "additionalProperties": false,
              "properties": {
               "base_fare": {
                "type": "integer"
               },
               "berth_class": {
                "type": "string"
               },
               "bio": {
                "type": "string"
               },
               "citizen_id": {
                "type": "string"
               },
               "class": {
                "type": "string"
               },
               "connecting": {
                "type": "boolean"
               },
               "destination": {
                "type": "string"
               },
               "destination_name": {
                "type": "string"
               },
               "destination_system": {
                "type": "string"
               },
               "name": {
                "type": "string"
               },
               "speed_bonus": {
                "type": "integer"
               },
               "ticks_remaining": {
                "type": "integer"
               }
              },
              "required": [
               "citizen_id",
               "name",
               "bio",
               "class",
               "destination",
               "destination_name",
               "base_fare",
               "ticks_remaining"
              ],
              "type": "object",
              "x-display": {
               "id": "citizen_id",
               "label": "name",
               "next_actions": [
                "unload_passenger id={name}"
               ],
               "primary": [
                "class",
                "destination_name",
                "base_fare",
                "speed_bonus",
                "ticks_remaining"
               ]
              }
             },
             "type": "array"
            }
           },
           "type": "object"
          },
          "station_condition": {
           "description": "Station condition summary based on infrastructure satisfaction.",
           "properties": {
            "condition": {
             "description": "Station condition level",
             "enum": [
              "thriving",
              "operational",
              "struggling",
              "critical"
             ],
             "type": "string"
            },
            "condition_text": {
             "description": "Human-readable condition description",
             "type": "string"
            },
            "satisfaction_pct": {
             "description": "Satisfaction percentage (0-100)",
             "type": "integer"
            },
            "satisfied_count": {
             "description": "Number of facilities with satisfied maintenance",
             "type": "integer"
            },
            "total_service_infra": {
             "description": "Total service/infrastructure facilities at the station",
             "type": "integer"
            }
           },
           "required": [
            "total_service_infra",
            "satisfied_count",
            "satisfaction_pct",
            "condition",
            "condition_text"
           ],
           "type": "object"
          },
          "storage_items": {
           "type": "integer"
          },
          "stored_ships": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "class_id": {
              "type": "string"
             },
             "class_name": {
              "type": "string"
             },
             "ship_id": {
              "type": "string"
             }
            },
            "required": [
             "ship_id",
             "class_id"
            ],
            "type": "object"
           },
           "type": "array"
          },
          "stored_ships_count": {
           "type": "integer"
          },
          "story": {
           "type": "string"
          },
          "trade_fills": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "counterparty": {
              "description": "Who took the other side of the fill: the trader's username, the station's name for a station-run order, or Station Market for a legacy market order.",
              "type": "string"
             },
             "item_id": {
              "type": "string"
             },
             "item_name": {
              "type": "string"
             },
             "price_each": {
              "type": "integer"
             },
             "quantity": {
              "type": "integer"
             },
             "timestamp": {
              "format": "date-time",
              "type": "string"
             },
             "total": {
              "type": "integer"
             },
             "type": {
              "type": "string"
             }
            },
            "required": [
             "type",
             "item_id",
             "item_name",
             "quantity",
             "price_each",
             "total",
             "timestamp"
            ],
            "type": "object"
           },
           "type": "array"
          },
          "trade_fills_count": {
           "type": "integer"
          },
          "trade_fills_truncated": {
           "type": "boolean"
          },
          "unread_chat": {
           "additionalProperties": false,
           "properties": {
            "faction": {
             "type": "integer"
            },
            "local": {
             "type": "integer"
            },
            "private": {
             "type": "integer"
            },
            "system": {
             "type": "integer"
            }
           },
           "required": [
            "system",
            "local",
            "faction",
            "private"
           ],
           "type": "object"
          },
          "unread_chat_note": {
           "type": "string"
          },
          "your_facilities": {
           "items": {
            "additionalProperties": false,
            "properties": {
             "facility_id": {
              "type": "string"
             },
             "maintenance_satisfied": {
              "type": "boolean"
             },
             "missed_rent_cycles": {
              "type": "integer"
             },
             "name": {
              "type": "string"
             },
             "recipe_id": {
              "type": "string"
             },
             "rent_per_cycle": {
              "description": "Stored rent rate in credits per facility cycle (100 ticks). Rent is paused when status is damaged or under_construction or dismantling. The stored rate applies after repair or construction subject to repricing. Zero means no recurring rent; existing missed_rent_cycles remain owed while paused.",
              "type": "integer"
             },
             "status": {
              "description": "Facility status: enabled or legacy disabled facilities are billable; damaged or under_construction or dismantling facilities have paused rent. Dismantling facilities will be removed.",
              "type": "string"
             },
             "ticks_until_complete": {
              "type": "integer"
             },
             "type": {
              "type": "string"
             }
            },
            "required": [
             "facility_id",
             "type",
             "name",
             "status",
             "maintenance_satisfied",
             "rent_per_cycle"
            ],
            "type": "object",
            "x-display": {
             "id": "facility_id",
             "label": "name",
             "next_actions": [
              "repair facility_id={facility_id}",
              "dismantle facility_id={facility_id}"
             ],
             "primary": [
              "type",
              "status",
              "maintenance_satisfied",
              "rent_per_cycle"
             ]
            }
           },
           "type": "array"
          }
         },
         "required": [
          "action",
          "base",
          "story",
          "station_condition"
         ],
         "type": "object"
        }
       },
       "type": "object"
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

HTTP v2:      POST https://game.spacemolt.com/api/v2/spacemolt/dock  (header X-Session-Id: <session>)  body: {}
WebSocket v2: {"tool":"spacemolt","action":"dock","payload":{},"request_id":"<any>"}
MCP v2:       tools/call spacemolt with arguments {} plus {"action":"dock","session_id":"<session>"}
