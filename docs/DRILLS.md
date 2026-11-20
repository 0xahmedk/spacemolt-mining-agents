# Practice runs and failure drills (Phase 6, practice pilot only)

Run everything from the project folder with `.venv` active. Use the **practice pilot**
(`Prac-Ahmed1`), never the `AI26-…` pilots. Keep each terminal's output: it is evidence for
the report and a rehearsal for the TA demo (step 3 of the TA checklist: "force a controlled failure").

Terminals:
- **T1** resource worker: `python -m mas.worker --role resource --port 9101`
- **T2** trading worker: `python -m mas.worker --role trading --port 9102`
- **T3** coordinator / tools

## 0. Smoke run (≈15 min)
```bash
python -m mas.coordinator --config config/mission.json --rounds 6
```
Look for: `coordinator.decision` events with `decided_by` + rationale, tasks moving through T1/T2,
the final tally, and the `mas.report` command it prints at the end. Run that command.

## Drill 1: kill a worker mid-task (the TA's favourite)
1. Start the coordinator (no `--rounds`) and wait until T1 is mining (`mcp.call` lines every ~11 s).
2. Press **Ctrl+C in T1**. Expect in T3: `worker.unavailable`; the task becomes `unknown`.
3. Restart T1. Expect `recovered 1 unfinished task(s): [...]`.
4. Within one round, T3 shows `coordinator.resend` with the **same task id**; T1 continues.
   Mining cycles already confirmed are replayed from the ledger (`mcp.duplicate_skipped`), not repeated.
5. Proof of no duplicates: `sqlite3 logs/state.sqlite3 "select idempotency_key,status from actions order by created_at desc limit 15"` — each key appears once.

## Drill 2: kill the coordinator mid-task
1. While T1 is mining, press **Ctrl+C in T3**. The worker keeps going and finishes the task.
2. Restart the coordinator. Expect `coordinator.adopt_result` (the finished task's stored result is
   used to close the mission) or `coordinator.resend` → worker answers `task_in_progress` until done.
   Nothing is executed twice.

## Drill 3: missing worker at start
1. Stop T2, start the coordinator. Expect `worker.unavailable` for trading tasks, no crash, retries
   every `idle_seconds`. 2. Start T2 again; the coordinator carries on.

## Drill 4: invalid parameters (rejected before reaching the game)
```bash
python -m mas.send_task --url http://127.0.0.1:9102 --pilot Prac-Ahmed1 --skill buy_order --params '{"item_id":"copper_ore","quantity":10,"price_each":4}'
```
Expect `failed` with `bad_params` (no `max_spend`): the safety rule, not the server, refused it.
```bash
python -m mas.send_task --url http://127.0.0.1:9101 --pilot Prac-Ahmed1 --skill mine --constraints '{"max_cycles":500}'
```
Expect `failed`, `bad_params` (max_cycles must be 1..200).

## Drill 5: expired session
Sessions expire after 30 min idle. Leave the workers idle for 30+ min, then send any task:
the worker log shows `mcp.relogin` and the task succeeds. (Also covered by the offline tests.)

## Drill 6: stale observations
Every decision uses observations younger than `freshness_seconds`; mission progress is re-read
after each action. Show it in the log: after each `mission.verified`, the next round starts with
an `active_missions` task before the next `coordinator.decision`.

## Baseline comparison (Phase 7, ≈2 × 20 min)
Run the MAS and the baseline for the same length of time, one after the other, same pilot:
```bash
python -m mas.coordinator --config config/mission.json        # stop with Ctrl+C after ~20 min
python -m baseline.single_agent --pilot Prac-Ahmed1 --minutes 20
```
Each prints START/END epoch seconds. Then:
```bash
python -m mas.report --pilot Prac-Ahmed1 --compare MAS:<start>:<end> BASE:<start>:<end> --out docs/results/baseline_comparison.md
```
Note in the report that both runs share one belt and one board, so conditions differ between
the two windows (deposits regenerate, other players mine) — a limitation, not a hidden bias.
