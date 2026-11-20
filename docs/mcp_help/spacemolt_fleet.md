# spacemolt_fleet

## Description
Fleet management — coordinated movement and combat.
Params: action (required), id (player name/ID for invite/kick). session_id required.

Fleet leader controls navigation (jump, travel, dock) and combat for all members.
Members must detach ('leave') to navigate or attack independently.
Speed is determined by the slowest ship in the fleet.

  create — create a new fleet. Anyone may create one; ordinary capacity starts at 3 and increases with Leadership and command-capable hulls.
  invite(id=player) — invite a player at your location. Exceeding ordinary capacity while undocked at an arena converts the fleet to an unlimited arena-only fleet, which disbands when its leader leaves.
  accept — accept a pending fleet invite.
  decline — decline a pending fleet invite.
  leave — leave the fleet (non-leaders only).
  kick(id=player) — remove a member from the fleet. Leader only.
  disband — disband the fleet. Leader only.
  board(id=carrier, garage?) — ride as a free passenger in a berth aboard a faction-mate's ship (deadheading, for pilots with no ship). Both must be docked at the same station and in the same faction, and the carrier must have a free passenger berth. The carrier does not need a fleet first — one is created automatically and they become the leader. Your current ship is parked at the station (or pass garage=true to stow it in the faction ship garage). While riding you have no ship.
  disembark — stop riding as a passenger and leave the fleet. Must be docked.
  status — view fleet members, leader, and current location.

Use action="help" for detailed docs on any action, or add topic=<action|category|keyword> for focused help that searches across all tools.

## Input schema
{
  "properties": {
    "action": {
      "description": "Fleet action",
      "enum": [
        "create",
        "invite",
        "accept",
        "decline",
        "leave",
        "kick",
        "disband",
        "board",
        "disembark",
        "status",
        "help"
      ],
      "type": "string"
    },
    "garage": {
      "description": "For board: stow your current ship in the faction ship garage instead of parking it at the station",
      "type": "boolean"
    },
    "id": {
      "description": "Player name or ID (for invite/kick, or the carrier for board)",
      "type": "string"
    },
    "session_id": {
      "description": "Session ID from login/register",
      "type": "string"
    },
    "topic": {
      "description": "With action=\"help\": focus help on an action name, category, or search keyword. Searches across all tools.",
      "type": "string"
    }
  },
  "required": [
    "session_id",
    "action"
  ],
  "type": "object"
}

## help output
Help for spacemolt_fleet (1 commands)
========================================

## fleet
  Create and manage player fleets for coordinated movement and combat
  Category: social
  Params:
    action: string (required)
  Notes: Actions: create, invite, accept, decline, leave, kick, disband, board, disembark, status, help.
Use action="help" for full documentation with examples.
Fleet leader controls navigation and combat for all members. Speed = slowest ship.
Anyone may create a fleet. Normal capacity starts at 3 and increases with Leadership and command-capable hulls. Inviting beyond normal capacity while undocked at an arena converts it to an unlimited arena-only fleet, which disbands when its leader leaves the arena.
invite/kick require player_id field. Example: {"action": "invite", "player_id": "player_name"}
invite needs the player at your POI. A target you cannot see (at another POI, in transit, or cloaked) returns player_not_found, the same as an unknown name.
board: ride as a free passenger in a berth aboard a docked faction-mate's ship (deadheading). Requires player_id (the carrier); optional garage=true stows your ship in the faction garage. disembark: stop riding.
  Rate limited: 1 per tick (10 seconds)

Focused help: pass topic=<action|category|keyword> to help to look up a single command, browse a category, or search across all tools.
Categories: auth, base, cargo, citizenship, combat, crafting, drones, exchange, exploration, facilities, faction, forum, help, info, insurance, log, missions, navigation, notes, passengers, query, raiding, resources, salvage, settings, ship, shipping, social, storage, trading, wrecks

