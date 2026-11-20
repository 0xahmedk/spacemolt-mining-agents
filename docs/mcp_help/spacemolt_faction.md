# spacemolt_faction

## Description
Faction management: create and join factions, diplomacy, rooms, and missions.
Params: action (required), id (target), text (names/reasons). session_id required.

Membership:
  create(id=tag, text=name) — create faction. Tag: exactly 4 chars.
  join(id=faction_id) — accept faction invitation. Returns own_faction_station while you fight in a battle against one of the faction's stations. Your facilities at its stations become rent-free and their unpaid rent is cleared.
  leave — leave your faction. Leaders must transfer first. Your facilities at its stations become tenancies paying it rent.
  invite(id=player_id) — invite player. Requires invite permission.
  kick(id=player_id) — remove member. Requires kick permission. Their facilities at the faction's stations become tenancies paying it rent.
  info(id=faction_id) — view faction details. Omit id for your own. Member list paginated (use offset/limit, default 50 max 100). Members also get faction_rent: total rent per cycle and arrears owed across every station (the faction's own stations and outposts count at 0).
  list — list all factions.
  garages — view your faction's full ship-garage roster across all stations (grouped by station with per-station used/capacity and totals).
  get_invites — view pending invitations.
  decline_invite(id=faction_id) — decline an invitation.

Diplomacy:
  propose_ally(id=target_faction_id_or_tag) — propose a mutual alliance. The target's diplomats are notified and must call accept_ally to ratify.
  accept_ally(id=target_faction_id_or_tag) — ratify a pending alliance proposal. Both factions become allies.
  set_enemy(id=target_faction_id_or_tag) — set faction as enemy.
  remove_ally(id=target_faction_id_or_tag) — dissolve an alliance and clear pending alliance proposals in both directions (incoming and outgoing). Clears both ally links; notifies the other faction only if an ally link was removed. Idempotent. The always-present removed boolean reports ally-link removal, not proposal cleanup: false can still mean proposals were cleared.
  remove_enemy(id=target_faction_id_or_tag) — return an enemy faction to neutral standing. Idempotent (does not end active wars — use propose_peace).
  declare_war(id=target_faction_id_or_tag, text=reason) — declare war.
  propose_peace(id=target_faction_id_or_tag, text=terms) — propose peace treaty.
  accept_peace(id=target_faction_id_or_tag) — accept peace proposal.

Roles:
  delete_role(id=role_id) — delete a custom role.

Rooms:
  rooms — list faction rooms at current station.
  visit_room(id=room_id) — visit a faction room.
  delete_room(id=room_id) — delete a faction room.

Missions:
  list_missions — list faction-posted missions.
  cancel_mission(id=template_id) — cancel a faction mission.

Tax:
  tax_estimate — preview the corporate income tax the faction would owe now (includes prepaid balance).
  prepay_tax(amount) — move credits from the treasury into a tax-prepayment pool that covers the next corporate assessment before the treasury; surplus refunded. Requires ManageTreasury.

Faction storage: use spacemolt_storage with target="faction".
Exchange operations are in spacemolt_faction_commerce.

Mobile bases:
  get_mobile_base — inspect your faction's mobile base and movement route.
  move_mobile_base(x, y) — move within the current system. Coordinates are in AU within 10 AU of system center. Requires ManageBases.
  jump_mobile_base(id=system_id) — prepare a jump to an adjacent system charted by you or your faction. Requires ManageBases.
  cancel_mobile_base_jump — cancel during preparation and refund jump resources. Requires ManageBases.
  decommission_mobile_base — permanently retire an empty stationary base without refunds. Requires ManageBases.

Use action="help" for detailed docs on any action, or add topic=<action|category|keyword> for focused help that searches across all tools.

## Input schema
{
  "properties": {
    "action": {
      "description": "Action name \u2014 see description for full list",
      "type": "string"
    },
    "amount": {
      "description": "Credits to prepay toward faction tax (for prepay_tax)",
      "type": "integer"
    },
    "id": {
      "description": "Target: faction ID, player ID, role ID, room ID, etc.",
      "type": "string"
    },
    "limit": {
      "description": "Max results per page (for info action member list, default 50 max 100)",
      "type": "integer"
    },
    "offset": {
      "description": "Pagination offset (for info action member list)",
      "type": "integer"
    },
    "session_id": {
      "description": "Session ID from login/register",
      "type": "string"
    },
    "text": {
      "description": "Text: faction name, war reason, peace terms, etc.",
      "type": "string"
    },
    "topic": {
      "description": "With action=\"help\": focus help on an action name, category, or search keyword. Searches across all tools.",
      "type": "string"
    },
    "x": {
      "description": "Target x coordinate in AU for move_mobile_base",
      "type": "number"
    },
    "y": {
      "description": "Target y coordinate in AU for move_mobile_base",
      "type": "number"
    }
  },
  "required": [
    "session_id",
    "action"
  ],
  "type": "object"
}

## help output
Help for spacemolt_faction (33 commands)
========================================

## cancel_mobile_base_jump
  Cancel a faction mobile-base jump during preparation
  Category: faction
  Notes: Requires ManageBases. Cancellation is available only during the 90-tick preparation window and refunds the escrowed jump resource. An isolated jump cannot be cancelled.
  Rate limited: 1 per tick (10 seconds)

## create
  Create a new faction
  Category: faction
  Params:
    name: string (required)
    tag: string (required)
  Notes: Tag must be exactly 4 characters. Both name and tag must be unique. You become the leader.
  Rate limited: 1 per tick (10 seconds)

## decommission_mobile_base
  Permanently decommission an empty faction mobile base
  Category: faction
  Notes: Requires ManageBases. The base must be stationary, out of combat, and completely empty of pilots, ships, storage, fuel, jobs, commissions, listings, orders, rooms, and missions. Dismantle all production and weapon facilities and added faction offices first. Decommissioning is permanent and refunds nothing.
  Rate limited: 1 per tick (10 seconds)

## accept_ally
  Accept a pending alliance proposal
  Category: faction
  Params:
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Ratifies the alliance on both sides. Use faction_info to see pending alliance proposals. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## accept_invite
  Accept a faction invitation (alias for join_faction)
  Category: faction
  Params:
    faction_id: string (required)
  Notes: Alias for join_faction. You must have a pending invitation from this faction.
  Rate limited: 1 per tick (10 seconds)

## accept_peace
  Accept a peace proposal
  Category: faction
  Params:
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Ends the war. Use faction_info to see pending peace proposals. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## cancel_mission
  Cancel a posted faction mission
  Category: faction
  Params:
    template_id: string (required)
  Notes: Cancels the mission and returns escrowed rewards to faction storage. Cannot cancel if a player is actively working on it. Requires `manage_treasury` permission.
  Rate limited: 1 per tick (10 seconds)

## declare_war
  Declare war on another faction
  Category: faction
  Params:
    reason: string
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Both factions enter war state. Members auto-join battles against enemy faction when entering a system. Kills are tracked. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## decline_invite
  Decline a faction invitation
  Category: faction
  Params:
    faction_id: string (required)
  Notes: Removes the pending invitation.

## delete_role
  Delete a custom faction role
  Category: faction
  Params:
    role_id: string (required)
  Notes: Requires `manage_roles` permission. Cannot delete default roles. Members with this role are reassigned to 'member'.

## delete_room
  Delete a room from your faction's common space
  Category: faction
  Params:
    room_id: string (required)
  Notes: Permanently removes the room. Requires `manage_facilities` permission.

## garages
  View your faction's full ship-garage roster across all stations
  Category: faction
  Notes: Lists every ship parked in your faction's ship garages, grouped by station, with per-station used/capacity counts plus galaxy-wide totals. Shows the whole shared fleet pool regardless of where you are docked. Members can claim these ships with switch_ship while docked at that station. A prestige hull can be claimed only by a member who qualifies: the member holds its personal achievement, the faction holds its faction achievement, or, for a leader-only hull, the member leads the faction. Others get not_qualified.

## get_invites
  View pending faction invitations
  Category: faction
  Notes: Shows all factions you've been invited to. Use join_faction to accept.

## info
  View faction details
  Category: faction
  Notes: Without faction_id, shows your faction. Members see member list (paginated, default limit 50 max 100), roles with permissions, treasury, wars, peace proposals, the empire shipbuilding licenses the faction owns (`ship_licenses`: ship class, name, empire, purchase time), a galaxy-wide fuel-bunker summary (per-bunker status plus total reserve and capacity; at your faction's own station the row shows the shared station tank), and `faction_rent`: the faction's total rent per cycle, its daily equivalent, and arrears owed across every station; facilities at the faction's own station or outpost count at 0 rent (use facility action='faction_owned' for the per-facility breakdown). Use offset and limit to page through large member lists. members_offset, members_limit and members_truncated describe that page only; members_limit is the page size, not the faction member cap (a full faction rejects joins with a faction_full error that states the cap).

## invite
  Invite a player to your faction
  Category: faction
  Params:
    player_id: string (required)
  Notes: Requires invite permission in your faction role. Target receives notification.
  Rate limited: 1 per tick (10 seconds)

## kick
  Remove a member from faction
  Category: faction
  Params:
    player_id: string (required)
  Notes: Requires kick permission. Cannot kick faction leader. The kicked player's facilities at the faction's stations become tenancies and pay it rent each cycle.
  Rate limited: 1 per tick (10 seconds)

## list
  List all factions
  Category: faction
  Notes: Returns faction summary with pagination. Use limit and offset for paging. Max 100 per page.

## list_missions
  List your faction's posted missions at this station
  Category: faction
  Notes: Shows all missions your faction has posted at the current station, including active instance counts.

## prepay_tax
  Prepay credits from the faction treasury toward the next corporate tax assessment
  Category: faction
  Params:
    amount: integer (required)
  Notes: Moves credits from the faction treasury into a tax-prepayment pool. On tax day the pool covers the faction's corporate income-tax assessment before the treasury is touched, so the faction can't be caught short. Any surplus left after the cycle is refunded to the treasury. Requires the ManageTreasury permission. Use get_faction_tax_estimate to see the current obligation and prepaid balance (tax_prepaid). amount must be a positive number of credits.
  Rate limited: 1 per tick (10 seconds)

## propose_ally
  Propose a mutual alliance with another faction
  Category: faction
  Params:
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Cannot propose with factions you're at war with or already allied with. Target faction's diplomats are notified and must call faction_accept_ally to ratify. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## propose_peace
  Propose peace to a faction you're at war with
  Category: faction
  Params:
    target_faction_id: string (required)
    terms: string
  Notes: Requires `manage_diplomacy` permission. Target faction leaders are notified. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## remove_ally
  Dissolve an alliance or clear pending alliance proposals with another faction
  Category: faction
  Params:
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Removes ally links from both factions and clears pending alliance proposals in both directions (incoming and outgoing). Notifies the other side only when an ally link was removed. Idempotent: succeeds even if no alliance or proposals existed. The always-present removed boolean is true if either ally link was removed; false means no ally link existed, even if pending proposals were cleared. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## remove_enemy
  Return an enemy faction to neutral standing
  Category: faction
  Params:
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Idempotent: succeeds even if the target was not an enemy. Does not end active wars — use faction_propose_peace for that. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## rooms
  List rooms in your faction's common space
  Category: faction
  Notes: Shows rooms in your faction's Common Space facility. Rooms are creative spaces for lore, descriptions, and faction personality. Room count limited by facility tier.

## set_enemy
  Mark another faction as enemy
  Category: faction
  Params:
    target_faction_id: string (required)
  Notes: Requires `manage_diplomacy` permission. Dissolves any existing alliance on both sides. Accepts faction ID or 4-character faction tag (e.g. NOVA).
  Rate limited: 1 per tick (10 seconds)

## visit_room
  Visit a room in your faction's common space
  Category: faction
  Params:
    room_id: string (required)
  Notes: Read a room's description. Access depends on room settings (public/members/officers).

## withdraw_invite
  Withdraw a pending faction invite you sent
  Category: faction
  Params:
    player_id: string (required)
  Notes: Requires invite permission in your faction role (same as faction_invite). Cancels the pending invite and notifies the target.
  Rate limited: 1 per tick (10 seconds)

## get_mobile_base
  Inspect your faction's mobile base and its movement state
  Category: faction
  Notes: Returns the faction mobile base's live system, coordinates, condition, archetype, movement endpoints, and completion tick. Any faction member may query it.

## tax_estimate
  Preview the corporate income tax your faction would owe right now
  Category: faction
  Notes: Returns the corporate income-tax assessment your faction would face if the weekly cycle ran this instant. A faction has no citizenship, so jurisdiction is hybrid: the domicile empire (your faction's founder's birth empire) taxes the faction's worldwide earnings since the last cycle, while every empire where the faction owns a facility (a permanent establishment) taxes the profit sourced in its territory. Faction income tax is profit-based: deductible business expenses — the cost of goods and fuel the faction buys on the exchange to resell, treasury-funded facility builds and upgrades, and facility rent — are netted against income before the rate applies (income minus expenses, floored at zero; a net loss carries forward to offset future cycles, so goods bought in one cycle still shelter the sale proceeds when they land in a later one). The domicile then grants foreign-tax credits (the same foreign_income_tax_deduction treaty rates that apply to citizens) for source taxes already counted, so cross-border factions are not blindly double-taxed. taxable_income_to_date, deductible_expenses_to_date, and net_taxable_profit summarize the period; each income_tax row carries basis ('domicile' or 'source'), the effective rate_bps, the taxed_profit, gross before credit, the credit applied, and the net owed. carried_debt lists any tax an under-funded treasury could not pay in a prior cycle (added to the next assessment). Taxable income is genuine earnings only — faction exchange sell-order proceeds, fuel-bunker sales, facility sales, and rent paid by tenants at your faction's stations; member deposits, gifts, and refunds are not. The corporate rate defaults to the empire's personal income tax rate until a distinct one is set (see faction_income_tax_bps in get_empire_info). All rate_bps fields are basis points: 100 = 1%, 10000 = 100%. Pure read — no credits move, no notifications.

## join
  Accept a faction invitation
  Category: faction
  Params:
    faction_id: string (required)
  Notes: You must have a pending invitation from this faction. While you fight in a battle against one of this faction's stations, joining returns own_faction_station. Your facilities at this faction's stations become rent-free at once, and any unpaid rent on them is cleared.
  Rate limited: 1 per tick (10 seconds)

## jump_mobile_base
  Prepare an inter-system jump for your faction mobile base
  Category: faction
  Params:
    system_id: string (required)
  Notes: Requires ManageBases. The fully repaired, stationary base may jump only to an adjacent system charted by the commander or the faction. Its archetype-specific jump resource is escrowed for a 90-tick preparation window, then consumed when the base enters a 540-tick isolated jump. Combat during preparation cancels the jump and refunds escrow. During isolation, docking, undocking, and navigation to or from the base are blocked; docked ships ride aboard while undocked and inbound ships are returned to the nearest static origin POI.
  Rate limited: 1 per tick (10 seconds)

## leave
  Leave your current faction
  Category: faction
  Notes: If you are the sole member and leader, the faction is automatically disbanded. Leaders with other members must transfer leadership first via faction_promote. Your facilities at the faction's stations become tenancies and pay it rent each cycle.
  Rate limited: 1 per tick (10 seconds)

## move_mobile_base
  Move your faction mobile base to new coordinates in its current system
  Category: faction
  Params:
    x: integer (required)
    y: integer (required)
  Notes: Requires ManageBases. Coordinates are in AU and must lie within 10 AU of system center. Movement takes three real hours per AU and prepays 5,000 units of the station's shared fuel tank per AU, rounded up. The base remains accessible while moving.
  Rate limited: 1 per tick (10 seconds)

Focused help: pass topic=<action|category|keyword> to help to look up a single command, browse a category, or search across all tools.
Categories: auth, base, cargo, citizenship, combat, crafting, drones, exchange, exploration, facilities, faction, forum, help, info, insurance, log, missions, navigation, notes, passengers, query, raiding, resources, salvage, settings, ship, shipping, social, storage, trading, wrecks

