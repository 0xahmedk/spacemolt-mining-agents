# SpaceMolt MAS — Working Plan

Living document. Tick boxes as you go. `Gxx` = group number (not assigned yet).

---

## 0. Goal in one paragraph

Two fresh Nebula pilots (`AI26-Gxx-A`, `AI26-Gxx-B`) are run by **three independent agent services** —
Coordinator, Resource (mining) and Trading/Logistics — that talk over **A2A** and act in the game only
through **authenticated SpaceMolt MCP v2**. The Coordinator uses an LLM sparingly (≤300 calls total) to
pick missions; workers execute deterministic, validated action sequences, persist everything in SQLite,
and survive restarts without replaying sales. Target combined stats: **≥2,000 credits earned, ≥30 ore,
≥1 sale, ≥2 systems, ≤1,500 spent, ≤1,500 AU.**

---

## 1. Architecture (proposed)

```
                    ┌──────────────────────────────┐
                    │  Coordinator (process 1)     │
                    │  - observe → plan (LLM) →    │
                    │    delegate → verify         │
                    │  - owns mission table        │
                    └──────┬────────────────┬──────┘
                    A2A task│                │A2A task
                           ▼                ▼
          ┌──────────────────────┐  ┌──────────────────────────┐
          │ Resource agent (p.2) │  │ Trading/Logistics (p.3)  │
          │ skills: survey_belt, │  │ skills: scout_market,    │
          │ mine_until, return   │  │ sell_cargo, run_mission, │
          │ to_station           │  │ refuel, explore_system   │
          └──────────┬───────────┘  └────────────┬─────────────┘
                     │   shared lib: mas/mcp_gateway.py   │
                     └────────────► SpaceMolt MCP v2 ◄────┘
                                (per-pilot session_id)

        SQLite (state.db): missions, a2a_tasks, actions (idempotency keys),
        observations, pilot_leases, llm_usage   +   logs/events.jsonl
```

