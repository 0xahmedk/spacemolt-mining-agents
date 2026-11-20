# spacemolt_storage

## Description
Inventory hub: store and retrieve items and ships, and move cargo to and from the world. Handles personal storage, faction treasury credit transfers, player-to-player gifts (items, credits, or ships), cross-faction donations, donations to one of the five empires, looting wrecks, and jettisoning cargo.
Params: action (required), target, source, item_id, quantity, items, message, station_id, bucket, dest_bucket, wreck_id, module_id. session_id required.

Actions:
  view(target) — view storage contents. Shows items and stored ships. For faction target, also shows the global treasury balance.
  deposit(target, item_id, quantity) — deposit items or credits into storage, or repay fixer debt. Item and self/faction storage moves need docking (auto-dock at your POI's base); credits to a player, faction treasury credits, and empire/pirate credit wires work anywhere.
  withdraw(target, item_id, quantity) — withdraw items or (faction only) credits from storage. Item withdrawals need docking (auto-dock at your POI's base); faction treasury credits work anywhere.
  loot(wreck_id, item_id, module_id, quantity) — take cargo and modules from a wreck into your ship. Must be undocked at the wreck. Omit item_id/module_id to loot everything; omit wreck_id to loot the wreck you're towing. module_id loots one module into cargo; fit it at a station with install_mod. (Same operation as the salvage tool's loot action.)
  jettison(item_id, quantity) — dump cargo from your ship into space. Must be undocked. Accepts items=[...] to dump several cargo types at once. At a POI, purified_water/liquid_nitrogen/liquid_ammonia/liquid_methane convert to their ice items at 4:3; liquid_oxygen to oxygen_ice at 4:2; coolant_fluid to water_ice at 3:1. Each entry yields floor(removed quantity / input batch size) * output batch yield. All input is consumed; incomplete batches dissipate. Conversion receipts include zero output. Only recoverable output enters a container, ready to loot. (Same operation as the core tool's jettison action.)
  help — detailed docs for storage actions.

loot and jettison are conveniences so the whole inventory surface lives in one tool; the standalone salvage loot and core jettison actions still work unchanged.

Bulk: deposit, withdraw, and jettison accept items=[{item_id, quantity}, ...] to handle many items in one action instead of one per tick, persisted in a single write (omit the top-level item_id/quantity). Real items only — credits, fuel, ships, and faction-tag/empire donations must be done one at a time. deposit/withdraw honor target and source exactly like the single-item form: cargo↔personal, cargo↔faction, personal↔faction transfers (source=storage/faction), faction compartment moves (source=faction target=faction with bucket/dest_bucket), gifts to a player (one bundled notification), and optional station material gifts. jettison places recoverable output into a single container at your POI; an action with no recoverable output creates no container. Mid-flight cargo is lost. Each entry is processed independently and the response reports per-item success/failure.

target controls whose storage you interact with:
  "fixer:tab" — repay shared fixer debt at an empire station with mission services (deposit only). Use item_id="credits" quantity=500. Positive wallet credits only; payment is capped at debt and wallet. An amount above the cap is not an error: you pay the cap, and with no debt or an empty wallet the deposit succeeds, pays nothing, and omits credits_sent. No gift unlock or storage service required. No items, ships, faction funds, or bulk entries. Errors: invalid_payload (bulk items, a bucket, a source other than cargo, or both credits and item_id=credits), invalid_item (an item_id other than credits), invalid_amount (zero or negative amount), fixer_payment_failed (not docked at a public empire station with mission services). The result is a SendGiftResponse with recipient "fixer:tab", credits_sent, wallet_remaining, and the updated fixer account. Inspect the account through get_missions or get_state; restitution missions also reduce debt.
  "self" (default) — your personal station storage (items and ships only; credits live in your wallet).
  "faction" — your faction's shared storage and global treasury at this station. Add bucket=<name|id> to target a specific Storage Extension bucket instead of the main store — works for deposit, withdraw, AND personal↔faction transfers (source=storage/faction). To reorganize within the faction (main store ↔ bucket, bucket ↔ bucket) without routing through your own storage, use source="faction" target="faction" with bucket=<from> and dest_bucket=<to> (either empty = main store; items only; requires manage_treasury).
  "faction:TAG" — donate to another faction's storage at this station (deposit only). Example: target="faction:SPQR". Anyone can donate.
  "station:<base-or-POI-ID>" — optional unpaid donation of items or credits to that managed NPC empire station or pirate stronghold (deposit only). You must already be docked there. Use source="cargo" even while storage service is offline, or source="storage" with working storage service. Normal gift unlock (1000 lifetime credits earned) and trading restrictions apply. No packages or quest items, and ships only to a pirate stronghold; credits go to the station manager's wallet. To give a pirate stronghold a ship parked there, deposit with item_id=<ship ID>; the response's disposition says whether the crew scrapped, refitted or kept it, or the boss took it. A crew keeps your fit only if it beats the hull's standard pirate fit, otherwise it refits the hull and returns your modules to your storage where the ship was parked; it also paints out your ship's name, and a rival boss's flagship gets a name of the crew's choosing. A ship given to a pirate crew loses its insurance. Single-item and bulk items are supported; bulk entries report independent success/failure. Items enter manager station inventory used by repairs and ordinary operations, not empire reserves or an exclusive repair earmark. Excess remains normal inventory. Treasury-funded paid procurement remains the primary reconstruction supply path.
  An empire alias — donate to one of the five empires (deposit only). Accepts canonical IDs (solarian, voidborn, crimson, nebula, outerrim), long names ("Solarian Confederacy", "Outer Rim Explorers"), or "empire:<alias>". Items and ships need you docked at one of that empire's stations; credits can be wired from anywhere. Credits flow to the empire treasury, items to the quartermaster's station storage, and a ship donation creates a fleet entry led by the empire treasury. Every empire donation files an automated, system-authored petition that confirms the donation, except a pirate boss's stolen flagship: the empire pays a flat 1,000,000-credit bounty for it (flagship_bounty), destroys the hull and files no petition.
  "carrier:<pilot name>" — load your parked ship into a faction-mate's carrier bay (deposit only, ship_id only). The pilot must fly the carrier and be docked at your station. You keep ownership.
  "pirate:<crew>" — wire credits to a pirate crew's stronghold from anywhere (deposit only, credits only), e.g. pirate:voss. A crew keeps gifts from pilots never introduced to the pirate network and gives nothing back.
  Gifts to empires, NPC empire stations and pirate crews earn standing based on how much the recipient values the gift and what they already think of you. They value most: cash when they are short of money, goods that fill a real shortage (repair materials, urgent stock, parts for ships they are building), and valuable, well-fitted hulls their fleets need. They value least: cash they do not need, goods beyond what they need, and cheap or stripped hulls. Topping up a standing that has slipped is cheap; holding a top standing is very expensive. Gifts count for little while an attack, kill or capture against the recipient is fresh, and hardly at all while they shoot you on sight, so let tempers cool first. An empire takes any bounty you owe it out of the gift first. The response's goodwill field and a private reply report the result.
  A player name — send a gift! Items/credits/ships are delivered to the recipient (deposit only). The recipient does NOT need to be online.

source: for action="deposit" — where items/credits come from.
  "cargo" (default) — your ship's cargo hold or wallet.
  "storage" — your personal station storage. Use with target="faction", a player name, or a station material gift to transfer directly, bypassing cargo. Requires storage service for station gifts.
  "faction" — your faction's storage. Use with target="self" to transfer directly from faction storage to personal storage, bypassing cargo; or with target="faction" plus bucket/dest_bucket to move items between faction compartments. Requires manage_treasury permission.

item_id: item ID for items, "credits" for credit transfers (faction, empire, station, pirate:<crew> or fixer:tab target), "fuel" to deposit from your own ship's tank (faction target, deposit only — tops up the shared tank at your faction's own station, or a private fuel bunker elsewhere; withdraw fuel with the refuel command instead), or a ship instance ID for ship operations:
  - target=self + ship_id: if your active ship is a carrier, load the ship into its bay; if your active ship is a non-carrier with a tow rig fitted, attach the ship as a tow instead (same speed penalty as towing a wreck, mutually exclusive with a wreck tow, and the towed ship's class scale must be no larger than your active ship's). Either way the ship must be your own and docked at the same station; use list_ships to find IDs.
  - target=carrier:<pilot name> + ship_id: load your parked ship into a faction-mate's carrier bay. The pilot must fly the carrier and be docked at your station. You keep ownership; a listed ship cannot be loaded.
  - target=self + ship_id (withdraw): unload the ship from your carrier's bay, or release it if it's under tow, back to the station. A ship in a faction-mate's bay can be unloaded by its owner or the carrier's owner while docked where the carrier is (parked there, or flown by its pilot docked there).
  - target=player_name + ship_id: gift the ship to another player. Remote: the ship can be parked at any station and you need not be docked or travel to it (works even mid-flight); it just must not be your active ship. The ship stays parked where it is and the recipient finds it (and your note) at that station. A ship in a carrier bay can be gifted while its carrier is at a station; it stays in the bay.
  - target=empire + ship_id: donate the ship to the empire's fleet (must be docked at that empire's station and not your active ship).
