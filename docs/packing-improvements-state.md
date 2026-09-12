# Packing improvements — work state

Updated: 2026-09-13. Repository instructions: root `AGENTS.md`.

## Requested outcome

1. Calculation progress bar and elapsed time, including completed result.
2. Z3 time budget includes the initial heuristic and model preparation.
3. Parallelize algorithm 1 across independent strategies (up to 12 useful workers;
   user has 24 logical CPUs), with cancellation and deterministic ranking.
4. Preserve maximum packed item count and volume, then maximize overall fill
   (minimize total carton volume before carton count).
5. Repack each Z3-selected carton neatly, preserving its assigned items and full support.
6. Use background jobs for every server calculation to remove the 120-second
   calculation HTTP timeout.
7. Explain alternatives and sort plans/cartons by fill descending.

## Findings

- `z3_engine.py` starts the deadline after an unbounded baseline heuristic.
- `packing.ts` uses jobs only for >1000 items or a Z3 budget >60 seconds.
- Both engines rank carton count before total carton volume.
- Z3 has no layout compactness objective and discards alternatives.
- Job status exposes elapsed time but no progress; completed plans omit duration.

## Plan / current status

- [done] Backend: shared search control/progress, fill ranking, bounded Z3,
  carton repacking, parallel heuristic, duration and background progress.
- [done] Frontend: always use jobs, progress UI, duration, settings/help, sorting.
- [done] Focused regressions, broader backend/frontend suites and build,
  browser checks/screenshots where available.
- [done] Document behavior, measured validation and limitations here.

No subagents used. No deployment or commits requested.

## Final validation

- Full backend: **380 passed, 1 stress skipped** (`uv run --frozen pytest -q`).
  Geometry, full support, deadline, parallel cancellation, fill ranking, sorted
  instructions and duration regressions are covered. Legacy deterministic-plan
  comparisons now independently validate the varying calculation time.
- Frontend: **93 passed, 1 skipped** (`npm test`); `npm run build` passed.
- `ruff check app tests`: passed. `git diff --check`: passed.
- New browser scenarios: **2 passed**. One uses the real API and Z3 (17 items,
  3-second budget, two processes); verifies budget progress, complete accounting,
  elapsed time and descending carton fill. Other verifies job transport, process
  settings, alternatives help and ordering with controlled responses.
- Existing browser suite: 12 passed / 3 failed. Existing live API suite:
  5 passed / 6 failed. Seven failures require WebGL unavailable in Alpine Chromium;
  the app correctly uses its existing layer view. Two legacy tests expect the
  issue section that was already commented out in PackingResultView before this
  task. API/status/instruction assertions before the WebGL checks passed. These
  unrelated product sections were not changed to satisfy outdated assertions.
- Screenshots of the real API calculation are in
  `docs/screenshots/calculation-progress.png` and `calculation-result.png`.
- Moderate benchmark on this machine (24 available logical CPUs): 200 items,
  first 20 SKU of the deterministic workload, quantity 10, all 8 box types.
  1 worker: **5.706 s**, 4: **2.857 s**, 12: **2.192 s**. All packed 200/200,
  24 cartons, **49.9375%** fill. Approx. 2.6x speedup at 12 workers in this sample.

## Environment and review

- Host has no Node/uv. Docker access approved. Use local Node 24 image via
  `/tmp/duncarbox-test-compose.yml` override (repo remains on its existing config).
- Local dev stack is running: frontend `http://127.0.0.1:5173`, API `:8000`,
  PostgreSQL `:5432`. Tests used isolated DB schemas. Dependency
  downloads initially failed, succeeded on retry. Production untouched.
- Chromium and Mesa were installed only in the temporary dev container.
- No dependency lock changes, DB migration, production deployment or commit.
- Active behavior docs updated: README, CONTRACTS, PACKING_ENGINE, Z3_ENGINE, UX.

## Practical limits

- Item count and packed product volume remain ahead of fill, so the algorithm
  does not discard products merely to produce a high percentage.
- Z3 progress is budget consumption, never a claimed percentage of proof.
- The deadline now includes the baseline and model startup/search. Validation,
  instructions, process cleanup and response transfer can add overhead.
- Repacking preserves assigned items and full support; if a greedy trial fails
  or time expires, the valid previous layout is retained and translated as a whole.
- Algorithm 1 has 12 strategies, hence up to 12 useful processes; small orders
  (<100 items) stay serial. Performance depends on the order.
