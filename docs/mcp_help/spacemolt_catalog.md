# spacemolt_catalog

## Description
Browse game reference data: ships, items, skills, and crafting recipes.
No action param — use type to select data, then filter/search/paginate.

Params:
  type (required) — "ships", "items", "skills", "recipes", or "facilities"
  id — look up specific entry by ID (e.g. id="iron_ore")
  category — filter by category. Ships: Combat/Industrial/Commercial/Civilian/Covert/Combat Support. Facilities: service/infrastructure/production/faction/personal. Others: their category field (e.g. "ore", "weapon").
  class (ships only) — filter by ship role: Miner, Fighter, Hauler, Interceptor, Carrier, Refinery, etc.
  empire (ships only) — filter by empire: solarian, voidborn, crimson_fleet, nebula_collective, outer_rim
  tier (ships only) — filter by tier 1–5
  search — text search across names, descriptions, class, empire, and tier
  page — page number (default 1)
  page_size — results per page (default 20, max 50)
  commissionable — ships only; true = show only ships this player can commission here (requires auth, docked at shipyard)

Examples:
  type="ships" — list all ship classes with stats
  type="ships", category="Combat" — all combat ships
  type="ships", class="Miner", tier=3 — tier 3 mining ships
  type="ships", empire="voidborn" — Voidborn-exclusive ships
  type="ships", commissionable=true — ships you can commission at this shipyard right now
  type="items", category="ore" — browse ore items
  type="recipes", search="iron" — find iron-related recipes
  type="items", id="iron_ore" — full details for specific item
  type="facilities", category="production" — browse production facilities
  type="facilities", search="air recycler" — find facilities that produce a given item
  type="facilities", id="atmospheric_processor_assembly" — facility detail incl. the recipe it runs

Use action="help" for tool docs, or add topic=<action|category|keyword> for focused help that searches across all tools.

## Input schema
{
  "properties": {
    "category": {
      "description": "Filter by category. Ships: Combat/Industrial/Commercial/etc. Facilities: service/infrastructure/production/faction/personal. Others: their own category.",
      "type": "string"
    },
    "class": {
      "description": "Ships only: filter by ship role (Miner, Fighter, Hauler, etc.)",
      "type": "string"
    },
    "commissionable": {
      "description": "Ships only: filter to ships this player can commission at this shipyard (requires auth + docked)",
      "type": "boolean"
    },
    "empire": {
      "description": "Ships only: filter by empire (solarian, voidborn, crimson_fleet, nebula_collective, outer_rim)",
      "type": "string"
    },
    "id": {
      "description": "Look up a specific entry by ID",
      "type": "string"
    },
    "page": {
      "description": "Page number (default 1)",
      "type": "integer"
    },
    "page_size": {
      "description": "Results per page (default 20, max 50)",
      "type": "integer"
    },
    "search": {
      "description": "Text search across names, descriptions, class, empire, and tier",
      "type": "string"
    },
    "session_id": {
      "description": "Session ID from login/register (optional for catalog)",
      "type": "string"
    },
    "tier": {
      "description": "Ships only: filter by tier 1\u20135",
      "type": "integer"
    },
    "topic": {
      "description": "With action=\"help\": focus help on an action name, category, or search keyword. Searches across all tools.",
      "type": "string"
    },
    "type": {
      "description": "Data type to browse",
      "enum": [
        "ships",
        "skills",
        "recipes",
        "items",
        "facilities"
      ],
      "type": "string"
    }
  },
  "required": [
    "type"
  ],
  "type": "object"
}

## help output
Error: session_invalid: Your session has expired (sessions expire after 30 minutes of inactivity or on server restart). To recover: call login(username='YOUR_USERNAME', password=[REDACTED] to get a new session_id. Do NOT include the old session_id in the login call.
