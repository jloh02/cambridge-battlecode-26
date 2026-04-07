# got-any-grapes scratchpad

## Promotion ladder

Each meaningful feature follows this sequence:

1. implement the feature
2. run unit or scenario tests for that feature
3. run a 16-game smoke set against `jon-6-a9bfs-surround`
4. require at least 60% win rate in the smoke set
5. if the smoke passes, create a preliminary draft commit
6. do not run 64-game tournaments yet
7. move to the next feature

After all trusted-feature work is complete:

1. selectively import `duck-1` optimizations one at a time
2. after each imported optimization, rerun unit tests and the same 16-game smoke
3. if the smoke passes, create another preliminary draft commit
4. if the smoke fails or the engine behavior regresses, remove the optimization

After all planned trusted features and accepted `duck-1` optimizations are in:

1. run 64-game local tournaments against each of:
   - `jon-6-a9bfs-surround`
   - `leeroy-jonkins`
   - `jon-6`
2. require at least 80% win rate against each opponent
3. require at least 150k average TiEq
4. use those tournaments to bug-hunt, tune, optimize, and refine
5. only after local results are favorable, run 15 remote games against each opponent
6. require at least a 9-6 remote match score against each opponent before closing

## Feature sequencing

Trusted-feature wave:

1. marker-system unification and timing-governor substrate
2. perception boundary and cached marker views
3. anytime-resume navigation
4. speculative navigation
5. hijack consolidation
6. combat consolidation:
   - assault posture
   - trench posture
   - zerg posture
   - offensive logistics
   - smart aiming

`duck-1` wave:

1. inspect one optimization primitive at a time
2. re-derive it against trusted behavior
3. validate it in unit tests and local engine smoke before keeping it

## Trusted-wave results

- `marker-system unification and timing-governor substrate`
  - smoke: `14-2` vs `jon-6-a9bfs-surround` (`87.5%`)
  - report: `.dist/reports/got-any-grapes_trusted1800_smoke.json`
  - commit: `642149e`
- `world-orientation marker sharing`
  - smoke: `11-5` vs `jon-6-a9bfs-surround` (`68.8%`)
  - report: `.dist/reports/got-any-grapes_orientation_smoke.json`
  - commit: `7c5a7a7`
- `opportunistic hijack mode`
  - smoke: `13-3` vs `jon-6-a9bfs-surround` (`81.2%`)
  - report: `.dist/reports/got-any-grapes_hijack_smoke.json`
  - commit: `bdedac1`
- `frontier recovery on single-builder stall`
  - smoke: `10-6` vs `jon-6-a9bfs-surround` (`62.5%`)
  - report: `.dist/reports/got-any-grapes_frontier_recovery_smoke.json`
  - commit: `d9442a7`
- `economy opening unclog`
  - smoke: `12-4` vs `jon-6-a9bfs-surround` (`75.0%`)
  - report: `.dist/reports/got-any-grapes_opening_unclog_smoke.json`
  - commit: `df15e7f`
- `ore-route temporary blacklist`
  - smoke: `13-3` vs `jon-6-a9bfs-surround` (`81.2%`)
  - report: `.dist/reports/got-any-grapes_ore_blacklist_v2_smoke.json`
  - commit: `479c86b`
- `faster opening-shell ore retarget`
  - smoke: `10-6` vs `jon-6-a9bfs-surround` (`62.5%`)
  - report: `.dist/reports/got-any-grapes_early_ore_retry_smoke.json`
  - probe: `12-4` vs `jon-6`
  - probe report: `.dist/reports/got-any-grapes_early_ore_retry_probe_jon6_16.json`
  - commit: pending
