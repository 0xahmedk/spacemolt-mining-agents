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
- [x] Task protocol `mas/a2a_protocol.py`: JSON `{task_id, mission_id, skill, pilot, params, constraints,
      issued_by, rationale}` → JSON `TaskResult {status, summary, data, evidence, error}`; malformed → rejected.
- [x] Worker framework `mas/worker.py`: validate → task-level dedupe → pilot lease → skill → store result →
      A2A artifact. `WORKING` progress updates. Startup recovery marks orphaned tasks `unknown`.
- [x] Duplicate protection: goods/money actions use `<task_id>:<step>` ledger keys (+ checkpoint/verify to
      reconcile lost replies); navigation converges on observed state.
- [x] **Resource skills** (`mas/resource_skills.py`): status, survey, go_to, return_to_station,
      mine (stops: target_reached / max_cycles / cargo_full / belt_depleted / game_error).
- [x] **Trading skills** (`mas/trading_skills.py`): status, market, sell (min_price), list_sell_order,
      buy_order (max_spend required), missions_board, active_missions, accept_mission (refuses smuggling/combat),
      complete_mission, refuel (max_spend). Exploration jumps dropped: home system already counts as explored.
- [x] Coordinator-side client `mas/a2a_client.py` (non-blocking send + poll) and manual `mas/send_task.py`.
- [x] Agent cards list the real skills. Offline tests `tests/test_workers.py` (fake world + A2A over ASGI).
- [x] Live test with practice pilot: status / mine / return_to_station over A2A (crash drill moved to Phase 6).


### Phase 5 — Coordinator (Day 3–4, ~5 h) — *Member A owns logic, B owns LLM prompt/budget*
`mas/coordinator.py` — loop per pilot: **observe → options → decide → delegate → verify**.
- [~] Observe: fresh observations from the shared store; stale → delegate a read task (status / active_missions /
      missions_board / market). Mission progress is always re-read after acting (no stale plans).
- [~] Options: deterministic, validated menu (complete finished mission, mine for a mission, accept feasible safe
      mission, buy/sell order a market mission needs, sell into a bid, generic mining, wait, return). Spend caps,
      unsafe missions and options that failed twice are filtered out before the LLM sees them.
- [~] Decide: forced rules (claim finished mission, refuel when low) → LLM picks ONE option id + rationale
      (`mas/llm.py`, JSON) → reuse the last LLM plan while the menu is unchanged → heuristic fallback.
- [~] Budget: starter ledger `scripts/budget.py` (300 req / 250k tok / 2 per min, waits out the minute window),
      per-run cap `llm.max_calls_per_run`. Every call logged (purpose, tokens, response).
- [~] Delegate over A2A (`A2ADispatcher`); worker unreachable → task `unknown`, retried via recovery.
- [~] Verify worker evidence before closing a mission (credits/cargo deltas, order ids, docked state).
- [~] Restart: resend unfinished tasks with the same id; adopt stored results of finished-but-unreported tasks.
- [~] Config `config/mission.example.json` (targets, limits). Offline tests `tests/test_coordinator.py`.
- [ ] Live run with the practice pilot.

`[~]` = code written, waiting for your test run.

### Phase 6+7 — Practice, drills, baseline, deliverables (everything that does NOT need the real pilots)
Minimal version, built together because time is short. Run on the practice pilot.
- [~] Failure-drill runbook [docs/DRILLS.md](docs/DRILLS.md): smoke run, kill worker, kill coordinator,
      missing worker, invalid params, session expiry, stale observations.
- [~] Baseline `baseline/single_agent.py`: one process, no A2A, no LLM, fixed script, same skills.
- [~] Comparison/summary tool `mas/report.py` (Markdown table from store + events + LLM ledger).
- [~] `README.md` with architecture diagram, module table, Linux + Windows commands, secret handling.
- [~] Report skeleton [docs/REPORT.md](docs/REPORT.md).
- [ ] YOU: offline tests; Phase 5 live smoke run; drills 1–4; one MAS vs baseline comparison (~20 min each).

`[~]` = code written, waiting for your test run.

### Phase 8 — Real pilots (needs group number) — *both*
> Pilots registered 2026-11-20 as **AI26-G100-A** and **AI26-G100-B** (nebula; passwords in keyring). Config: `config/mission.assessed.example.json`. Two-pilot rehearsal on practice pilots: `config/mission.rehearsal.example.json`.
1. [ ] Group number + partner confirmed. Check the dashboard for a pilots-per-account limit.
2. [ ] Archive dev LLM usage so assessed runs start from zero:
       `mv logs/budget.sqlite3 logs/budget.dev.sqlite3` (also keep `logs/events.jsonl` → `logs/events.dev.jsonl`).
3. [x] Register `AI26-Gxx-A` and `AI26-Gxx-B` (nebula) with `python -m mas.explore_cli` → `register …` — once each.
       No manual gameplay on them afterwards.
4. [ ] `config/mission.json`: `"pilots": ["AI26-Gxx-A", "AI26-Gxx-B"]`; targets per pilot 1000 cr / 15 ore / 1 sale.
5. [x] `python -m mas.gateway_smoke --pilot AI26-Gxx-A` (and B) — read-only.
6. [ ] `python -m scripts.runtime start` → workers + coordinator → `python -m scripts.runtime stop`. Repeat until
       the combined profile counters reach the targets; stop early (extra spend/travel only hurts).
7. [ ] Check both public profiles; `python -m scripts.platform_score …` with the combined numbers.
8. [ ] Fill docs/REPORT.md (outcomes, comparison, drills, budget), export `mas.report` tables, zip the submission
       (source, requirements, README, report, sanitized logs, budget summary, profile URLs).
9. [ ] Demo rehearsal: live profiles → start MAS → decision + A2A handoff + MCP call + game change →
       kill a worker → restart → no duplicate. Each member explains their modules.

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
