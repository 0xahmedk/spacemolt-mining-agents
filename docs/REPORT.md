# Report: SpaceMolt Autonomous Enterprise (Group AI26-G100)

## 1. Team and pilots
| Member | Reg. no. | Owns (modules) | Pilot | Profile URL |
|---|---|---|---|---|
| Ahmed Khan | 25i-7633 | MCP gateway, coordinator, resource agent | AI26-G100-A | https://spacemolt.com/player/AI26-G100-A |
| Ejaz ul Haq | 25i-7624 | store, LLM/budget, trading agent, baseline | AI26-G100-B | https://spacemolt.com/player/AI26-G100-B |

Both pilots were registered on 2026-11-20 in the Nebula empire and start at Haven / Grand Exchange.
`G100` was used because no group number had been assigned when the pilots had to be created.

## 2. Strategy (why these actions)
- **Missions over raw ore.** The Grand Exchange board offers supply runs paying 1,000–3,500 cr. The game's
  miner guide says missions pay about 10× what ore sales do, and copper/iron have no bids at Grand Exchange.
- **One home belt.** Mining happens at Commerce Fields in Haven: no jumps, so tiny AU and fuel use. The home
  system already counts for *Systems Explored* (1 per pilot, 2 combined).
- **Low-risk sales.** Sales go only into existing bids, or through `create_sell_order` for the
  `market_participation_selling` mission (1,000 cr), which also gives the exchange sale.
- **Low spending.** Per-pilot and per-task spend caps are in `config/mission.json` (700 and 120 cr).
- **Contested belt.** The coordinator reads the remaining deposits and waits or switches mission when ore
  runs out.
- **How a decision is made.** The coordinator builds a menu of already-validated options. The LLM picks one
  option id and gives a rationale. Forced safety rules are applied first, and if the LLM is unavailable or
  answers invalidly, a cached plan or a deterministic heuristic is used instead.

## 3. Architecture
See the diagram and module table in [README.md](../README.md). The three roles run as three processes:
- **coordinator/planner** (`mas.coordinator`);
- **resource agent** (`mas.worker --role resource`);
- **trading/logistics agent** (`mas.worker --role trading`).

Tasks travel between them over A2A (a2a-sdk 1.3, JSON task bodies). Game actions go over authenticated
SpaceMolt MCP v2 through `mas.mcp_gateway`, which validates parameters, re-logs in on expired sessions and
applies an idempotency ledger. Shared memory is SQLite (`logs/state.sqlite3`) and holds:
- missions, A2A tasks, the action ledger, pilot leases and observations.

## 4. Real outcomes (assessed runs)
| Run | Start–end (UTC) | Minutes | Credits earned | Ore (A / B) | Sales | Spent | LLM calls / tokens |
|---|---|---|---|---|---|---|---|
| MAS #1 | 2026-11-20 15:52:55 – 16:05:31 | 12.6 (runtime ledger 13.34) | 0 | 25 (22 / 3) | 0 | 0 | 7 / 4,674 |

What happened in run #1 (from `logs/events.jsonl` and `logs/state.sqlite3`):
- **Decisions.** The LLM made 7 decisions and rules made 3. Every decision is logged with its option menu
  and rationale (`coordinator.decision`).
- **Missions accepted.** A accepted *Copper Requisition* (25 copper, 1,800 cr) and B accepted
  *Titanium Extraction Contract* (20 titanium, 3,500 cr). Both were verified against the game's active
  missions.
- **Mining.** 25 units were mined. Each mine action was confirmed in the action ledger by the cargo
  increasing.
- **No credits yet.** Neither mission was finished inside the 6 rounds.

Public profile counters at submission (fill from the two profile pages):
| Counter | A | B | Combined |
|---|---|---|---|
| Credits Earned | | | |
| Credits Spent | | | |
| Ore Mined | | | |
| Trades Completed / Exchange | | | |
| Distance Traveled (AU) | | | |
| Systems Explored | | | |

## 5. Baseline comparison
`baseline/single_agent.py` is a single process with no A2A and no LLM. It runs a fixed script that reuses
the same executors. Because time ran out, it has **not** been run on the assessed pilots yet. When it is, run it with
`python -m baseline.single_agent --pilot <pilot> --minutes 20` and compare with
`python -m mas.report --compare`. The comparison below is therefore qualitative, by design.

| | Baseline (fixed script, by design) | MAS run #1 (observed) |
|---|---|---|
| Who decides | hard-coded order | LLM picks among validated options; rules as guard and fallback |
| Mission choice | fixed | adaptive (it avoided a recently failed option and switched to an active mission's ore) |
| Recovery | none (crash ends the run) | A2A task resend with the same id, ledger prevents replay, lease takeover |
| LLM cost | 0 | 7 calls / 4,674 tokens |

**Limitation:** the two runs used the same contested belt at different times and on different pilots,
so their outcomes are not directly comparable.

## 6. Reliability evidence
Offline tests (`python -m tests.run_all`, all passing) cover:
- duplicate `act()` skipped (no double sale);
- expired session (`session_invalid` / `not_authenticated`) recovered by re-login;
- rate-limit wait;
- an ambiguous timeout recorded as `unknown`, then re-observed and resolved without replay;
- a restarted process not replaying completed actions;
- A2A worker restart and lost-reply adoption;
- the coordinator's invalid-LLM-answer fallback;
- no secrets in the logs.

Live findings handled:
- the server sends `not_authenticated` after 30 minutes idle, which is now treated as an expired session;
- `get_map` rejects `id`, which is caught by local validation before the call is sent.

## 7. LLM usage and budget
| Ledger | Requests | Tokens |
|---|---|---|
| Assessed (`logs/budget.sqlite3`) | 7 | 4,674 (input 3,918, output 756) |
| Development (`logs/budget.dev.sqlite3`) | 1 | 199 |

Model: `openai/gpt-oss-20b` on Groq. The budget is 300 requests and 250,000 tokens, and the per-minute
limit of 2 requests is enforced by `scripts.budget`. Assessed runtime is 13.34 of 480 minutes
(`python -m scripts.runtime status`).

## 8. Known issues found in run #1 and next steps
1. **Server errors not retried.** `mcp 2.3.0` renamed `McpError` to `MCPError`, so the gateway's retry
   list (`mas/mcp_gateway.py`, `_transport_errors`) silently missed server errors (JSON-RPC -32603).
   A one-minute burst of them failed four observations and two decisions instead of being retried.
   Fix: import `MCPError`, falling back to the old name.
2. **Mining stops too early.** The mine skill stops on the game error `depleted` even when other deposits
   in the belt still have ore. It should skip that tick instead and stop only when every deposit reads 0.
3. **Missions with no reachable ore.** *Titanium Extraction Contract* was offered even though
   Commerce Fields has no titanium. Accept options should be filtered to ores present in a known belt.
4. **Stale worker process.** The trading worker had been started before the `view_market` `category`
   fix, so market observations failed the local validator. Workers must be restarted after each update.
5. **Text parsing.** MCP returns no `structuredContent`, so all replies are parsed from text
   (`mas/parsers.py`).
6. **Credits still to come.** Next runs should finish the accepted missions and the two
   market-participation missions (1,000 cr each per pilot) to reach 2,000 cr earned and an exchange sale.