**Key design decision: roles ≠ pilots.** Each worker can drive *either* pilot. A pilot is "leased" to one
worker at a time (row lock in `pilot_leases`) so two agents never steer the same ship. This keeps both
pilots productive (each mines *and* sells its own ore — no inter-pilot transfers, which don't count anyway)
while still giving three substantive roles with real handoffs:
Coordinator → Resource: "Pilot A: mine 15 ore at belt X, cap fuel use Y" → result: cargo + game evidence →
Coordinator → Trading: "Pilot A: sell 15 iron_ore at station S, floor price P" → result: credits delta.

---

## 2. Phases and steps

### Phase 0 — Setup (Day 1, ~2 h) — *both*
- [x] Extract starter, `git init`, commit pristine starter.
- [x] Linux venv + deps; offline self-test passes; live MCP discovery returns 10 tools.
- [x] Fix `scripts/verify_local.py` to skip `.venv/` (currently crashes parsing site-packages).
- [ ] Get a free Groq key; run `python -m examples.groq_plan` once.
- [ ] Get group number + partner. **Do not register `AI26-Gxx` pilots before that.**
- [x] Register **one or two practice pilots** (`Prac-Ahmed1`) (any name) for development. Note: in MCP, registration is
      `spacemolt_auth register(username, empire)` + `claim(registration_code)`; password is returned once.
- [x] Linux credential storage (`mas/secrets_store.py`): `keyring` needs Secret Service (GNOME Keyring). Fallback: a git-ignored
      `.secrets/pilots.json` with `chmod 600`. Never log it.

### Phase 1 — Learn the game by hand through MCP (Day 1–2, ~3 h) — *both*
Goal: know the exact action names, params and response shapes before automating.
- [x] `mas/explore_cli.py`: tiny REPL — login practice pilot, call any `tool/action` with JSON args, pretty-print.
- [x] Call `help` on each tool and save output (`docs/mcp_help/`, summary in `docs/game_notes.md`).
- [ ] Record real responses for: `get_status`, system/POI listing, `travel`, `dock/undock`, `mine`,
      `view_market`, sell (instant sell vs `create_sell_order`), `refuel`, `jump`, missions list/accept/complete.
- [ ] Answer the open questions (§4) and write the answers in `docs/game_notes.md`.
- [ ] Read the guides: getting-started, miner, trader.

### Phase 2 — MCP gateway (Day 2, ~4 h) — *Member A owns*
`mas/mcp_gateway.py` — the only module that talks to the game.
- [x] Persistent `ClientSession` per pilot; `login` → keep `session_id`; auto re-login on expired session.
- [x] Load tool schemas at startup; **validate args against `input_schema`** before every call.
- [x] `query()` / `act(..., idempotency_key)` (ledger in `mas/store.py`):
  - checks `actions` table — if key already `confirmed`, return stored result (no replay);
  - writes row `pending` → calls MCP → writes `confirmed`/`failed` with sanitized args + server response;
  - timeouts + retry with backoff **only for read-only actions**; state-changing actions are never blind-retried —
    on ambiguity, re-observe state (`get_status`/cargo) and reconcile.
- [x] Event log on every call: time, agent, a2a_task_id, tool/action, sanitized args, outcome.
- [x] Unit tests with a fake MCP session (`python -m tests.run_all`).
- [x] Live read-only smoke test (`python -m mas.gateway_smoke --pilot Prac-Ahmed1`).

- Result: offline tests 18/18 pass; live smoke passes; MCP returns **no structuredContent** → text parsers stay.

### Phase 3 — Persistence layer (Day 2, ~2 h) — *Member B owns*
`mas/store.py` (SQLite, WAL mode, shared by all processes).
- [x] Tables: `missions`, `a2a_tasks`, `actions` (idempotency_key UNIQUE), `observations` (with `observed_at`),
      `pilot_leases` (pilot, holder, expires_at). One `Store` object per process gives access to all of them.
- [ ] LLM usage: keep the starter's `scripts/budget.py` (separate `logs/budget.sqlite3`); wire it in Phase 5.
- [ ] Assessed-run start/stop: keep the starter's `scripts/runtime.py`.
- [x] Leases: `acquire / renew / release / holder` with expiry (crashed worker's lease times out).
- [x] Observations: `record / latest / fresh(max_age)` — stale data returns None so agents must re-observe.
- [x] Mission state machine: `proposed → assigned → in_progress → verifying → done | failed | cancelled`
      (illegal transitions raise; retries are new missions with `parent_id`).
- [x] Offline tests: `tests/test_store.py` (run via `python -m tests.run_all`).

- Result: 24/24 offline tests pass (6 new store tests).

### Phase 4 — A2A worker services (Day 3, ~5 h) — *split: A = Resource, B = Trading*
Start from `examples/a2a_worker.py`; replace `acknowledged_only` with real execution.
- [ ] Task payload = JSON `{mission_id, pilot, skill, params, constraints, deadline}`; reject malformed input.
- [ ] Persist A2A task id ↔ mission id; emit `WORKING` updates; final artifact = JSON result with **game evidence**
      (before/after cargo, credits, server message).
- [ ] **Resource agent skills:** `survey` (POIs with resources in system), `mine(target_qty, max_ticks)`,
      `return_and_dock`. Safety: fuel ≥ reserve, cargo not full, hull ok.
- [ ] **Trading/Logistics skills:** `scout_market(items)`, `sell(item, qty, min_price)`, `refuel`,
      `explore(adjacent_system)` (for Systems Explored), `missions` (accept/complete supply missions if available).
- [ ] Restart safety: on start, scan `a2a_tasks` in `in_progress` for this role → reconcile with live game state
      → resume or mark failed. No action re-executed if its idempotency key is confirmed.
- [ ] Agent cards with real skill descriptions.

### Phase 5 — Coordinator (Day 3–4, ~5 h) — *Member A owns logic, B owns LLM prompt/budget*
`mas/coordinator.py` — loop: **observe → decide → delegate → verify → record**.
- [ ] Observe: fresh `get_status` for both pilots + latest market snapshot (reject if older than N min).
- [ ] Decide:
  - deterministic rules first (fuel low → refuel; cargo full → sell; both stats goals met → stop/idle);
  - LLM only for real choices: which belt/ore, sell now vs. other station, accept which mission, recovery
    after repeated failure. Compact JSON prompt (~1.5k tokens), JSON output, validated against a schema;
    invalid → deterministic fallback.
- [ ] Budget guard: ≤2 LLM req/min, ≤300 total, ≤250k tokens — target **≤120 calls / ≤120k tokens** for all
      assessed runs. Every call logged with rationale.
- [ ] Delegate via A2A client to the right worker; handle worker missing (card fetch fails) → mark, retry later,
      or reassign.
- [ ] Verify result against a new observation (credits/cargo actually changed) before marking `done`.
- [ ] Hard safety limits from config: max spend, max AU, no combat, no transfers between pilots.

### Phase 6 — Practice runs on practice pilots (Day 4–5) — *both*
- [ ] Full loop on practice pilot: mine → dock → sell → see credits rise.
- [ ] Failure drills: kill a worker mid-mine; kill coordinator mid-sell; expire session; give invalid params;
      stale market. Each must recover without double-selling. Save the logs as evidence.
- [ ] Measure: credits/hour, ore/hour, AU per cycle, LLM calls per cycle → project whether targets fit in 8 h.
- [ ] Tune strategy (which ore sells best, nearest station, missions vs. raw selling).

### Phase 7 — Baseline (Day 5, ~2 h) — *Member B owns*
- [ ] `baseline/single_agent.py`: one process, fixed rule loop (mine → sell → repeat), no LLM, no A2A.
- [ ] Run it on a practice pilot for a fixed window; compare against MAS on same window:
      credits/hour, ore, AU, errors recovered, LLM calls. Table goes into the report.

### Phase 8 — Assessed runs on real pilots (Day 5–7) — *both*
- [ ] Register `AI26-Gxx-A` and `AI26-Gxx-B` (Nebula) — **once**.
- [ ] `python -m scripts.runtime start` before each run, `stop` after. Stay under 8 h total.
- [ ] Early: one jump to an adjacent system per pilot (Systems Explored ≥2), keep total AU low.
- [ ] Check public profiles after each run; preview with `scripts.platform_score`.
- [ ] Stop once targets are hit — extra spending/travel can only hurt.

### Phase 9 — Deliverables (Day 6–7) — *split*
- [ ] README: exact commands (Windows **and** Linux), config example, safe key setup.
- [ ] Architecture diagram (agents, A2A tasks, MCP calls, memory).
- [ ] Report: strategy, real outcomes, baseline comparison, AI-assistant disclosure.
- [ ] Sanitized logs + LLM usage summary (`scripts/budget.py`).
- [ ] Public profile URLs + sale evidence.
- [ ] Demo rehearsal: start MAS → coordinator decision → A2A handoff → MCP call → game change →
      kill worker → restart → no duplicate. Each member explains every module.

---

## 3. Target layout

```
mas/
  config.py          # loads config.json + env; safety limits
  mcp_gateway.py     # MCP session, schema validation, idempotent calls
  store.py           # SQLite schema + helpers
  llm.py             # Groq wrapper using scripts/budget.py
  a2a_common.py      # task payload schema, client helper
  coordinator.py     # process 1
  resource_agent.py  # process 2 (A2A server)
  trading_agent.py   # process 3 (A2A server)
  explore_cli.py     # manual MCP REPL for learning (not used in assessed runs)
baseline/single_agent.py
tests/
docs/game_notes.md, docs/architecture.png, REPORT.md
```

## 4. Open questions to answer in Phase 1
1. Exact action names: system/POI listing, cargo view, instant sell vs. order book, missions.
2. Does selling ore to the station (NPC buy orders) count as *Trades Completed* or *Exchange Items Sold*?
3. Starting ship: has a mining laser? cargo capacity? fuel tank? starting credits?
4. Nebula home system: nearest asteroid belt and station, distances (AU).
5. Do supply missions exist near home and how much do they pay? (likely the fastest path to 2,000 credits)
6. Game tick length / action cooldowns → realistic actions per hour within 8 h.
7. How does `Systems Explored` count (does the home system count as 1 per pilot)?

## 5. Ownership split (for the individual defense)
| Area | Owner | Must also understand |
|---|---|---|
| MCP gateway, idempotency, coordinator loop, Resource agent | Member A | everything at a high level |
| Store/SQLite, LLM + budget, Trading agent, baseline | Member B | everything at a high level |
| README, report, diagram, demo script | both | — |

## 6. Rules we must not break
- Gameplay only via MCP. REST only for setup/cross-checks.
- No transfers between our pilots counted as income; no fake trades; no faction credit shifting.
- No secrets in logs, repo, report, or chats. `.env`, `.secrets/`, `*.sqlite*`, `logs/*.jsonl` stay git-ignored.
- Manual REPL is for learning on practice pilots only — never on assessed pilots during assessed runs.
