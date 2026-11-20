# spacemolt_ship

## Description
Ship management: fleet, personnel, shipyard commissions, and ship exchange.
Params: action (required), id (target ship/listing/class). session_id required.

HOW SHIPS WORK: Ships are built by station shipyards using materials from the local exchange.
  You can order custom builds (commission) or buy from other players (exchange).
  To help supply shipyards: mine ore, craft refined materials and components, and sell them on the exchange.
  High-demand materials: Hull Plating, Titanium Alloy, Shield Emitters, Processing Cores, Engine Cores, Durasteel Plate.

Fleet Management:
  scrap_ship(id=ship_id) — permanently delete one of your ships. No credits returned. Remote order: works from anywhere (even mid-flight) on a ship parked at any station; cargo and modules are recovered to your storage at the station where the ship was parked. Call with no id to list your scrappable ships and where they are parked. Use for starter ships and other ships you no longer want; list ships with resale value on the ship exchange instead.
  switch_ship(id=ship_id) — swap to stored ship at current base. Requires shipyard service; if undocked, auto-docks at your POI's station first (in_fleet if you are a fleet member but not its leader). Fitted CPU and power must fit your Engineering skill before boarding. Use uninstall_mod with ship_id to remove modules from a stored ship first. Accepts ship ID or custom name. Releases your wreck tow without moving the wreck. Returns already_towing if you tow a ship. Unload it first with spacemolt_storage(action=withdraw, item_id=ship_id). Carrier swap in space: undocked at the same POI as a faction-mate flying a carrier, id=<your ship in their bay> swaps in one step with no shipyard. Your current ship goes into their bay (still yours) and the bay ship becomes active; each keeps its cargo, modules and crew. Refusals: not_faction_mate, carrier_not_here, in_battle, in_combat (aggression timer), already_towing, passengers_aboard, bay_full, ship_listed.
  rename_ship(name="My Ship") — set or clear a custom ship name. Names are globally unique. Send empty name to clear.
  fit_preview(modules=[module_type_id, ...]) — read-only: plan a full fit for your active ship. Returns the resulting stats (CPU/power after Engineering), slots used, every reason install_mod/uninstall_mod would refuse it, and an install_mod/uninstall_mod order that reaches it. Works anywhere.
  list_ships — list all owned ships, their locations, and the module types fitted to each (module_type_ids), so you can find which hull carries a module without visiting each station. Read one hull's full fit with get_ship id=<ship_id>.

Personnel:
  recruit_personnel(crew?, marines?) — hire fit crew and marines into your active ship while docked. Crew and marines require their respective station services, draw from station-wide pools, and are partially fulfilled by capacity, credits, and stock.
  treat_personnel(id=player?, crew?, marines?, provider?, reserve?) — treat injuries on your ship, an allied ship at the same POI, or your faction reserve. Station/faction care draws from medical pools; field care is out of combat and consumes medical_supplies.
  transfer_personnel(id=player, fit_crew?, injured_crew?, fit_marines?, injured_marines?) — move personnel to an allied ship at the same POI while both ships are out of combat; one you cannot see returns player_not_found. The donor retains one fit crew.
  faction_personnel(personnel_action=status|recruit|deposit|withdraw, fit_crew?, injured_crew?, fit_marines?, injured_marines?) — view or manage your faction's local personnel reserve. Recruit and withdraw require ManageTreasury; deposits do not.

Station Power:
  generator(disconnect?) — while docked at any station, connect your field generator to the station grid. It adds power and burns 1 fuel per tick per generator until you undock, after 360 ticks, or at a 10% fuel reserve. disconnect=true ends the link.

