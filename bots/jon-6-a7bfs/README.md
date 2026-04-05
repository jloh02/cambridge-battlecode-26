# jon-6-a7bfs

`jon-6-a7bfs` branches from `jon-6-a5bfs` and implements the V2 assault-state-machine proposal in `bots/jon-6-a5bfs/V2_PROPOSAL_NEW_ASSAULT_STATE_MACHINE.md`.

## Implemented
- Replaced the assault control flow with the four-state `ESCAPE -> SCOUT -> APPROACH -> EXECUTE` model.
- Added persisted EXECUTE subplans: `BUILD`, `CLEAR_THEN_BUILD`, and `WAIT_FOR_SLOT`.
- Replaced Bug-2 assault navigation with bounded BFS plus best-frontier fallback and a 5-turn assault temporary-obstacle TTL.
- Removed `connected_friendly_harvesters` from assault inference and switched predicted-harvester generation to mirrored ore sources only.
- Added symmetry informative-tile caching for assault symmetry evaluation.
- Fixed assault claim publication to use `place_assault_marker_around`.
- Simplified opening escape to outward movement plus shell-local exit selection after repeated blockage.
- Kept live anchors in `SCOUT` when no usable site exists instead of prematurely retiring them as `ring_blocked`.
- Unified assault-claim TTL handling at 12 turns across planner publication and perception-side claim decoding.
- Forced stale-discovery frontier fallback to remain enemy-half only when an anchor hint is available.
- Removed the leftover `known_connected_harvesters` state and perception maintenance path.
- Removed dead pre-V2 assault wait/support helpers that no longer participate in the four-state machine.

## Validation
- `pytest -q tests/test_jon_6_a7bfs_assault.py tests/test_jon_6_a7bfs_navigation.py tests/test_jon_6_a7bfs_core.py`
  `28 passed`
- `python tools/run_representative_benchmark.py jon-6-a7bfs jon-6-a5bfs --maps default_small1.map26 default_medium1.map26 default_large1.map26 --seeds 1 --jobs 8`
  `1-5` on the prescribed smoke benchmark.
- `python tools/run_representative_benchmark.py jon-6-a7bfs jon-6-a5bfs --seeds 1 --jobs 8`
  Historical pre-fix representative result: `5-5`.
- Historical benchmark file from before the rename: `.rep_bench/20260405_184818_jon-6-a7bfs-g_vs_jon-6-a5bfs.json`
- Smoke benchmark file after the V2 cleanup pass: `.rep_bench/20260405_222452_jon-6-a7bfs_vs_jon-6-a5bfs.json`

## Notes
- The current V2 implementation appears complete against the proposal, but the bot is still weaker than `jon-6-a5bfs` on the required smoke benchmark.
- In the smoke run, `jon-6-a7bfs` only won the `jon-6-a5bfs vs jon-6-a7bfs` seat on `default_medium1.map26`; it lost both `default_small1` seats and both `default_large1` seats.
- The earlier full representative split suggests the V2 rewrite is viable, but the fresh smoke check shows the cleanup pass did not improve the matchup against `jon-6-a5bfs`.
- Renamed the dedicated pytest files from `a7bfsg` to `a7bfs` after promoting the bot directory.
- Added regression coverage for live-anchor no-site fallback, enemy-half-only frontier scouting, claim-TTL consistency, and the removed V2 assault state fields.