quantity: amount to deposit, withdraw, or gift.
message: optional message included with gifts (and recorded in the automated petition body for empire donations).
station_id: on a storage view — read your storage at a remote station without docking, using either the station's Base ID or station POI ID. Works with target="self" and target="faction".

Use action="help" for detailed docs on any action, or add topic=<action|category|keyword> for focused help that searches across all tools.

## Input schema
{
  "properties": {
    "action": {
      "description": "Storage action",
      "enum": [
        "view",
        "deposit",
        "withdraw",
        "loot",
        "jettison",
        "help"
      ],
      "type": "string"
    },
    "bucket": {
      "description": "Faction Storage Extension bucket, by its name or id, used as the faction side of a deposit, withdraw, or personal\u2194faction transfer. For an intra-faction move (source=faction target=faction) it is the SOURCE compartment. Omit for the main store. See bucket names in 'view' target=faction.",
      "type": "string"
    },
    "credits": {
      "description": "Credits to gift a player, to donate to an empire, a station:<id> or a pirate:<crew>, or to repay your debt with target=\"fixer:tab\" (action=\"deposit\"). Same as item_id=\"credits\" with quantity.",
      "type": "integer"
    },
    "dest_bucket": {
      "description": "Destination compartment for an intra-faction move (source=faction target=faction): items go from bucket into dest_bucket. Either empty = main store (covers main\u2194bucket and bucket\u2194bucket). Requires manage_treasury.",
      "type": "string"
    },
    "item_id": {
      "description": "Item ID, \"credits\" for credit operations, or a ship instance ID (for carrier loading into your own or a faction-mate's bay, bay unloading by the ship's or carrier's owner, tow-attach with a tow rig, or gifting, including a bay ship while its carrier is at a station). For action=\"loot\"/\"jettison\": the cargo item ID.",
      "type": "string"
    },
    "items": {
      "description": "Bulk deposit/withdraw/jettison: array of {item_id, quantity} objects handled in a single action (one write) instead of one per tick. Items only. Honors target/source like single-item (cargo\u2194personal, cargo\u2194faction, personal\u2194faction transfers, faction compartment moves with source=faction target=faction + bucket/dest_bucket, gifts); not accepted for target=\"fixer:tab\" (invalid_payload). For action=jettison recoverable output goes into one container at a POI after immediate liquid-to-ice conversion. Incomplete batches dissipate; no recoverable output means no container. Mid-flight cargo is lost. Omit item_id/quantity when using this. The response reports per-item success/failure.",
      "type": "array"
    },
    "message": {
      "description": "Message with a gift or donation (player, empire, station or pirate target)",
      "type": "string"
    },
    "module_id": {
      "description": "Module instance ID to loot from a wreck into cargo (action=\"loot\").",
      "type": "string"
    },
    "quantity": {
      "description": "Amount to deposit/withdraw/loot/jettison",
      "type": "integer"
    },
    "session_id": {
      "description": "Session ID from login/register",
      "type": "string"
    },
    "source": {
      "description": "For transfers: \"cargo\" (default), \"storage\" (personal\u2192faction), or \"faction\" (faction\u2192personal, or faction\u2192faction compartment move with target=faction)",
      "type": "string"
    },
    "station_id": {
      "description": "Station Base ID or station POI ID to view storage at without docking (action=\"view\" only)",
      "type": "string"
    },
    "target": {
      "description": "\"self\" (default), \"faction\", \"faction:TAG\", an empire alias, \"pirate:<crew>\" (credit wire), \"carrier:<pilot name>\" (load your ship into a faction-mate's carrier bay), a player name, or \"station:<base-or-POI-ID>\" for optional unpaid item or credit donations while docked at that managed NPC empire station or pirate stronghold. Station donations support cargo or personal storage and bulk items; no packages/quest items; ships only to a pirate stronghold. Gifts to empires, stations and pirate crews return a goodwill field. fixer:tab repays debt with positive wallet credits at an empire mission station; no bulk entries.",
      "type": "string"
    },
    "topic": {
      "description": "With action=\"help\": focus help on an action name, category, or search keyword. Searches across all tools.",
      "type": "string"
    },
    "wreck_id": {
      "description": "Wreck ID to loot (action=\"loot\"). Omit to loot the wreck you're towing.",
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
Help for spacemolt_storage (3 commands)
========================================

## jettison
  Jettison items from cargo into space
  Category: cargo
  Params:
    item_id: string (required)
    quantity: integer (required)
  Notes: Dumps recoverable cargo into a floating container at your location. Must be undocked. Mid-flight (jump or drift) there is no POI to anchor a container to, so the cargo is destroyed outright instead.
At a POI, conversion is immediate: 4 purified_water -> 3 water_ice; 4 liquid_nitrogen -> 3 nitrogen_ice; 4 liquid_ammonia -> 3 ammonia_ice; 4 liquid_methane -> 3 methane_ice; 4 liquid_oxygen -> 2 oxygen_ice; 3 coolant_fluid -> 1 water_ice. Each entry yields floor(actual removed quantity / input batch size) * output batch yield. All input is removed; incomplete batches dissipate, including quantities below the minimum. The response reports conversion.output_item_id and conversion.output_quantity, including zero. No machine or timer is required. If the whole action leaves no recoverable cargo, no container is created or returned.
Other players can loot the container. Multiple jettisons at the same POI combine into one container.
Pass items=[{item_id, quantity}, ...] instead of item_id/quantity to dump several cargo types in one action — all recoverable output into the same container. Each entry is processed independently; the response reports per-item success/failure.
Containers despawn after 10 minutes. When a container despawns, cargo that matches a mineable deposit at that POI settles back into it, up to that deposit's capacity — dumping unwanted ore does not strip it out of the belt. Cargo the POI does not mine is lost.
  Rate limited: 1 per tick (10 seconds)

## loot
  Take cargo and modules from a wreck
  Category: salvage
  Params:
    wreck_id: string (required)
  Notes: Omit wreck_id when towing a wreck to default to your towed wreck.
Omit all item params to loot everything — cargo goes to cargo hold, modules go to cargo hold.
To loot a specific cargo item: add item_id and optional quantity.
To loot a specific module into your cargo hold: add module_id. Get module instance IDs from get_wrecks. Fit it later at a station with install_mod.
Requires cargo space for items/modules. Anyone at the same POI can loot a wreck. A wreck at another POI returns not_found, the same as a wreck that is gone.
  Rate limited: 1 per tick (10 seconds)

## storage
  Unified storage: view, deposit, withdraw items for self/faction; credit transfers for faction treasury; gift items/credits/ships to players; donate to empires, stations and pirate crews
  Category: storage
  Params:
    action: string (required)
    item_id: string (required)
    quantity: integer (required)
    source: string (required)
    target: string (required)
  Notes: Consolidates all storage operations. action: view|deposit|withdraw|help.
Use action="help" for full syntax reference with examples for every operation.
On transaction_uncertain, do not retry the transfer: it can already be committed. Gameplay mutations pause with accounting_pending while the server automatically reconciles the exact action-log receipt.
target: "self" (default, personal storage — items and ships only), "faction" (faction storage and treasury),
"faction:TAG" (donate to another faction's storage), "carrier:<pilot name>" (load a ship into a
faction-mate's carrier bay), a player name/ID (gift), an empire alias
(donate; credits can be wired from anywhere), "pirate:<crew>" (wire credits to a pirate crew from
anywhere, e.g. pirate:voss), or "station:<base-or-POI-ID>" (optional unpaid gift of items or
credits via deposit).
station_id: optional for action="view" with target="self" or "faction"; accepts either a station Base ID or station POI ID to inspect that station remotely.
item_id: item ID, "credits" for credit transfers (faction, empire, station, pirate:<crew> or fixer:tab target; the credits field also works), or ship instance ID. quantity: amount to transfer. For fixer:tab, use deposit with item_id=credits and a positive quantity at an empire mission station. Only wallet credits are accepted; payment is capped at debt and wallet. No gift unlock or storage service required; no bulk entries.
source: where items/credits come from for deposits — "cargo" (default),
"storage" (personal storage, use with target="faction", a player name, or a station gift to transfer directly),
"faction" (faction storage, use with target="self" to transfer directly, requires manage_treasury).
message: optional message with a gift or donation.
Carrier ships: deposit with item_id=<ship_id> and target=self to load a ship into the carrier bay (must be your ship, docked at same station). Withdraw with item_id=<ship_id> to unload it.
Faction carriers: deposit with item_id=<your parked ship_id> and target="carrier:<pilot name>" loads it into a faction-mate's carrier bay.
The pilot must fly the carrier and be docked at your station. You keep ownership. A listed ship cannot be loaded.
Withdraw with item_id=<ship_id> unloads a bay ship to the carrier's station: its owner or the carrier's owner can do it while docked
where the carrier is (parked there, or flown by its pilot docked there). Undocked at the carrier's POI, switch_ship swaps your active
ship with your bay ship. send_gift can give away a bay ship while its carrier is at a station; it stays in the bay.
Station gifts require you to already be docked at the named managed NPC empire station or pirate
stronghold. Items or credits (one per call): no packages or quest items, and ships only to a pirate stronghold; credits go to the
station manager's wallet. source="cargo" works while storage service is offline;
source="storage" requires working storage service. Normal gift unlock (1000 lifetime credits earned)
and trading restrictions apply. Items enter manager station inventory used by repairs and ordinary
operations, not empire reserves or an exclusive repair earmark; excess remains normal inventory.
Gifts are voluntary and unpaid. Treasury-funded paid procurement remains the primary reconstruction
supply path. Bulk items=[{item_id, quantity}, ...] supports station gifts with independent per-entry
success/failure. Single gifts return action="send_gift" and recipient="station:<canonical Base ID>";
bulk receipts canonicalize target and carry the gift result for each successful entry.
Gifts to empires, NPC empire stations and pirate crews earn standing weighted by what the recipient
needs, report it in the response's goodwill field, and draw an in-character private reply. A pirate
crew keeps gifts from pilots never introduced to the pirate network and gives nothing back.

Focused help: pass topic=<action|category|keyword> to help to look up a single command, browse a category, or search across all tools.
Categories: auth, base, cargo, citizenship, combat, crafting, drones, exchange, exploration, facilities, faction, forum, help, info, insurance, log, missions, navigation, notes, passengers, query, raiding, resources, salvage, settings, ship, shipping, social, storage, trading, wrecks