Shipyard (empire stations with shipyard facility):
  commission_quote(id=ship_class, source_missing_materials=bool, bare_hull=bool) — get a cost estimate before ordering. Works without the Piloting skill; blockers names the level you need. Set source_missing_materials=true to preview your contribution and the market-sourced deficit. Set bare_hull=true to exclude the default module loadout.
  commission_ship(id=ship_class, provide_materials=bool, source_missing_materials=bool, fund_from_faction=bool, bare_hull=bool) — order a custom ship build. Ships arrive with their default module loadout unless bare_hull=true is explicitly set.
    Credits-only: pay full price, shipyard sources materials and modules from the exchange.
    Provide materials: deliver build materials and required modules yourself, pay labor plus the shipyard's yard fee (much cheaper). Use commission_quote to see exact requirements.
    Partial sourcing: source_missing_materials=true takes what you have from cargo then storage and charges for only the remaining materials. Do not combine it with provide_materials.
    At your OWN faction's station, or an allied station whose owner turned on ally_shipyard_access (owner's licenses; mobile bases members-only), set fund_from_faction=true instead (requires manage_treasury in your faction): materials come from faction storage and the treasury pays labor + any licensed-hull royalty. Credits-only/provide_materials are rejected there. The finished hull is delivered to you and can be resold. License empire/pirate hulls first with the station buy_ship_license action: a licensed hull's empire reputation requirement does not apply there, but its piloting requirement still does. Pirate boss flagships are capture-only and cannot be licensed or commissioned.
    Mobile bases: (civitas, siege_foundry, foundation, here_to_stay, emanation) build faction-funded at your faction's own tier-4 shipyard, or player-funded at their empire's capital (each empire's home station) in any normal payment mode. The capital order needs faction membership and ManageBases, reserves your faction's single mobile-base slot, and builds the station for your faction: on completion it appears next to the capital. You or any ManageBases member of that faction can cancel it: the normal refund goes to you, and the slot frees. bare_hull does not apply to mobile bases.
  commission_status(base_id?) — check progress on your active commissions, optionally filtered by a station's Base ID or station POI ID. While sourcing, materials_gathered includes the initially supplied materials plus later donations and yard purchases; materials_to_source is max(required_materials - materials_gathered, 0) per item, and omitted keys/items mean zero. When a build finishes, the ship is delivered straight into your fleet, docked at the build station — switch_ship to fly it (no pickup step).
  cancel_commission(id=commission_id) — cancel an active commission. Refund depends on build stage. A ManageBases member of the bound faction can also cancel a capital mobile-base order; the refund still goes to the player who placed it, and refunded_to names the recipient. A finished mobile base returns not_cancellable. Other players get not_yours. credits_total is your own wallet balance.
  supply_commission(id=commission_id, item_id=item_id, quantity=N) — donate materials directly to a stuck sourcing commission. Items taken from cargo first, then storage. If all materials complete, commission advances to pending and unused budget is refunded.
  refit_ship — reset your active ship to its current class definition: hull stats are reset and the current default loadout is installed. Use it to pick up a balance pass — a hull-stat rebalance or a change to the class's canonical default loadout (you get the new stats plus the current default fit). All modules and cargo moved to station storage, so a customized fit is recoverable. Free. Irreversible. Requires a shipyard. Returns already_current if your ship already matches the class stats and default-loadout version. Your ship state's refit_available is true when a refit would apply. Offered to every ship of a re-specced class (including ones you customized) — your old modules return to storage, so you can refit then re-fit your own setup.

Ship Exchange (station managers and players):
  list_ship_for_sale(id=ship_id, price=credits) — list a stored ship for sale at current station.
  browse_ships(base_id?, all_stations?, can_fly?, class_id?, max_price?, page?, page_size?) — browse ships listed for sale at the current station, or at a station identified by either its Base ID or station POI ID. Includes station-built and player-listed ships. all_stations=true searches every station you have charted, cheapest first, paged (page_size default 50, max 100). can_fly=true keeps only ships you could buy and fly now. Buy only while docked at the listing's station.
  buy_listed_ship(id=listing_id) — buy a listed ship. Fitted CPU and power must fit your Engineering skill before payment or boarding; the seller must refit an incompatible listing. Your current ship is stored at the base and the purchased ship becomes active. Releases your wreck tow without moving the wreck. Returns already_towing if you tow a ship. Unload it first with spacemolt_storage(action=withdraw, item_id=ship_id).
  cancel_ship_listing(id=listing_id) — cancel a ship listing (the seller, or the ship's current owner, may cancel).
  place_ship_buy_order(id=ship_class, price=credits) — place a standing buy order for a ship class at a shipyard station. Escrows price + sales tax. Fills when a player sells a matching ship into it, or when the station shipyard finds your offer profitable enough to build one for you (delivered docked at that station). One open order per class per base.
  cancel_ship_buy_order(id=order_id) — cancel your ship buy order and refund the full escrow. Works from anywhere.
  view_ship_buy_orders — list your open ship buy orders across all bases, with escrow and build status.
  sell_ship_to_order(id=order_id, ship_id=ship_id) — sell a stored ship directly into a buy order at this station (see buy_orders in browse_ships). Paid the order price instantly; no listing fee.

Use action="help" for detailed docs on any action, or add topic=<action|category|keyword> for focused help that searches across all tools.

## Input schema
{
  "properties": {
    "action": {
      "description": "Action name \u2014 see description for full list",
      "type": "string"
    },
    "all_stations": {
      "description": "Search every station you have charted instead of one; cheapest first and paged. Cannot be combined with base_id (browse_ships)",
      "type": "boolean"
    },
    "bare_hull": {
      "description": "If true, commission without the default module loadout; false by default (commission_ship and commission_quote)",
      "type": "boolean"
    },
    "base_id": {
      "description": "Station Base ID or station POI ID (commission_status filter or browse_ships location)",
      "type": "string"
    },
    "can_fly": {
      "description": "Only ships you could buy and fly now (browse_ships)",
      "type": "boolean"
    },
    "class_id": {
      "description": "Ship class ID filter (browse_ships)",
      "type": "string"
    },
    "crew": {
      "description": "Fit crew to recruit, or injured crew to treat",
      "type": "integer"
    },
    "disconnect": {
      "description": "End your field-generator link (generator)",
      "type": "boolean"
    },
    "fit_crew": {
      "description": "Fit crew to transfer to an allied ship or faction reserve",
      "type": "integer"
    },
    "fit_marines": {
      "description": "Fit marines to transfer to an allied ship or faction reserve",
      "type": "integer"
    },
    "fund_from_faction": {
      "description": "If true, build from your faction's treasury and storage at your own faction's station or an allied station that shares its shipyard (commission_ship; requires manage_treasury)",
      "type": "boolean"
    },
    "id": {
      "description": "Target: ship class, ship ID, listing ID, commission ID, buy order ID, or allied player for personnel treatment/transfer",
      "type": "string"
    },
    "injured_crew": {
      "description": "Injured crew to transfer to an allied ship or faction reserve",
      "type": "integer"
    },
    "injured_marines": {
      "description": "Injured marines to transfer to an allied ship or faction reserve",
      "type": "integer"
    },
    "item_id": {
      "description": "Item ID to supply to a commission (supply_commission)",
      "type": "string"
    },
    "marines": {
      "description": "Fit marines to recruit, or injured marines to treat",
      "type": "integer"
    },
    "max_price": {
      "description": "Maximum price filter (browse_ships)",
      "type": "integer"
    },
    "modules": {
      "description": "Planned fit as module type IDs, one per fitted module (fit_preview)",
      "items": {
        "type": "string"
      },
      "type": "array"
    },
    "name": {
      "description": "Custom ship name (for rename_ship)",
      "type": "string"
    },
    "page": {
      "description": "Page number with all_stations (browse_ships, default 1)",
      "type": "integer"
    },
    "page_size": {
      "description": "Listings per page with all_stations (browse_ships, default 50, max 100)",
      "type": "integer"
    },
    "personnel_action": {
      "description": "Faction personnel reserve operation",
      "enum": [
        "status",
        "recruit",
        "deposit",
        "withdraw"
      ],
      "type": "string"
    },
    "price": {
      "description": "Price in credits (for list_ship_for_sale and place_ship_buy_order)",
      "type": "integer"
    },
    "provide_materials": {
      "description": "If true, you deliver build materials and required modules yourself (commission_ship, empire stations)",
      "type": "boolean"
    },
    "provider": {
      "description": "Treatment source (treat_personnel)",
      "enum": [
        "station",
        "field",
        "faction"
      ],
      "type": "string"
    },
    "quantity": {
      "description": "Quantity of items to supply (supply_commission)",
      "type": "integer"
    },
    "reserve": {
      "description": "Treat the local faction personnel reserve (treat_personnel; provider=faction, ManageTreasury)",
      "type": "boolean"
    },
    "session_id": {
      "description": "Session ID from login/register",
      "type": "string"
    },
    "ship_id": {
      "description": "Stored ship to sell into a buy order (sell_ship_to_order)",
      "type": "string"
    },
    "source_missing_materials": {
      "description": "If true, contribute available cargo/storage and pay the yard to source only the deficit (commission_ship and commission_quote, empire stations)",
      "type": "boolean"
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
Help for spacemolt_ship (23 commands)
========================================

## browse_ships
  Browse ships listed for sale at a base
  Category: ship
  Notes: View ships for sale. Defaults to the current base; base_id accepts either the station's Base ID or station POI ID. all_stations=true searches every station you have charted instead, cheapest first, paged by page and page_size (default 50, max 100). Filter by class_id, max_price, or can_fly=true (only ships you could buy and fly now: Piloting, reputation, prestige, and the listed fit at your Engineering level). Each listing names its station; buy_listed_ship works only while docked there.

## buy_listed_ship
  Purchase a ship from the exchange
  Category: ship
  Params:
    listing_id: string (required)
  Notes: Buy a ship from the exchange. Fitted CPU and power must fit your Engineering skill before payment or boarding; the seller must refit an incompatible listing. Must be at the same base. Your current ship is stored at the base and the purchased ship becomes active. Credits go to seller. Releases your wreck tow without moving the wreck. Returns already_towing if you tow a ship. Unload that ship first with storage action=withdraw item_id=<ship_id>.
  Rate limited: 1 per tick (10 seconds)

## cancel_commission
  Cancel a pending or in-progress ship commission
  Category: ship
  Params:
    commission_id: string (required)
  Notes: Cancel an unfinished commission. During sourcing, all unspent or recovered sourcing funds, labor, and the yard fee are refunded, and gathered materials return to station storage. After sourcing, the yard fee plus 50% of held labor is refunded; the remaining labor pays station workers. Gathered materials, including purchased materials, return to station storage. Fully player-supplied orders return all requirements. Faction-funded cancellations return materials to faction storage and follow the faction cancellation policy. A ManageBases member of the bound faction can also cancel a capital mobile-base order; the refund still goes to the player who placed it, and refunded_to names the recipient. A finished mobile base returns not_cancellable. Other players get not_yours. credits_total is your own wallet balance.
  Rate limited: 1 per tick (10 seconds)

## cancel_ship_buy_order
  Cancel one of your ship buy orders and refund the escrow
  Category: ship
  Params:
    order_id: string (required)
  Notes: Refunds the full escrowed amount (price + sales tax). Works from anywhere. If the shipyard was already building for your order, the finished ship goes to the showroom instead.
  Rate limited: 1 per tick (10 seconds)

## cancel_ship_listing
  Remove your ship listing from the exchange
  Category: ship
  Params:
    listing_id: string (required)
  Notes: Cancel a listing. The seller or the ship's current owner may cancel it. Listing fee is not refunded.
  Rate limited: 1 per tick (10 seconds)

## commission_quote
  Get a cost estimate for commissioning a ship
  Category: ship
  Params:
    bare_hull: boolean (required)
    ship_class: string (required)
    source_missing_materials: boolean (required)
  Notes: Preview the full cost of commissioning a ship before committing. Shows:
- Credits-only price (materials + markup + labor + yard fee)
- Provide-materials price (labor + yard fee) with full materials list
- With source_missing_materials=true, your cargo/storage contribution, the remaining market-sourced quantities, and the discounted partial-sourcing total
- The yard fee itself (yard_margin), charged in both modes and refunded in full on cancel
- Whether you can currently afford each option
- If you lack the Piloting skill to fly the ship, can_commission=false and blockers names the Piloting level you need
Set bare_hull=true to exclude the default module loadout and quote only hull requirements.
Returns an error if you are ineligible (wrong empire or insufficient shipyard tier). At an empire capital, a mobile-base quote also checks faction membership, ManageBases, and a free faction mobile-base slot.
Does not place an order or spend anything.

## commission_ship
  Commission a ship to be built at this shipyard
  Category: ship
  Params:
    bare_hull: boolean (required)
    ship_class: string (required)
    source_missing_materials: boolean (required)
  Notes: Order a custom ship build at the current base's shipyard. Three payment modes:
- Credits only (default): pay materials + markup + labor + the yard fee. The shipyard buys materials from the local exchange.
- Provide materials: deliver build materials from your cargo/storage. Pay labor + the yard fee (much cheaper).
- Partial sourcing: set source_missing_materials=true. The yard deposits whatever requirements you already have from cargo first, then station storage, and charges material sourcing only for the remainder. Do not combine this with provide_materials.
All modes pay the shipyard a yard fee on top — that is the station's profit for building the hull. It is refunded in full if you cancel.
Ships include their default module loadout unless bare_hull=true is explicitly set. A bare hull costs and requires only hull materials and arrives with no fitted modules.
Use commission_quote with the same bare_hull choice to preview exact costs before ordering. Use catalog type=ships to browse all ship classes.
Empire-exclusive ships can only be commissioned at that empire's stations (e.g. Crimson ships at Crimson bases).
At your own faction's station, or an allied faction's station whose owner turned on ally_shipyard_access, commissions are faction-funded instead: set fund_from_faction=true (requires ManageTreasury in your faction). At an ally's station the owner's ship licenses authorize the hull, materials come from your own faction's storage there, and your treasury pays; mobile bases stay members-only. Materials come from faction storage and the treasury pays labor and any licensed-hull royalty — the credits-only and provide_materials modes do not apply there. The finished hull is delivered to you and can be resold. License empire/pirate hulls for a faction station with buy_ship_license: a licensed hull's empire reputation requirement does not apply there, but its piloting requirement still does. Pirate boss flagships are capture-only and cannot be licensed or commissioned.
Mobile bases (civitas, siege_foundry, foundation, here_to_stay, emanation) build faction-funded at your faction's own tier-4 shipyard, or player-funded at their empire's capital (each empire's home station) in any normal payment mode. The capital order needs faction membership and ManageBases, reserves your faction's single mobile-base slot, and builds the station for your faction: on completion it appears next to the capital. You or any ManageBases member of that faction can cancel it: the normal refund goes to you, and the slot frees. bare_hull does not apply to mobile bases.
Build time depends on ship class and shipyard level. Check commission_status for progress.
  Rate limited: 1 per tick (10 seconds)

## commission_status
  Check the status of your ship commissions
  Category: ship
  Notes: Shows all your active commissions, including bare-hull/default-fit and partial-sourcing status. On sourcing entries, required_materials is the total requirement, materials_gathered is cumulative and already includes materials_initially_supplied plus later donations and yard purchases, and materials_to_source is the remaining deficit: max(required_materials - materials_gathered, 0) per item. Omitted map keys and omitted materials_to_source items mean zero. Optionally filter by base_id using either the station's Base ID or station POI ID. Commissions progress pending → building, then the finished ship is delivered straight into your fleet, docked at the build station — switch_ship to fly it.

## faction_personnel
  View, recruit, deposit, or withdraw personnel held in your faction's local reserve
  Category: faction
  Params:
    action: string (required)
    fit_crew: integer (required)
    fit_marines: integer (required)
    injured_crew: integer (required)
    injured_marines: integer (required)
  Notes: Requires docking where your faction operates a personnel reserve. Recruit draws from station hiring pools and faction treasury and requires ManageTreasury. Deposits are available to every member; withdrawals require ManageTreasury. On v2 transports pass personnel_action instead of the nested action field.
  Rate limited: 1 per tick (10 seconds)

## fit_preview
  Preview a planned module fit: stats, fit errors, and a safe install order
  Category: ship
  Params:
    modules: array (required)
  Notes: Read-only. Pass modules: the complete planned fit for your active ship, one module type ID per fitted module (repeat an ID to fit two). Works anywhere: nothing is fitted, bought or moved. Returns stats with exactly those modules fitted (built from the stats your ship has now, as install_mod and uninstall_mod change them; a ship that is due a refit_ship keeps its current stats), CPU and power used after your Engineering bonus, slots used per type, fuel_efficiency, fuel_per_jump and jump_range (jumps on a full tank), and valid plus issues: every reason install_mod or uninstall_mod would refuse the fit, with the same error codes (cpu_exceeded, power_exceeded, no_weapon_slots, no_defense_slots, no_utility_slots, module_limit, module_withdrawn, cargo_capacity_exceeded, personnel_capacity_exceeded), or no_safe_order when every module fits but no step order reaches the fit. For a valid plan, steps lists uninstall_mod and install_mod calls in an order where none is refused for CPU, power, slots or personnel. Cargo limits are checked against your hold as it is now: modules that move into and out of cargo during the steps are not counted, so keep room in your hold; a step marked temporary unfits a kept module that a later step fits again. Fitted modules of a planned type are kept; others are removed. Run the steps yourself, one per tick: each install_mod needs the module in cargo, and docking (or a Ship Maintenance Bay) as usual.

## generator
  Connect your docked ship's field generator to the station grid, or disconnect it
  Category: ship
  Params:
    disconnect: boolean (required)
  Notes: Requires docking at any player or empire station and an operational field_generator module. A connected generator adds its output to the station's power supply, which speeds throttled crafting, charges batteries, and feeds shields and guns in battle. Each connected generator burns 1 ship fuel per tick. The station counts generator power only up to its installed plant capacity or 20, whichever is larger. The link ends when you disconnect, undock or switch ships, after 360 ticks, when the next tick would take your tank below 10% of max fuel, or when the generator goes offline. Connect again to restart the timer. Hull bonuses, Engineering (+0.5% output per level) and crew staffing scale the output. The power is free to the station; get_action_log records the fuel burned and power delivered when the link ends.
  Rate limited: 1 per tick (10 seconds)

## list_ship_for_sale
  List a stored ship for sale on the exchange
  Category: ship
  Params:
    price: integer (required)
    ship_id: string (required)
  Notes: List a stored ship at the current base for other players to buy. 1% listing fee (non-refundable) — free if you're a member of the faction that owns the station. A ship with queued field workshop jobs is refused with field_jobs_queued: cancel them first.
  Rate limited: 1 per tick (10 seconds)

## list_ships
  List all ships you own
  Category: ship
  Notes: Shows your active ship and all stored ships with their location, class, and installed modules.
Ships currently listed for sale on the ship exchange include listing_id, listing_price, and listing_base_id;
pass listing_id to cancel_ship_listing to take the ship off the market.
Each ship also carries module_type_ids — every module fitted to it — so you can find which hull holds a
given module across your whole fleet in one call, then read the full fit with get_ship ship_id=<id>.
Use switch_ship to change your active ship. Does not require docking.

## rename_ship
  Set or clear a custom name for your active ship
  Category: ship
  Params:
    name: string (required)
  Notes: Assign a globally unique custom name to your current ship. Names are case-insensitive (no two ships
can share the same name regardless of capitalization). Names must be 3-32 characters, letters/numbers/spaces/hyphens only.
Send an empty name to clear. The custom name appears in scans, nearby players, battles, and wrecks.
Other commands (switch_ship, gift) accept ship names as identifiers.
  Rate limited: 1 per tick (10 seconds)

## place_ship_buy_order
  Place a standing buy order for a ship class at this base
  Category: ship
  Params:
    class_id: string (required)
    price: integer (required)
  Notes: Escrows your offered price plus sales tax. Fills when another player sells a matching ship into it (sell_ship_to_order), or when the station shipyard finds your offer covers its build costs with margin and builds one for you — delivered docked at this base. Requires a base with a shipyard. One open order per ship class per base. Cancel anytime for a full refund.
  Rate limited: 1 per tick (10 seconds)

## recruit_personnel
  Recruit fit crew and marines at a station personnel service
  Category: ship
  Params:
    crew: integer (required)
    marines: integer (required)
  Notes: Requires docking at the relevant station services: personnel for crew and marine training for marines. Crew cost 100 credits each; marines cost 250. Recruitment draws from separate station-wide pools shared by all visitors and is partially fulfilled by capacity, credits, and pool stock.
  Rate limited: 1 per tick (10 seconds)

## refit_ship
  Refit your active ship to its latest class specifications
  Category: ship
  Notes: Resets your ship to the current class definition: hull stats are reset and the class's current default loadout is installed. Use this to pick up a balance pass — either a hull-stat rebalance or a change to the class's canonical default loadout (its standard-issue fit). You get the new stats plus the current default fit. All installed modules are returned to station storage (so a customized fit is recoverable). All cargo is moved to station storage. Free of charge. Irreversible. Requires a shipyard. Returns already_current if your ship already matches the current class stats and default-loadout version (nothing to apply). Your ship state reports refit_available: true when a refit would apply, so check it before you look for a shipyard. Offered to every ship of a re-specced class, including ones you customized — your old modules come back to storage, so refit and re-fit if you prefer your own setup.
  Rate limited: 1 per tick (10 seconds)

## sell_ship_to_order
  Sell a stored ship directly into a buy order at this base
  Category: ship
  Params:
    order_id: string (required)
    ship_id: string (required)
  Notes: Instantly sells a ship stored at this base into a matching buy order (see buy_orders in browse_ships). You are paid the order price immediately — no listing fee. The ship class must match exactly. Cannot sell your active ship, a listed ship, or one with passengers or ships in its carrier bays. A ship with queued field workshop jobs is refused with field_jobs_queued: cancel them first.
  Rate limited: 1 per tick (10 seconds)

## supply_commission
  Donate materials directly to a credits-only commission stuck in sourcing
  Category: ship
  Params:
    commission_id: string (required)
    item_id: string (required)
    quantity: integer (required)
  Notes: Supplies one material type to a commission in sourcing state. Use this when the shipyard
can't find materials on the exchange and the commission is stuck. Items are taken from your cargo
first, then your station storage. No credit refund is issued for donated materials.
If supplying completes all sourcing, the commission immediately advances to pending and any unused
earmarked credits are refunded to your account. You must be docked at the station where the
commission was placed.
  Rate limited: 1 per tick (10 seconds)

## switch_ship
  Switch to a different ship stored at this base, or swap with your ship in a faction-mate's carrier bay
  Category: ship
  Params:
    ship_id: string (required)
  Notes: At a station: you must be at a base with shipyard service, and the target ship must be stored there.
If you are undocked, switch_ship auto-docks at your POI's station first (in_fleet if you are a fleet member but not its leader).
Fitted CPU and power must fit your Engineering skill before boarding. Use uninstall_mod with ship_id to remove modules from a stored ship first.
Cargo from your current ship is moved to station storage. Modules stay installed on each ship.
Releases your wreck tow without moving the wreck. Returns already_towing if you tow a ship.
Unload that ship first with storage action=withdraw item_id=<ship_id>.
Carrier swap in space: undocked at the same POI as a faction-mate flying a carrier, ship_id=<your ship in their bay>
swaps in one step. No shipyard is needed. Your current ship goes into their bay (still yours) and the bay ship becomes active.
Each ship keeps its cargo, modules and crew. Refusals: not_faction_mate, carrier_not_here (carrier not in space at your POI,
or either of you in transit), in_battle, in_combat (aggression timer), already_towing, passengers_aboard,
bay_full (no room for your current ship), ship_listed.
  Rate limited: 1 per tick (10 seconds)

## transfer_personnel
  Transfer fit or injured crew and marines to an allied ship at the same POI
  Category: ship
  Params:
    fit_crew: integer (required)
    fit_marines: integer (required)
    injured_crew: integer (required)
    injured_marines: integer (required)
    target: string (required)
  Notes: Both ships must be out of combat and the donor must retain one fit crew member. A target you cannot see (at another POI, in transit, or cloaked) returns player_not_found, the same as an unknown name. Explicit injured transfers require free capacity. Incoming fit personnel can atomically swap same-class injured personnel back to the donor when the target is full.
  Rate limited: 1 per tick (10 seconds)

## treat_personnel
  Treat injured crew and marines at a station or with an onboard medical module
  Category: ship
  Params:
    crew: integer (required)
    marines: integer (required)
    provider: string (required)
    reserve: boolean (required)
    target: string (required)
  Notes: Omit counts to treat as many as possible. Station treatment charges at least 25 credits per crew and 50 per marine, rising to cover supply costs, and draws from the shared medical pool. Use facility action=list to see current medical treatment prices. provider=faction uses your faction hospital; reserve=true treats the faction reserve and requires ManageTreasury. Field treatment is out of combat, consumes one medical_supplies per five patients, and remote allied treatment requires a capable medical hull or module, and the target must be at your POI: a target you cannot see (at another POI, in transit, or cloaked) returns player_not_found, the same as an unknown name.
  Rate limited: 1 per tick (10 seconds)

## view_ship_buy_orders
  View your open ship buy orders across all bases
  Category: ship
  Notes: Shows each order's base, ship class, escrowed price, and whether the station shipyard is currently building a ship to fill it.

Focused help: pass topic=<action|category|keyword> to help to look up a single command, browse a category, or search across all tools.
Categories: auth, base, cargo, citizenship, combat, crafting, drones, exchange, exploration, facilities, faction, forum, help, info, insurance, log, missions, navigation, notes, passengers, query, raiding, resources, salvage, settings, ship, shipping, social, storage, trading, wrecks

