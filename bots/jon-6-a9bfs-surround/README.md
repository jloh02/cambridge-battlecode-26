# jon-6-a9bfs-surround

`jon-6-a9bfs-surround` branches from `jon-6-a8bfs` and swaps the assault planner to a much simpler surround-first policy. Once a visible enemy harvester is found, the bot now tries to fill the cardinal ring around it with sentinels instead of ranking secondary turret/core/logistics shots.

## Implemented
- Replaced the assault site planner with a surround planner that scores ring tiles first, then keeps the existing forward-direction alignment heuristic to choose only the best forward / forward-left / forward-right sentinel facings.
- Simplified visible-anchor scoring so partially surrounded harvesters stay preferred until their in-bounds ring is resolved.
- Changed clearable assault ring buildings to enemy conveyors and bridges only. Enemy armoured conveyors are now treated as blocked, and opportunistic assault fire no longer targets them.
- Kept the friendly-conveyor safety rule intact: only enemy ring logistics are considered clearable, so the assault bot will not destroy our own conveyor lines around a target.
- Added heal-stall handling for repeated clear attempts on the same ring tile. If a cleared conveyor keeps coming back, the anchor is retired and the scout cache is redirected to an off-screen predicted harvester instead of cycling locally.

## Validation
- `source .venv/bin/activate && pytest -q tests/test_jon_6_a9bfs_surround_assault.py`
  `4 passed`
- `source .venv/bin/activate && python tools/run_representative_benchmark.py jon-6-a9bfs-surround jon-6-a8bfs --seeds 1 --jobs 8`
  `1-9`
  Benchmark file: `.rep_bench/20260406_002805_jon-6-a9bfs-surround_vs_jon-6-a8bfs.json`

## Notes
- The new planner deliberately leaves the broader scout and navigation state machine alone. The change is meant to isolate whether simpler surround execution is better before reopening movement or symmetry logic again.
