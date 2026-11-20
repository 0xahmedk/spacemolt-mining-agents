# SpaceMolt game notes (from live MCP v2 help, 2026-11-14)

Raw help for every tool: [docs/mcp_help/](mcp_help/). Regenerate with
`python -m mas.explore_cli -c dumphelp`.

Legend: ✅ confirmed from server help · 🔲 still to verify with a logged-in practice pilot.

## Protocol facts
- ✅ Endpoint `https://game.spacemolt.com/mcp/v2`, streamable HTTP; 10 tools.
- ✅ Auth is **not** an HTTP header: `spacemolt_auth login(username, password)` returns a `session_id`
  that is passed as an argument to every other tool.
- ✅ **Sessions expire after 30 min of inactivity or on server restart** → error code `session_invalid`.
  Recovery: call `login` again *without* the old session_id. The gateway must do this automatically.
- ✅ Missing session → `session_required`. Errors come back as `is_error=True` with text `Error: <code>: <message>`.
- ✅ Results are plain text (often tab-separated tables or JSON-ish text); `structured_content` was `None`
  for help/catalog. 🔲 check whether `get_status` returns JSON text (help says "single JSON blob").
- ✅ **Game tick = 10 s**; nearly every state-changing action is rate-limited to **1 per tick**.
  So ≤ 360 actions/hour/pilot; 8 h budget is not action-limited, it's travel/mining-time limited.
- ✅ `help` works without login (`session_id` can be any string); `get_guide` needs a real session.
- 🔲 Param names: help lists `travel(target_poi)`, `jump(target_system)`, `sell(item_id, quantity)`, but the
  MCP schema of `spacemolt` only has generic `id`, `quantity`, `text`. Tool description says `travel(id=...)`.
  Test which one the server accepts; the gateway will map our names → schema names.

## Registration
- ✅ `register(username, empire, registration_code)` → password (shown once, **no recovery**) + session_id.
- ✅ `claim(registration_code)` links an existing pilot to the website account.
- ✅ Usernames: 3–24 chars, letters/digits/space/`_-'.!`. `AI26-G01-A` is valid.
- ✅ Nebula = "exploration" empire.

## Core loop commands (`spacemolt` tool)
| Need | Action | Notes |
|---|---|---|
| Full state | `get_status` | player, ship, modules, cargo, location, missions, skills |
| Where am I | `get_location`, `get_poi`, `get_system` | POI resources, station services, connections |
| Map / routing | `get_map`, `find_route`, `search_systems` | for Systems Explored with minimal AU |
| Move in system | `undock` → `travel` → `dock` | travel ≤4 AU charged real; longer charged `sqrt(4×AU)` |
| Change system | `jump` | time = 7 − speed ticks; fuel ∝ mass × speed |
| Mine | `mine` | needs mining laser for ore; yield = power × richness × skill; deposit can be `deposit_too_sparse` |
| Survey ore | `survey_system` | needs a survey scanner module 🔲 does starter ship have one? |
| Sell now | `sell(item_id, quantity)` | instant fill vs. existing buy orders, **no fee**, must be docked |
| Buy now | `buy(item_id, quantity)` | sales tax may apply |
| Fuel | `refuel` (docked, no target) | fills tank, costs credits → counts as Credits Spent |
| Missions | `get_missions` (docked) → `accept_mission` → `complete_mission` | max 5 active; rewards credits + XP |
| Events | `get_notifications` | trade fills, mission updates |
| Cargo | `get_cargo`, `get_ship` | |

## Market (`spacemolt_market` tool)
- ✅ `view_market` (docked): best bid/ask per item; `item_id` for depth; `since=current_tick` incremental.
- ✅ `create_sell_order` (1% fee, escrowed), `create_buy_order`, `view_orders`, `cancel_order`, `analyze_market`.
- 💡 Strategy: prefer instant `sell` when a buy order exists at an acceptable price (no fee, immediate,
  easy to verify); fall back to `create_sell_order` only if no bids.

## Starter ships (catalog search "starter")
All T0 Industrial **Miners**: Cobble (75 cargo), Prospect (100), Shard (60), Theoria (70), Threshold (65).
🔲 Which one Nebula gets and whether it ships with a mining laser + survey scanner.

