# jon-6-a4bfs

`jon-6-a4bfs` is the `jon-6` economy / ore / tiling-back bot with the
`jon-5o-a4bfs` assault stack grafted into it.

## Integration Summary
- Imported the `jon-5o-a4bfs` assault stack into `jon-6`:
  `assault.py`, `mode_assaulting.py`, `sentinel_bot.py`, assault markers,
  assault perception state, and the BFS-first / Bug 2 assault navigation path.
- Kept the `jon-6` economy side as the non-assault baseline:
  ore finding, tiling-back, return-target refresh, bridge-aware cardinal
  routing, connected-line sharing, and `healing.preemptive_heal_or_move`.
- Updated the shared plumbing so both halves can coexist:
  `core_bot.py`, `builder_bot.py`, `main.py`, `navigation.py`,
  `perception.py`, `marker.py`, `states.py`, and `utils.py`.
- `main.py` now dispatches the imported sentinel unit so assault-side sentinels
  actually run their own controller after the port.

## Spawn And Role Split
- Ore / economy bots now spawn only on the `4` cardinal tiles around the core.
- Assault bots now spawn only on the `4` diagonal tiles around the core.
- The diagonal spawn position is also the assault-role tag in
  `builder_bot.py`, so diagonal builders immediately boot into
  `BuilderMode.ASSAULTING`.
- The first `4` builders stay economy, rounds `5` and `6` force the first two
  diagonal assault spawns, and a `3rd` assault bot unlocks once the team
  reaches `90` titanium.
- Assault spawns also publish assault-spawn markers so the imported
  `jon-5o-a4bfs` coordination logic can see those builders.

## Assault Stack Brought Over From `jon-5o-a4bfs`
- BFS-first with Bug 2 fallback for assault movement.
- Assault site ranking, anchor assessment, symmetry inference, predicted
  harvester scouting, and global frontier fallback.
- Assault claim markers, sentinel placement logic, adjacent-wait handling, and
  same-harvester deconfliction.
- Enemy-core-center-only pressure scoring, plus the blacklist /
  exhausted-region / move-on retirement rules from the `a4` assault line.

## jon-6 Economy Pieces Kept Intact
- `FINDING_ORE` and `TILING_BACK` stay the `jon-6` economy baseline.
- Economy builders still use cardinal routing, bridge-aware tiling-back,
  connected conveyor sharing, connected harvester sharing, and preemptive
  healing.
- Assault builders do not take the economy healing shortcut; they stay on the
  imported assault stack once their diagonal spawn tags them as assault.

## Bridge Fix From `jon-5a1`
- The `jon-5a1` bridge-transit snippet (`5a`) had to be inserted into
  `mode_tiling_back.py` to fix the regression where the integrated bot could
  enter a bridge step but fail to actually place the bridge.
- The important part of that `5a` snippet is the pending-bridge flow:
  keep `pending_bridge_plan`, compute the short transit path off the bridge
  start, queue `pending_build = (ActionType.BRIDGE, bridge_start, bridge_end)`
  once the bot steps away, then restore the saved master path.
- Without the inserted `5a` snippet, builders could path as if a bridge existed
  but never complete the bridge build, which is why the bot looked like it
  would not build bridges.

## Current State
- The bridging bug has been fixed.
- Economy and tiling-back are in a usable state again after the bridge fix.
- This bot is the reference snapshot for "`jon-6` economy +
  `jon-5o-a4bfs` assault stack".
- Main known problem: all assault bots TLE from turn `1`.

## TODO
- [ ] fix the assault-bot TLE issue from turn `1`
- [ ] profile where assault mode is spending time on the opening turns
- [ ] verify that assault site selection and marker reads still behave after
      the TLE fix

## Notes
- `jon-6-a5bfs` is the next workspace for experimenting on assault-side fixes.
- Keep this bot as the reference point after the bridge fix.