## Open questions → answers
| # | Question | Status |
|---|---|---|
| 1 | Action names for system/POI/cargo/sell/missions | ✅ table above; params use generic `id` |
| 2 | Does `sell` to station buy orders count as *Trades Completed* or *Exchange Items Sold*? | 🔲 check profile after first sale |
| 3 | Starting ship modules, cargo, fuel, credits | ✅ see "Practice pilot findings" |
| 4 | Nebula home system: nearest belt + station, distances | ✅ Haven; belt in same system (AU distance 🔲) |
| 5 | Supply missions near home + payouts | ✅ yes, see below — main income source |
| 6 | Tick / cooldown | ✅ 10 s tick, 1 action per tick |
| 7 | How Systems Explored counts | 🔲 compare profile before/after first `jump` |
| 8 | Do mission rewards count as *Credits Earned* on the profile? | 🔲 check profile after first mission |
| 9 | Jump distances are shown in GU; profile counts AU. Conversion? | 🔲 check profile after first jump |
| 10 | Must a mining mission be accepted *before* mining for ore to count? | 🔲 accept first, then mine |

## Practice pilot findings (Prac-Ahmed1, 2026-11-14)
- **Start:** 250 cr, docked at **Grand Exchange Station** in **Haven** (Nebula capital, max security).
- **Ship:** Prospect — cargo 110, fuel 130/130, speed 1, hull 95, shield 50.
  Modules: `mining_laser_i` (mine:5, utility), `pulse_laser_i` (weapon). **No survey scanner** →
  `survey_system` not available; use `get_poi` at a belt to see its resources.
- **Station services:** crafting, market, medical, missions, personnel, refuel, repair, shipyard, storage.
  Fuel 16 cr/unit (11 + 5 tax) → refuelling counts toward Credits Spent; keep it minimal.
- **Haven POIs:** grand_exchange (station), **commerce_fields (asteroid_belt, metallic)**, trade_winds (gas cloud),
  frostmarket_flats (ice field), haven_star, haven_prime, founders_wreck.
  → mining loop needs **no jump**: undock → travel commerce_fields → mine × N → travel grand_exchange → dock.
- **Connections:** market_prime (407 GU), traders_rest (514 GU).
- `get_cargo` while docked showed "Capacity: 0/0" although status shows 0/110 — trust `get_status`.
- Output is human-readable text, not JSON. The gateway needs small parsers (e.g. `NNNcr`, `Cargo: a/b`).
- Another class pilot (`AI26-G34-B`) is at the same station — expect competition for the same belt.

### Phase 1b findings (2026-11-20)
- ✅ **Param names:** the generic `id` works — `accept_mission {"id":"first_cargo"}`, `travel {"id":"commerce_fields"}`.
  (Help's `mission_id` / `target_poi` names are aliases in the help text only.)
- ✅ `accept_mission` reply: `"... Template: first_cargo. Expires: 2026-11-23T06:15:58Z."` (3-day expiry).
- ✅ `undock` → `"Undocked from station."`; `travel` → `"Arrived at Commerce Fields (commerce_fields). N other players here."`
  Travel grand_exchange → commerce_fields took < 40 s.
- ✅ **Mining yields 1 unit per `mine` (1 per tick)**, random deposit weighted by richness:
  `"Mined 1 Iron Ore.\nDeposit: 5 units (100% depleted)\nXP: mining +1, piloting +1"`.
- ⚠️ **Commerce Fields is heavily contested and nearly empty** (other class pilots there, e.g. AI26-G07-B6).
  `get_poi` resources table: Iron 8 left, Copper 8, Nickel 1, Silicon 1, Trade Crystal 48. Iron went
  "depleted" → "5 units" between ticks → deposits **regenerate** slowly (rate unknown).
  → we cannot rely on 15–30 copper here; the agent must read `remaining` and pick another belt/system.
- ✅ `get_poi` at a belt has a parseable table: `resource, richness, remaining, supports_power, workable`.
- ✅ **Not every action uses `id`:** `get_map {"id":…}` → `invalid_payload: Unknown parameter(s): id. Valid
  parameters: system_id.` The published schema doesn't list `system_id`, so confirmed exceptions live in
  `mas/action_params.py`. `invalid_payload` = server rejected it = nothing happened.
- ✅ **Undocked `get_status`** has no `Docked at:` line and no POI id; it adds the current POI's
  `Resources (N):` table, a `Cargo (N items):` table (`item, qty, size`), skills and `Active missions (a/5)`.
- ✅ Travel Grand Exchange → Commerce Fields cost **1 fuel** (130 → 129).
- ✅ Ten minutes later Commerce Fields showed Iron/Copper/Nickel/Silicon **all 0**, Trade Crystal 29.
- ✅ **Mission ids:** `get_missions` shows the *template* id (`first_cargo`); after accepting,
  `get_active_missions` shows an *instance* id (`42d92dacb5f7c9d08ce8915aff151842`) and progress
  `Mine 15 units of Copper Ore: 0/15`. Mining other ores does not count. 🔲 which id `complete_mission` wants.
- ✅ `dock` away from a station → `Error: no_base: No station at this location`.

### Public profile after Phase 1b (Prac-Ahmed1, 2026-11-20)
Service Record counters: Credits Earned 0, **Ore Mined 4**, Trades Completed 0, Exchange Earnings 0,
Missions Completed 0, **Systems Explored 1** (home system counts!), Jumps 0, **Distance Traveled 4**
(two in-system trips; unit presumably AU), Times Docked 1.
- ✅ Q7 answered: home system already counts → **two pilots = 2 systems = full 3 marks with zero jumps.**
  Jumping is only worth it if a neighbouring belt is better.
- Profile shows **Exchange Earnings**, not "Exchange Items Sold" — that is the counter to watch after a sale.
- `create_sell_order` (2 iron @ 4 cr) → `fee: 1cr` (counts as spending), order id returned; fills later.

### Galaxy map (get_map, no args)
506 systems. `get_map {"system_id":…}` returns "No systems" for unvisited systems — POIs are unknown until
visited. Nebula space around Haven: haven → **market_prime** (5 POIs) → cargo_lanes (6) / **gold_run** (9;
"Gold Run Extraction Hub" — likely mining) ; haven → **traders_rest** (5) → factory_belt (4) / khambalia (7).
Jump distance Haven→market_prime is 407 GU; 🔲 how many AU/fuel a jump costs (use `find_route`).

### Docs MCP server — authoritative contracts (queried 2026-11-20, server v0.728.0)
`https://game.spacemolt.com/mcp/docs` (read-only). Saved contracts + guides: [api_contracts/](api_contracts/).
- **Exact params** (MCP: `tools/call spacemolt {action, session_id, ...}`):
  `travel {id: poi_or_base}` · `jump {id: system}` · `mine {}` · `dock {}` · `undock {}` ·
  `sell {id: item, quantity, auto_list?}` · `refuel {}` (docked: fills tank) · `find_route {id}` ·
  `get_map {system_id?}` · `accept_mission {id | template_id}` · **`complete_mission {id: mission UUID}`**
  (the instance id from get_active_missions, not the template) ·
  `spacemolt_market create_sell_order {item_id, quantity, price_each}` / `cancel_order {order_id}` /
  `view_market {category?, item_id?, base_id?}`.
- **Replies:** every response is `V2Response {result, structuredContent, notifications, session, error}`.
  `structuredContent` is typed JSON (`V2GameState`; mutations return a delta + `details`, e.g. mine →
  `{kind:"yield", resource_id, quantity, remaining, ...}`). 🔲 check MCP actually delivers it
  (`gateway_smoke` now prints it). If yes, parse JSON and keep text parsers only as fallback.
- **Rate limits:** only mutations are 1 per tick (10 s); queries are not tick-limited.
- Commands **auto-dock / auto-undock** when needed (`details.auto_docked`, `auto_undocked`).
- Mining "too sparse": refused only if deposit < 25% capacity AND power > 4× what it supports.
  Our Mining Laser I (power 5) can never lock (P×F ≤ 20) → **never hits too_sparse**, mines to zero.
- Yield selection at Mining skill 0 = plain richness weighting.

### Strategy implications (from miner + mission-runner guides and the boards)
- Guides: "Accept missions first — 10x more than selling ore". Supply runs pay 1,500–3,500 cr.
- **Market participation missions** at Grand Exchange pay **1,000 cr each** per pilot:
  - `market_participation_buying`: buy 10 units of anything via a buy order that fills
    (copper ask is 4 cr → ~40–50 cr spent → 1,000 cr earned; also a real exchange trade).
  - `market_participation_selling`: sell 10 units via `create_sell_order` that fills — price at/under an
    existing bid (e.g. silicon bid 10 cr, mined in Commerce Fields) so it fills at once.
- Draft per-pilot plan (both pilots, no jumps, tiny AU, low spend):
  1. accept buying + selling + one mining supply mission (copper/iron);
  2. buy 10 cheap units (fills buying mission);
  3. mine at Commerce Fields (wait for regen / choose richest deposit), sell ≥10 of an ore that has bids;
  4. complete missions. Expected ≈ 1,000 + 1,000 + 1,000–1,800 per pilot ⇒ well over 2,000 combined.
- Coordinator's LLM role: choose which mission/ore given live deposits, bids and progress; re-plan when the
  belt is empty (wait vs. other POI vs. jump to market_prime/gold_run).

### Market at Grand Exchange (view_market category=ore, 2026-11-20)
Columns: `best_sell` = cheapest ask (what we'd pay to buy), `best_buy` = highest bid (what instant `sell` gets us).
**Instant `sell` only works where `best_buy` exists.** Useful bids for ores we might mine:
| item | best bid | notes |
|---|---|---|
| titanium_ore | **231 cr** (58,770 wanted) | + titanium mission 3,500 cr → find a titanium belt |
| silicon_ore | 10 cr | in Commerce Fields (tiny stock) — cheap guaranteed instant sale |
| silver_ore | 10 cr | |
| uranium_ore | 600 cr | radioactive — mining laser can't? (guns can't; laser unclear) |
| copper_ore / iron_ore / nickel_ore / trade_crystal | **no bids** | only via `create_sell_order` (needs a buyer to fill) or missions |
So for copper/iron the money comes from **missions**, not the market.

### Missions at Grand Exchange (best fits for our targets)
| Mission id | Type | Objective | Reward |
|---|---|---|---|
| `first_cargo` | mining d1 | mine 15 copper ore | 1,000 cr (chain → scouting_the_lanes) |
| `copper_requisition` | mining d1 | mine 25 copper ore | 1,800 cr |
| `iron_supply_run` | mining d1 | mine 30 iron ore | 1,500 cr |
| `titanium_extraction_contract` | mining d3 | mine 20 titanium ore | 3,500 cr |
| `market_participation_selling` | trading d1 | sell 10 units via `create_sell_order` (must fill) | 1,000 cr — **also gives the exchange sale** |
| `local_sector_survey` | exploration d2 | visit sirius, node_alpha, horizon | 2,500 cr (too much travel for the AU cap?) |

**Avoid** (safety rules for the coordinator): all `smuggling_*` / "Off the Books" / "Black Market" missions
(fixer debt, customs), long trade runs (buy first → Credits Spent, 7–13 jumps → AU), combat/hunt missions,
the 5-empire tour and other multi-system exploration missions.

**Draft strategy (both pilots combined):** each pilot does one or two mining missions in Commerce Fields
(e.g. A: first_cargo + copper_requisition = 40 copper, 2,800 cr; B: iron_supply_run = 30 iron, 1,500 cr)
→ ≫30 ore and ≫2,000 cr earned. Sell surplus ore with `create_sell_order` (market_participation_selling)
for the trade/exchange counter. One short jump per pilot for Systems Explored if needed.
Depends on: which ores Commerce Fields actually has, and open questions 8–10.

## Things the gateway must handle (feeds Phase 2)
- `session_invalid` → re-login, then retry **only if the action is read-only or verified not applied**.
- Rate limit / `retry_after` → wait one tick (10 s).
- `deposit_too_sparse` → tell coordinator; choose another POI.
- Docked/undocked preconditions (`sell`, `buy`, `get_missions`, `refuel` need docked; `travel`, `mine` need undocked).
