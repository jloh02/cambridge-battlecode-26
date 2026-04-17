# CODEX Scratchpad

## Active Long-Form Task

### Current active task (2026-04-17): remote-safety ROI pass

| Field | Current state |
| --- | --- |
| Active strategy name | `remote_safety_roi_pass` |
| Task | Improve `bots/got-any-grapes/` against `jon-6`, `jon-6-a9bfs-surround`, and `leeroy-jonkins`, with priority on reducing builder timing pressure before macro benchmarking. |
| Criteria | Preserve legal per-unit state/marker-only coordination, keep direct-core economy, reduce remote `% builder turns >1ms`, `% >1.5ms`, `% >2ms`, and TLE pressure, then validate win rate and TiEq by opponent/seat. |
| Latest evidence | Remote r2 timing diagnostic completed at `13-17` overall, avg TiEq `33,610`, worst TiEq `0`, avg builder `>1ms` `51.1%`, avg builder `>1.5ms` `45.1%`, avg builder `>2ms` `41.3%`, total TLE turns `340,385`. Batch 30 DEBUG profiling was kept and identified `_find_best_ore_target()` as the dominant measured economy-mode subphase. Batch 31 no-target scan suppression was reverted after same-seed smoke/profile showed no useful cache-hit reduction once current-position invalidation was made correct. |
| Immediate next action | Stop per user request after the Batch31 smoke/analysis phase, summarize the nine-hour iteration table, and commit kept parts separately. Avoid stale shared-progress cleanup, economy road skipping, lazy road moves, road-action reordering, production `scan_micro()` routing, visible harvester caps, current-target stickiness, ore friend-claim lower-bound skips, early marker-scan/connected-refresh gate splitting, opening-escape tuple refactors, full-perception turret danger parity, TILING_BACK positive buildability check reuse, cached-path tuple/slice allocation rewrites, visible movement-prep SDK skips, broad source-seeded core-slot spread, and current-position-safe no-target scan caching; these were behavior-sensitive, too weak, or regressive under `USE_GLOBAL_SEED=true` g16/smoke. |
| Resume point | No local/remote evaluations are running. Current kept code is Batch 30 DEBUG subphase profiling plus earlier retained live changes. Batch31 has been reverted from code/tests; only STATUS records its evidence. Full runtime substrate passes (`255 passed`). |

#### Batch 28: visible-tile movement-prep SDK skip

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety reduction in movement preparation after path choice. The DEBUG turn-profile run on `labyrinth`/`jon-6` showed many EXPLORING/FINDING_ORE turns around `1.1-1.5ms`; on path-cache-hit turns navigation compute was only `~15-20us`, so the remaining hot work is SDK-heavy move preparation and execution. |
| Planned code change | Add a navigation helper that uses the current adjacent-tile perception record before calling SDK marker/road probes. If current grid data says the next tile's building is not a marker, skip `get_tile_building_id`/`get_entity_type` marker destruction. If current grid data says the tile already has a building, or has known non-empty terrain, skip `can_build_road`. Keep fallback SDK behavior when grid data is missing or inconclusive. |
| Completion surface | Touch only `navigation.py` movement-prep helpers/callers and focused runtime-substrate tests. Apply the helper to normal economy path movement and assault move execution where road prep already existed. No path scoring, A* budgets, mode transitions, marker schemas, perception scans, TILING_BACK conveyor construction, direct-core routing, spawn policy, or shared coordination changes. |
| Invariants to check | Adjacent visible marker tiles are still destroyed before road attempts. Unknown/stale grid data still takes the old SDK path. Known empty terrain still tries `can_build_road` and builds roads. Known roads/conveyors/other buildings skip only road-build checks that would be false. Movement still calls `can_move`/`move` exactly as before. |
| Edge cases to check | Visible non-marker road tile with SDK marker probe forbidden; visible marker tile still calls destroy and then road build; unknown grid tile falls back to SDK marker and road checks; known ore/wall terrain does not call `can_build_road`; assault `build_road=True` path uses the same preparation helper. |
| Time-risk check | Removes repeated SDK calls on hot movement turns; adds only one `grid.get` and a few dictionary/enum checks. It does not move work before A*, increase loop bounds, add marker scans, or add per-unit shared state. |
| Execution model | Pure private per-builder grid/perception cache use. No globals for coordination and no communication outside existing marker behavior. |
| Validation plan | `py_compile navigation.py`, focused movement-prep tests, full runtime substrate, touched-file `git diff --check`, bug audit of all changed call paths, one same-seed smoke, then `USE_GLOBAL_SEED=true` g16 only if cheap checks and audit are clean. Remote r2 only if local evidence is acceptable. |
| Code changed | Added `_destroy_visible_marker_if_present()`, `_should_probe_road_build()`, and `_prepare_passable_move_tile()` in `navigation.py`. Replaced the direct `utils.destroy_marker_if_present()` plus `ct.can_build_road()` sequence in `try_pathfinding_move()` and `_execute_assault_move()` with the helper. |
| Tests | Added four focused tests: visible road skips marker and road SDK probes, visible marker is still destroyed before road build, unknown next tile falls back to SDK probes, and assault move execution uses the same visible-tile preparation skip. |
| Cheap validation | `py_compile navigation.py` passed; focused movement-prep tests passed (`4 passed, 252 deselected`); full runtime substrate passed (`256 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Re-read the helper, both call sites, the old `utils.destroy_marker_if_present()` behavior, and remaining direct marker-destroy callers. Invariants hold: marker tiles still use the old destroy path; unknown grid entries still call SDK probes; known empty terrain still probes/builds roads; known roads/conveyors/buildings and known non-empty terrain skip only checks that would be false. Movement action order after preparation is unchanged. No introduced bug found. |
| Next validation | Run one same-seed local smoke and analyze replay for TiEq, source-port distribution, loop/no-progress signals, and local timing-field trustworthiness. Do not start g16 until smoke and another no-edit audit are complete. |
| In-smoke no-edit audit | While the smoke ran, re-read perception freshness and movement call paths. Normal builder turns always call `perception.scan_around()` before `try_pathfinding_move()` except opening-escape-only turns, which do not use this helper. Full perception refreshes a radius-2 safety ring; fast perception refreshes the nearby local tile set. `assault_navigate()` is called after perception, and unknown grid entries still fall back to the old SDK probes. No introduced bug found. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by enemy core destruction on turn `756`: got-any-grapes delivered `17,230` Ti, final stored `2,127`, `16` builder bots alive, `380` buildings; `jon-6` delivered `26,070` Ti, final stored `4,217`, `11` units, `558` buildings. TiEq is `117,230` because of the early-win bonus. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch28_visible_move_prep_settlement.json`: active source ports `3`, source top1 share `38.8%`, top3 share `100%`, builder max small-loop streak `187`, no-progress streak `18`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; local timing fields remain all zero/untrustworthy. |
| Next validation | Proceed to `USE_GLOBAL_SEED=true` g16. Do not remote-test unless local cross-opponent evidence is acceptable and no-edit audit during g16 finds no code bug. |
| In-g16 no-edit audit | While g16 ran, grep-confirmed the batch boundary: the new helper was called only from normal path movement and assault move execution; direct marker destruction remained in TILING_BACK conveyor-clear logic. No A* scoring, route construction, perception, marker payload, spawn, direct-core, or role-transition code was touched. No introduced code bug found; remaining risk was timing/order perturbation from fewer SDK probes. |
| g16 report | `.dist/reports/got-any-grapes_batch28_visible_move_prep_g16_20260417.json` |
| g16 aggregate | `28-20` (`58.3%`), avg TiEq `43,961.7`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `11-5`, avg TiEq `55,435.6`, worst `0`; seat split AB `4-4` avg `54,648.8`, BA `7-1` avg `56,222.5`. |
| `jon-6-a9bfs-surround` | `8-8`, avg TiEq `30,928.8`, worst `670`; seat split AB `6-2` avg `28,680.0`, BA `2-6` avg `33,177.5`. |
| `leeroy-jonkins` | `9-7`, avg TiEq `45,520.6`, worst `50`; seat split AB `4-4` avg `48,647.5`, BA `5-3` avg `42,393.8`. |
| Batch9 comparison | Aggregate `-6` wins, `+747.7` avg TiEq, and `-740` worst TiEq. `jon-6` was equal wins and `+7,781.2` avg TiEq, but worst dropped `3,990 -> 0`; `a9` was `-3` wins and `-324.4` avg TiEq; `leeroy` was `-3` wins and `-5,213.8` avg TiEq. This fails the every-opponent TiEq rule and weakens both pressure matchups. |
| Decision | Revert and do not remote-test. The helper was mechanistically plausible, but local g16 shows pressure-matchup regression without trustworthy local timing proof. Remote validation would be spending timing-truth budget on a known-bad local candidate. |
| Next target | Revert Batch28 code/tests, validate baseline restoration, then pick a new ROI away from movement-prep timing perturbations unless stronger remote timing evidence justifies it. |
| Revert validation | Removed the movement-prep helper and four focused Batch28 tests. `py_compile navigation.py` passed; focused movement/navigation tests returned to `4 passed, 248 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; exact stale-symbol search found Batch28 helper/test names only in STATUS history. |
| Next target after revert | Avoid movement-prep SDK-skip changes without remote timing evidence because even post-A* SDK timing perturbation can shift local macro outcomes. Next ROI should target a correctness/resilience failure with stronger behavioral upside or a runtime gate whose local behavior impact is intentionally nil. |

#### Batch 29: source-seeded core-slot spread

| Item | Finding |
| --- | --- |
| ROI target | Algorithmic port distribution for direct-core throughput. Batch9 and later smokes repeatedly report `core_port_concentration`, often with only `3-4` active source ports and source top1 share above the desired `30%`. The live `_assign_core_lane_slot()` spread offset is slot-count bounded, but it is primarily owner-id/slot based; a builder that harvests multiple nearby veins keeps the same port preference across those lanes. |
| Planned code change | Include the lane source seed (`last_harvester_pos`, else spawn/origin) in the existing `spread_offset` hash while keeping the modulo bounded by `slot_count`. Do not increase the spread range, do not add marker claims, do not change port load penalties, and do not change direct-core fallback/rotation behavior. |
| Completion surface | Touch only `_assign_core_lane_slot()` scoring/commentary in `mode_tiling_back.py` plus focused tests around slot assignment. No TILING_BACK build execution, A*, perception, marker protocol, spawn policy, direct-core enablement, or assault behavior changes. |
| Invariants to check | Cached valid core lane slot is still reused. Tried slots are still skipped. All slots exhausted still returns `None`. Existing orphan, other-claim, connected-load, and distance penalties remain in the same score tuple. Spread offset remains `< slot_count`, preserving the rejected-idea boundary against `slot_count * 3` expansion. |
| Edge cases to check | Missing `last_harvester_pos` falls back to spawn/origin. Same owner with different harvester seeds can receive different equal-cost slots. Existing tests for rotation and exhausted slots remain valid. |
| Time-risk check | Adds four integer hash operations inside a 12-slot loop only when assigning a core lane slot. No SDK calls, no A*, no map-wide scans, no marker work, and no per-turn hot-path work after a slot is cached. |
| Execution model | Pure private per-builder scoring based on local state. No shared Python state and no non-marker communication. |
| Validation plan | `py_compile mode_tiling_back.py`, focused slot-assignment tests, full runtime substrate, bug audit, same-seed smoke, then `USE_GLOBAL_SEED=true` g16 if cheap checks are clean. Remote validation only if g16 improves every-opponent TiEq or has a strong cross-opponent rationale without pressure-matchup collapse. |
| Code changed | Added `seed_pos.x` and `seed_pos.y` to the existing `spread_offset` hash in `_assign_core_lane_slot()`, while keeping `% max(slot_count, 1)`. Updated comments to describe owner/source-seeded spread. |
| Tests | Added `test_core_lane_slot_spread_depends_on_harvester_seed()` to prove the same builder and same origin can choose different bounded-spread slots when the harvested source changes. Existing rotation/exhaustion tests still cover tried-slot behavior. |
| Cheap validation | `py_compile mode_tiling_back.py` passed; focused core-lane/rotation tests passed (`5 passed, 248 deselected`); full runtime substrate passed (`253 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Re-read `_assign_core_lane_slot()`, `_select_core_return_target()`, and the focused tests. Invariants hold: cached core lane slots are returned before rescoring; tried slots are skipped; exhausted tried slots still return `None`; orphan, other-claim, connected-load, and distance penalties are unchanged; spread remains `< slot_count`. No SDK calls, A*, marker communication, or shared state were added. No introduced bug found. |
| Next validation | Run the same-seed `settlement`/`jon-6` smoke and analyze source-port distribution plus loop/no-progress signals before g16. |
| In-smoke no-edit audit | While the smoke ran, rechecked source fallback (`last_harvester_pos -> spawn_pos -> origin`) and confirmed the change only affects uncached core-lane assignment. Cached lanes, missing slots, and non-direct-core return targets keep prior behavior. No introduced bug found. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by titanium tiebreak at turn `2000`: got-any-grapes delivered `84,810` Ti, final stored `63,238`, `15` builder bots alive, `591` buildings; `jon-6` delivered `37,870` Ti, final stored `42`, `10` units, `304` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch29_source_seed_slot_spread_settlement.json`: active source ports `5`, source top1 share `23.0%`, top3 share `64.8%`, builder max small-loop streak `508`, no-progress streak `18`, failure signals `small_loop`, `low_builder_progress`, and `travel_without_build`; `core_port_concentration` disappeared. Local timing fields remain all zero/untrustworthy. Compared with Batch9 same-seed smoke, delivered Ti improved `63,580 -> 84,810`, active source ports `4 -> 5`, and source top1/top3 concentration improved materially. |
| Next validation | Proceed to `USE_GLOBAL_SEED=true` g16. Do not remote-test unless cross-opponent evidence is acceptable and no-edit audit during g16 finds no bug. |
| In-g16 no-edit audit | Grep-confirmed the explicit Batch29 code symbols were only the two source multipliers in `spread_offset` and the focused regression test. The broader file diff contains older retained live changes, so the batch boundary was judged by exact symbols and call paths. No introduced code bug found; remaining risk was changed lane geometry. |
| g16 report | `.dist/reports/got-any-grapes_batch29_source_seed_slot_spread_g16_20260417.json` |
| g16 aggregate | `29-19` (`60.4%`), avg TiEq `40,992.5`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `12-4`, avg TiEq `51,745.0`, worst `390`; seat split AB `7-1` avg `55,872.5`, BA `5-3` avg `47,617.5`. |
| `jon-6-a9bfs-surround` | `10-6`, avg TiEq `37,070.6`, worst `220`; seat split AB `4-4` avg `26,447.5`, BA `6-2` avg `47,693.8`. |
| `leeroy-jonkins` | `7-9`, avg TiEq `34,161.9`, worst `0`; seat split AB `4-4` avg `48,100.0`, BA `3-5` avg `20,223.8`. |
| Batch9 comparison | Aggregate `-5` wins and `-2,221.5` avg TiEq. `jon-6` was `+1` win and `+4,090.6` avg TiEq, but `a9` was `-1` win despite `+5,817.5` avg TiEq, and `leeroy` was `-5` wins and `-16,572.5` avg TiEq with a zero worst. This fails every-opponent TiEq and materially weakens the no-TLE offensive stress matchup. |
| Decision | Revert and do not remote-test. The smoke showed the intended port-spread mechanism, but the broader map/opponent sample says source-seeded slot ordering over-rotates `leeroy` lane geometry, especially as second seat. |
| Next target | Revert Batch29 code/tests. Future port-spread work should use a narrower guard, for example only applying source-seeded spread when current source-port concentration is locally visible or when direct-core candidates are within a smaller distance band. Do not reintroduce this broad source-seeded spread blindly. |
| Revert validation | Removed the source-seed multipliers and the focused Batch29 test. `py_compile mode_tiling_back.py` passed; focused core-lane/rotation tests returned to `4 passed, 248 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; exact stale-symbol search found Batch29 helper/test symbols only in STATUS history. |
| Next target after revert | Avoid broad port spread changes without a `leeroy` guard. Next ROI should either directly target `leeroy`/offensive survival or reduce TLE via diagnostics/instrumentation that does not alter macro lane geometry. |

#### Batch 30: DEBUG-only mode subphase profiling

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety diagnosis. DEBUG profile evidence already shows many slow `EXPLORING`/`FINDING_ORE` builder turns where `nav_compute_ns` is small but `mode_us` remains around the danger band. Recent guessed hot-path edits changed behavior and failed g16, so the highest-ROI next batch is to expose the remaining mode subphase costs before changing production decisions. |
| Planned code change | Add `DEBUG_TURN_PROFILE`-guarded `time.time_ns()` probes inside `mode_finding_ore.execute()` and `mode_exploring.execute()`. Emit subphase keys for blacklist/recheck/retile/target/share/build/nav/progress/fallback in FINDING_ORE and setup/clear/select/nav/progress/retarget in EXPLORING. |
| Completion surface | Touch only `mode_finding_ore.py`, `mode_exploring.py`, focused instrumentation tests, and STATUS. No target scoring, pathfinding, perception, marker encoding, direct-core routing, TILING_BACK construction, spawn policy, or role transitions. |
| Invariants to check | With `DEBUG_TURN_PROFILE=false`, the new code must not call `time.time_ns()` from the added probes and must not mutate bot state. With profiling enabled, the old actions still run exactly once and the profile keys are additive diagnostics only. All early-return paths must preserve the pre-existing return behavior. |
| Edge cases to check | FINDING_ORE retile early return, adjacent-ore build/existing/wait/failure returns, no-target defender hold, no-target non-defender fallback into EXPLORING, EXPLORING target exhaustion return, progress success return, retarget return, and blacklist return. |
| Time-risk check | Production overhead is limited to a small number of constant false boolean branches and local assignments in two mode functions; no SDK calls, loops, A*, marker scans, or shared state are added. DEBUG runs intentionally pay for `time.time_ns()` so they can identify real bottlenecks. |
| Execution model | Pure private per-builder diagnostics. No shared Python state for coordination and no communication outside the existing marker system. |
| Validation plan | Add focused tests proving disabled profiling records no subphase keys and enabled profiling records expected mode subphase keys without changing mode transitions. Then run `py_compile`, focused tests, full runtime substrate, diff check, bug audit, and a DEBUG same-seed profile smoke. No g16/remote benchmark until the profile points to a complete production optimization batch. |
| Code changed | Added `import time` and `profile_enabled = utils.DEBUG_TURN_PROFILE` guarded subphase timing to `mode_finding_ore.execute()` and `mode_exploring.execute()`. FINDING_ORE now reports `finding_blacklist_ns`, `finding_recheck_claims_ns`, `finding_retile_scan_ns`, `finding_retile_commit_ns`, `finding_best_target_ns`, `finding_share_marker_ns`, `finding_adjacent_ore_ns`, `finding_move_nav_ns`, `finding_progress_note_ns`, and `finding_no_target_fallback_ns` when DEBUG turn profiling is enabled. EXPLORING now reports `explore_setup_ns`, `explore_clear_target_ns`, `explore_select_target_ns`, `explore_nav_ns`, `explore_progress_note_ns`, and `explore_retarget_ns` when enabled. |
| Tests | Added three focused instrumentation tests: disabled profiling for both modes must not call `time.time_ns()` or record profile keys; enabled FINDING_ORE move-path profiling records the expected subphase keys while still calling the progress hook once; enabled EXPLORING successful-move profiling records setup/clear/nav/progress keys and preserves the zero-stall success behavior. |
| Cheap validation | `py_compile mode_finding_ore.py mode_exploring.py` passed; focused `subphase_profile` tests passed (`3 passed, 252 deselected`); full runtime substrate passed (`255 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Re-read both edited `execute()` functions and focused tests. A double-count hazard in the adjacent-ore build path was found during review and fixed before full validation. Current invariants hold: profiling disabled performs no added `time.time_ns()` calls in the tested FINDING_ORE/EXPLORING paths; enabled profiling only calls `utils.bump_profile`; target choice, marker placement, navigation calls, retile commits, adjacent-ore returns, defender no-target hold, and EXPLORING retarget/blacklist transitions retain the old control flow. |
| Next validation | Run one DEBUG same-seed profile smoke on a known slow map/opponent to collect subphase `turn_profile` evidence. Do not run g16 or remote for this diagnostic batch because production behavior is intentionally unchanged and the next benchmark should wait for a complete optimization batch informed by the profile. |
| In-smoke no-edit audit | While the DEBUG smoke ran, re-read all added profile guards and early-return lines. The added `time.time_ns()` calls are only under `profile_enabled`; every return in the edited FINDING_ORE adjacent/retile/no-target paths has a matching profile write only when profiling is enabled; EXPLORING success, retry, retarget, and exhausted returns preserve old state transitions. No additional bug found. |
| DEBUG smoke | Same-seed `labyrinth`/`jon-6` profile smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) lost by titanium tiebreak at turn `2000`. Analyzer report: `.dist/replay_analysis/got-any-grapes_batch30_profile_labyrinth_seed_204011053.json`; replay: `.dist/replays/got-any-grapes_batch30_profile_labyrinth_seed_204011053.replay26`. TEAM_A/got-any-grapes delivered `24,200` Ti, final stored `22,916`, placed `16` builders, `6` harvesters, `122` conveyors, `20` bridges, `154` roads. TEAM_B/jon-6 delivered `33,320` Ti, final stored `36,279`, placed `11` builders, `7` harvesters, `42` conveyors, `3` bridges, `224` roads. |
| Smoke diagnostics | got-any-grapes failure signals: `small_loop`, `low_builder_progress`, `travel_without_build`, `idle_output_spam`, and `core_port_concentration`; builder max small-loop `1132`, max no-progress `18`, no-progress turns `11421`; active source ports `4`, source top1 share `41.0%`, top3 share `99.8%`. Local replay timing fields remain all zero/untrustworthy (`builder_turns_over_1ms_rate = 0.0`, TLE `0`). |
| Profile findings | Parsed `21,509` DEBUG `turn_profile` lines from the replay. Modes: `EXPLORING 13,904`, `FINDING_ORE 7,600`, `RUSH 3`, `TILING_BACK 2`. Overall profiled turns averaged `1256.6us` (`p90 1410us`, `p99 1514us`). `finding_best_target_ns` appeared on `21,504` lines with avg `700.4us`, median `699us`, p90 `747us`, p99 `830us`, max `1220us`. `finding_move_nav_ns` averaged `345.0us` over FINDING_ORE lines. EXPLORING fallback turns paid both `finding_best_target_ns` and `finding_no_target_fallback_ns`; `finding_no_target_fallback_ns` averaged `399.9us`, while the embedded `explore_select_target_ns` averaged `220.7us` and `explore_nav_ns` averaged `173.4us`. |
| Decision | Keep Batch30 as diagnostic instrumentation for now; do not g16/remote-test it because it intentionally changes only DEBUG output and production behavior. The next production batch should target redundant `_find_best_ore_target()` work, especially repeated no-target scans before EXPLORING fallback, using private-state caching/time gates rather than movement-prep or lane-geometry changes. |
| Next target | Batch31 candidate: add a short private no-ore/ore-target negative cache in FINDING_ORE so builders do not spend ~700us every turn proving no viable ore before exploring. The cache must invalidate on new ore discovery, blacklist expiry, claimed-harvester/retiling changes, role/defender constraints, and current-position/visible-logistics changes enough to avoid missing newly viable ore. |

#### Batch 31: no-target ore scan suppression

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety reduction in the measured hottest economy mode subphase. Batch30 profile showed `finding_best_target_ns` on `21,504/21,509` profiled slow lines with avg `700.4us`, including EXPLORING fallback turns that immediately found no ore target and then explored. |
| Planned code change | Add a cheap `has_known_titanium_target_hint()` filter and a short private no-target retry cache in `mode_finding_ore`. Use the hint in `BuilderBot` before switching EXPLORING builders back into FINDING_ORE. Use the retry cache inside FINDING_ORE after retile checks and before `_find_best_ore_target()` so already-FINDING_ORE builders can skip repeated negative scans briefly. |
| Completion surface | Touch `mode_finding_ore.py`, `builder_bot.py`, focused runtime-substrate tests, and STATUS. Do not change BFS scoring, ore distance heuristics, marker schemas, TILING_BACK routing, movement preparation, perception, direct-core routing, or spawn policy. |
| Invariants to check | A newly visible titanium count change invalidates the skip. Blacklist size, claimed-harvester count, connected-conveyor count, known-harvester count, and visible ally count changes invalidate the skip. Retile-disconnected-harvester priority still runs before any no-target skip. A real target found clears the no-target cache. The skip is private per builder and communicates nothing. |
| Edge cases to check | All ore claimed, all ore blacklisted, all ore already adjacent to connected transport, new ore discovered during retry window, builder already in FINDING_ORE with a valid no-target cache, defender no-target hold, and EXPLORING pre-switch target clearing only when the hint is true. |
| Time-risk check | Replaces repeated 50-120 node BFS plus Euclidean fallback scans with a small bounded local-grid hint and a short signature check. It adds no SDK-heavy loops beyond one `get_team()`/`get_current_round()` plus local set/dict lengths and at most cardinal-neighbor grid checks over known titanium positions. |
| Execution model | Pure private per-builder cache fields. No shared Python coordination and no non-marker communication. |
| Validation plan | Add focused tests for hint filtering, retry-cache skip, cache invalidation on new ore, and BuilderBot EXPLORING pre-switch behavior. Run `py_compile`, focused tests, full runtime substrate, diff check, bug audit, then a DEBUG profile smoke to confirm `finding_best_target_ns` occurrence drops on the same slow map before g16. |
| Code changed | Added `NO_ORE_TARGET_RETRY_TURNS`, private no-target retry signature/cache helpers, and `has_known_titanium_target_hint()` in `mode_finding_ore.py`. FINDING_ORE still runs disconnected-harvester retile priority first, then skips `_find_best_ore_target()` only when the short private no-target signature still matches. Added `BuilderBot._maybe_switch_exploring_to_finding_ore()` so EXPLORING builders only re-enter FINDING_ORE when the cheap hint says a titanium target is plausibly useful. |
| Tests | Added focused tests for claimed/blacklisted/connected-ore hint filtering, repeated no-target scan suppression, cache invalidation on new ore, cache invalidation after builder movement, and the BuilderBot EXPLORING pre-switch gate. |
| Cheap validation | `py_compile mode_finding_ore.py builder_bot.py tests/test_got_any_grapes_runtime_substrate.py` passed; focused Batch31 tests passed (`5 passed, 255 deselected`); full runtime substrate passed (`260 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Re-read the changed FINDING_ORE target-selection path, BuilderBot pre-switch path, and focused tests. Found and fixed one correctness gap before smoke: the no-target signature initially omitted current position even though target access and route scoring are position-dependent. The signature now includes `ct.get_position()` so movement invalidates the skip. Retile priority remains before the skip, real targets clear the cache, the cache is private per builder, and no marker/global/shared coordination was added. No remaining introduced bug found before smoke. |
| Local smoke | Same-seed `labyrinth`/`jon-6` DEBUG profile smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) lost by titanium tiebreak at turn `2000`: got-any-grapes delivered `23,840` Ti (`23,405` final stored), with `16` builders, `5` harvesters, `109` conveyors, `19` bridges, and `122` roads. `jon-6` delivered `41,280` Ti (`41,309` final stored), with `11` builders, `11` harvesters, `98` conveyors, `6` bridges, and `423` roads. Analyzer report: `.dist/replay_analysis/got-any-grapes_batch31_no_target_cache_profile_labyrinth_seed_204011053.json`; replay: `.dist/replays/got-any-grapes_batch31_no_target_cache_profile_labyrinth_seed_204011053.replay26`. |
| Profile findings | Parsed `16,985` DEBUG `turn_profile` lines. Modes: `EXPLORING 10,324`, `FINDING_ORE 6,611`, `TILING_BACK 47`, `RUSH 3`. Overall profiled turns averaged `1260.8us` (`p90 1412us`, `p99 1513us`), essentially unchanged from Batch30. `finding_best_target_ns` still appeared on `16,935` lines with avg `693.5us`, median `692us`, p90 `741us`, and p99 `789us`; no `finding_best_target_cache_hits` profile values were emitted. Correct current-position invalidation made the cache miss on the moving EXPLORING fallback path, so the mechanism did not remove the measured hotspot. |
| Smoke diagnostics | got-any-grapes failure signals remained `small_loop`, `low_builder_progress`, `travel_without_build`, `idle_output_spam`, and `core_port_concentration`; local replay timing fields remained all zero/untrustworthy. Compared with Batch30 same-seed smoke, delivered Ti was slightly worse (`24,200 -> 23,840`) and the opponent delivered materially more (`33,320 -> 41,280`), so the smoke does not justify g16 or remote validation. |
| Decision | Revert and do not benchmark further. The cache is only safe with current-position invalidation, but that invalidation removes the intended benefit on the dominant moving fallback turns. Keeping the batch would add extra pre-switch logic and private cache state without measurable runtime relief or smoke benefit. |
| Revert validation | Removed the no-target cache helpers, hint function, BuilderBot helper, and five focused Batch31 tests. `py_compile mode_finding_ore.py builder_bot.py tests/test_got_any_grapes_runtime_substrate.py` passed; stale-symbol search for Batch31 names returned no live code/test matches; focused retained profiling/defender tests passed (`4 passed, 251 deselected`); full runtime substrate returned to `255 passed`; touched-file `git diff --check` clean. |
| Next target after revert | Do not retry short no-target scan caching unless the trigger can distinguish stationary/no-move fallback turns without suppressing position-dependent target checks. Better next ROIs are reducing the cost inside `_find_best_ore_target()` itself, caching route-distance/access work keyed by ore/frontier, or adding a stricter DEBUG profile for target-picker internals. |

#### Batch 27: small-loop shared-progress reset

| Item | Finding |
| --- | --- |
| ROI target | Algorithmic resilience with small runtime benefit: every Batch9 g16 game reports `small_loop` and `low_builder_progress`, and worst hard-map losses show long travel-without-build/no-progress streaks. Live small-loop recovery clears cached path, planner, temp obstacles, active ore target, return target, pending builds, and exploration target, but leaves `pathfinding_state["progress_state"]` and a possible `shared_progress_stalled` flag from the old target/mode intact. |
| Planned code change | In `BuilderBot._note_small_loop_progress()`, clear `progress_state` and `shared_progress_stalled` at the same time as path/planner/temp-obstacle recovery. Add one focused test that seeds stale shared-progress state, triggers small-loop recovery, and verifies all reset state is coherent. |
| Completion surface | Touch only `builder_bot.py` small-loop recovery and `tests/test_got_any_grapes_runtime_substrate.py`. No path scoring, A* budgets, perception, TILING_BACK route construction, marker protocol, spawning, direct-core routing, assault, or shared coordination changes. |
| Invariants to check | Recovery still preserves `ore_target_blacklist`; still clears active ore target/path/planner/temp obstacles/return target/pending builds/bridge transit/explore target; still respects heal-turn skip and recovery cooldown; stale shared-progress state cannot cause the next mode turn to consume an old stall flag or compare against an old target. |
| Edge cases to check | Existing progress state with old target, pending `shared_progress_stalled=True`, no movement possible during `utils.move_random()`, heal turns, incomplete history, and cooldown-protected repeated recovery. |
| Time-risk check | Removes two stale dictionary entries only on rare small-loop recovery, after a threshold of stuck turns. It adds no per-turn scans, SDK calls, A*, marker work, or persistent cross-unit state. |
| Execution model | Pure private per-builder state cleanup. No shared Python globals and no communication change; markers remain the only inter-unit channel. |
| Validation plan | `py_compile builder_bot.py`, focused small-loop/shared-progress tests, full runtime substrate, diff check, then one same-seed smoke and `USE_GLOBAL_SEED=true` g16 only if cheap checks and audit find no bugs. Remote r2 only if local evidence is acceptable. |
| Code changed | Added `self.pathfinding_state.pop("progress_state", None)` and `self.pathfinding_state.pop("shared_progress_stalled", None)` to `_note_small_loop_progress()` immediately after clearing `path`, `planner_state`, `last_replan_signature`, and `temporary_obstacles`. |
| Tests | Added `test_small_loop_recovery_clears_shared_progress_state()`, which seeds stale shared-progress state, stale path/planner/temp obstacles, active ore/return/explore/bridge state, and verifies recovery clears only the intended state while preserving `ore_target_blacklist`. |
| Cheap validation | `py_compile builder_bot.py` passed; focused regression passed (`1 passed, 252 deselected`); full runtime substrate passed (`253 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Re-read `_note_small_loop_progress()`, `navigation.note_shared_builder_progress()`, `navigation.consume_shared_progress_stall()`, and the FINDING_ORE/EXPLORING/TILING_BACK consumers. Clearing the one-shot stall flag during full recovery is coherent because mode-level consumers have already run on the current turn, and the next turn should not consume stale progress from an old target. Clearing `progress_state` is coherent because the next movement call rebuilds it through `setdefault()`. No introduced bug found. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by titanium tiebreak at turn `2000`: got-any-grapes delivered `64,920` Ti, final stored `24,377`, `16` builder bots alive, `639` buildings; `jon-6` delivered `49,120` Ti, final stored `27,721`, `3` builder bots alive, `308` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch27_small_loop_progress_reset_settlement.json`: active source ports `4`, source top1 share `29.45%`, top3 share `85.0%`, builder max small-loop streak `668`, no-progress streak `688`, failure signals `small_loop`, `low_builder_progress`, and `travel_without_build`; local timing fields remain all zero/untrustworthy. Compared with Batch9 same-seed smoke, delivered Ti improved `63,580 -> 64,920`, winner flipped from `jon-6` to got-any-grapes, active source ports stayed `4`, top1/top3 source concentration improved slightly, and max small-loop/no-progress roughly halved (`1258/1261 -> 668/688`). |
| Next validation | Proceed to `USE_GLOBAL_SEED=true` g16. No remote validation until g16 and no-edit audit are complete. |
| In-g16 no-edit audit | While g16 was running, re-read the Batch27 code delta, test, `note_shared_builder_progress()`, and all three `consume_shared_progress_stall()` callers. The larger worktree diff contains older retained changes, but the Batch27 written code is only the two stale-state `pop(..., None)` calls plus one regression test. `note_shared_builder_progress()` recreates `progress_state` with `setdefault()` on the next move, and clearing `shared_progress_stalled` after mode execution prevents only stale next-turn consumption. No Batch27 bug found so far. |
| Revision A g16 report | `.dist/reports/got-any-grapes_batch27_small_loop_progress_reset_g16_20260417.json` |
| Revision A aggregate | `30-18` (`62.5%`), avg TiEq `50,327.1`, worst TiEq `830`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| Revision A `jon-6` | `13-3`, avg TiEq `66,185.0`, worst `4,670`; seat split AB `6-2` avg `61,957.5`, BA `7-1` avg `70,412.5`. |
| Revision A `jon-6-a9bfs-surround` | `10-6`, avg TiEq `45,679.4`, worst `830`; seat split AB `5-3` avg `41,202.5`, BA `5-3` avg `50,156.2`. |
| Revision A `leeroy-jonkins` | `7-9`, avg TiEq `39,116.9`, worst `4,720`; seat split AB `4-4` avg `36,710.0`, BA `3-5` avg `41,523.8`. |
| Revision A Batch9 comparison | Aggregate `-4` wins but `+7,113.1` avg TiEq and `+90` worst TiEq. `jon-6` was `+2` wins and `+18,530.6` avg TiEq; `a9` was `-1` win but `+14,426.3` avg TiEq; `leeroy` was `-5` wins and `-11,617.5` avg TiEq. Because TiEq does not improve for every opponent and the pressure matchup collapses below noise, Revision A is not keepable as-is. |
| Revision A failure analysis | The largest drops are `leeroy/default_small2` (`125,030 -> 18,260`), `leeroy/wasteland_oasis` (`101,270 -> 15,790`), `leeroy/cinnamon_roll` (`100,000 -> 16,900`), and `a9/flowers` (`115,050 -> 19,640`). The same patch also flips major hard-map wins (`a9/wall`, `jon-6/donut`, `jon-6/default_large1`), so the mechanism is useful but too broad. Likely overreach: clearing `progress_state` delays same-target shared-progress temp obstacles after each small-loop cleanup. The narrower stale one-shot flag cleanup should preserve same-target stall memory while removing illegal stale next-turn consumption. |
| Revision A decision | Revise before any remote validation. Do not remote-test Revision A. |
| Revision B code changed | Removed the `progress_state` pop and now only clears `pathfinding_state["shared_progress_stalled"]` during small-loop recovery. Updated the regression test to assert detector history is preserved while the stale one-shot flag is removed. |
| Revision B cheap validation | `py_compile builder_bot.py` passed; focused regression passed (`1 passed, 252 deselected`); full runtime substrate passed (`253 passed`); touched-file `git diff --check` clean. |
| Revision B pre-smoke audit | Re-read the small-loop cleanup, regression test, `note_shared_builder_progress()`, and `consume_shared_progress_stall()`. Preserved `progress_state` is safe because the next movement call resets it when mode or target changes, and preserving it is useful when the same target remains stuck. Clearing only `shared_progress_stalled` prevents stale one-shot consumption in the next mode turn. No introduced bug found. |
| Revision B local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by enemy core destruction on turn `1346`: got-any-grapes delivered `34,930` Ti, final stored `8,352`, `16` builder bots alive, `520` buildings; `jon-6` delivered `55,220` Ti, final stored `13,985`, `9` builder bots alive, `719` buildings. |
| Revision B smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch27b_stale_stall_flag_settlement.json`: active source ports `3`, source top1 share `36.0%`, top3 share `100%`, builder max small-loop streak `736`, no-progress streak `35`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; local timing fields remain all zero/untrustworthy. The economy signal is weaker than Revision A on this seed, but early core destruction makes it a valid g16 candidate. |
| Revision B next validation | Run `USE_GLOBAL_SEED=true` g16. Do not remote-test unless cross-opponent g16 evidence is acceptable. |
| Revision B in-g16 no-edit audit | While Revision B g16 was running, re-read the actual Batch27B delta and grep-confirmed the only live code addition is `self.pathfinding_state.pop("shared_progress_stalled", None)`. The regression test now asserts the detector `progress_state` object is preserved and only the one-shot flag is removed. No introduced bug found so far. |
| Revision B g16 report | `.dist/reports/got-any-grapes_batch27b_stale_stall_flag_g16_20260417.json` |
| Revision B aggregate | `30-18` (`62.5%`), avg TiEq `38,946.7`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| Revision B `jon-6` | `8-8`, avg TiEq `47,291.2`, worst `0`; seat split AB `4-4` avg `55,283.8`, BA `4-4` avg `39,298.8`. |
| Revision B `jon-6-a9bfs-surround` | `11-5`, avg TiEq `32,587.5`, worst `10`; seat split AB `6-2` avg `30,881.2`, BA `5-3` avg `34,293.8`. |
| Revision B `leeroy-jonkins` | `11-5`, avg TiEq `36,961.2`, worst `1,990`; seat split AB `6-2` avg `41,580.0`, BA `5-3` avg `32,342.5`. |
| Revision B Batch9 comparison | Aggregate `-4` wins, `-4,267.3` avg TiEq, and `-740` worst TiEq. `jon-6` was `-3` wins and `-363.1` avg TiEq; `a9` was equal wins and `+1,334.4` avg TiEq; `leeroy` was `-1` win and `-13,773.1` avg TiEq. This fails the every-opponent TiEq rule and creates a zero-TiEq worst case. |
| Revision B decision | Revert and do not remote-test. Even the narrower stale one-shot flag cleanup is behavior-sensitive and does not improve every opponent. |
| Revert validation | Removed the Batch27 code line and regression test. `py_compile builder_bot.py` passed; focused shared-progress tests returned to `2 passed, 250 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; exact stale-symbol search for Batch27 test/helper patterns returned no live code/test matches. |
| Next target | Avoid small-loop/shared-progress cleanup without stronger replay evidence. Next ROI should come from a different concrete failure or runtime hot path, preferably one that is less timing-sensitive than changing movement recovery state. |

#### Batch 26: cached-path tuple validation

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety cleanup in `navigation.compute_pathfinding_step()`, which runs on every economy navigation turn. Cached-path validation currently allocates `state["path"][:A_STAR_LOOKAHEAD_CANCEL]` and builds temporary `Position` objects with `Position.add()` while checking whether the next few cached steps are still clear. Profile evidence shows route-heavy turns are a timing hotspot; this batch removes allocation from a path-reuse hot path without changing path choice. |
| Planned code change | Add a module-level direction-to-delta cache and replace cached-path validation/short-path endpoint simulation with `(x, y)` tuple arithmetic. Iterate by index up to `min(len(path), A_STAR_LOOKAHEAD_CANCEL)` instead of slicing. Keep the same obstacle checks, blocked-index trimming, short-path invalidation, and returned move action. |
| Completion surface | Touch only `navigation.py` cached-path validation and focused runtime-substrate tests. No A* scoring, planner state, bugnav fallback, movement action order, marker protocol, perception, mode transitions, or direct-core routing changes. |
| Invariants to check | Existing cached paths remain accepted/rejected on the same simulated endpoint keys. The target tile remains allowed even if present in known/temporary obstacles. Blocked paths still trim at the same `blocked_index`; short non-assault paths still clear when their endpoint is not the target; bridge actions still jump to their stored landing position. |
| Time-risk check | Removes one list slice and up to five temporary `Position` allocations per cached-path validation, plus up to two short-path endpoint `Position.add()` allocations. Adds only tuple/int arithmetic and cached direction delta lookups. No loops grow; bounds remain `A_STAR_LOOKAHEAD_CANCEL`. |
| Execution model | Pure private per-unit computation plus immutable module constants. No shared mutable coordination state and no non-marker communication. |
| Code changed | Added `_DIRECTION_DELTAS` beside the existing precomputed navigation deltas. Reworked cached-path lookahead validation to iterate `range(min(len(path), A_STAR_LOOKAHEAD_CANCEL))` and simulate `(sim_x, sim_y)` directly. Reworked the short-path endpoint check to use the same tuple simulation. |
| Tests | Added `test_compute_pathfinding_step_validates_cached_path_without_slicing()` with a list subclass that raises on slicing, and `test_compute_pathfinding_step_tuple_simulation_trims_after_bridge()` to verify bridge landing plus later blocked-conveyor trimming. Existing cache-hit and temp-obstacle expiry tests remain in the focused set. |
| Pre-smoke bug audit | Rechecked target-change invalidation, temporary obstacle expiry, lookahead blocked-index trimming, target-tile exception, bridge landing simulation, and short-path endpoint invalidation. `_DIRECTION_DELTAS` is immutable module data and all action paths still use the same stored `Direction` or bridge `Position`. No introduced bug found. Residual risk is only tiny timing perturbation changing anytime planner outcomes later in the turn. |
| Cheap validation | `py_compile navigation.py` passed; focused cached-path tests passed (`4 passed, 250 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) lost by titanium tiebreak at turn `2000`: got-any-grapes delivered/mined `54,430` Ti, final stored `33,607`, `20` units, `520` buildings; `jon-6` delivered/mined `87,350` Ti, final stored `62,633`, `5` units, `585` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch26_cached_path_tuple_settlement.json`: active source ports `3`, source top1 share `35.1%`, top3 share `100%`, builder max small-loop streak `320`, no-progress streak `29`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; local timing fields remain all zero/untrustworthy. This trails Batch9 same-seed smoke (`63,580` delivered, `4` active source ports), but is not a crash or route-collapse symptom, so g16 is needed before deciding. |
| In-g16 no-edit audit | While g16 was running, rechecked `_DIRECTION_DELTAS`, cached-path lookahead validation, short-path endpoint validation, and grep-confirmed the removed `state["path"][:A_STAR_LOOKAHEAD_CANCEL]` slice no longer exists. Conveyor simulation uses the same direction deltas as the existing A* tables; bridge simulation uses the stored landing `Position`. No introduced bug found so far. |
| g16 report | `.dist/reports/got-any-grapes_batch26_cached_path_tuple_g16_20260417.json` |
| g16 aggregate | `29-19` (`60.4%`), avg TiEq `34,489.6`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `12-4`, avg TiEq `49,431.9`, worst `90`; seat split AB `5-3` avg `55,892.5`, BA `7-1` avg `42,971.2`. |
| `jon-6-a9bfs-surround` | `7-9`, avg TiEq `18,465.0`, worst `220`; seat split AB `3-5` avg `13,150.0`, BA `4-4` avg `23,780.0`. |
| `leeroy-jonkins` | `10-6`, avg TiEq `35,571.9`, worst `0`; seat split AB `4-4` avg `36,002.5`, BA `6-2` avg `35,141.2`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `48/48`, and `core_port_concentration` `39/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-5` wins, `-8,724.4` avg TiEq, and `-740` worst TiEq. `jon-6` was `+1` win and `+1,777.5` avg TiEq but `-3,900` worst TiEq; `a9` was `-4` wins, `-12,788.1` avg TiEq, and `-520` worst TiEq; `leeroy` was `-2` wins, `-15,162.5` avg TiEq, and `-1,320` worst TiEq. |
| Decision | Revert and do not remote-test. The change was intended as behavior-preserving allocation cleanup, but the g16 result shows real timing-induced behavior drift with large pressure-matchup regressions. This is not a candidate for remote timing validation. |
| Revert validation | Removed `_DIRECTION_DELTAS`, restored cached-path validation slicing and `Position.add()` simulation, and removed the two Batch26 tests. `py_compile navigation.py` passed; focused cached-path tests returned to `2 passed, 250 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; exact stale-symbol search for Batch26 names returned no matches. |
| Next target | Avoid navigation allocation rewrites that perturb `time.time_ns()` budget boundaries without strong local equivalence evidence. Next ROI should either fix a concrete failure signal or reduce remote timing in a way that does not change local decision timing enough to affect A* expansion outcomes. |

#### Batch 24: full-perception hostile turret danger parity

| Item | Finding |
| --- | --- |
| ROI target | Survive no-TLE offensive opponents and reduce early wreckage. Live fast perception already treats visible enemy sentinels/gunners as temporary 3x3 danger obstacles for economy builders, but full perception only records them as visible enemies. Economy builders on a full-scan turn can therefore path into a visible turret's immediate fire zone. |
| Code changed | Added `_DANGER_TURRET_TYPES`, `_DANGER_TTL`, and `_mark_hostile_turret_danger()`. Replaced the fast-path inline danger loop with the helper and called the same helper from `_infer_state_from_grid()` after hostile turret inference. |
| Completion surface | Touched only `perception.py` inference and focused tests. No marker protocols, pathfinding planner scoring, direct-core routing, role transitions, spawn policy, or assault targeting changed. This intentionally preserves the existing 3x3 danger shape rather than expanding to directional sentinel range. |
| Invariants checked | Economy builders mark `(x-1..x+1, y-1..y+1)` temporary obstacles until `round + 8` for visible hostile sentinel/gunner. Assault builders skip danger marking as before so offensive approaches are not disabled. Existing obstacle classification and `visible_enemy_targets` population remain unchanged. Full and fast perception now share the same helper. |
| Edge cases checked | Missing `temporary_obstacles` is handled with `setdefault`; existing later expiry is preserved with `max`; out-of-bounds keys can be written exactly as the old fast path did and are later ignored by pathfinding bounds checks; enemy cores/harvesters/conveyors do not trigger turret danger. |
| Time-risk check | Adds only a membership check for each visible hostile and nine dictionary writes per visible hostile sentinel/gunner. No SDK calls, no A*, no map-wide scans, and no work on quiet economic maps. |
| Execution model | Pure private per-builder `pathfinding_state["temporary_obstacles"]`; no shared mutable state and no non-marker communication. |
| Tests | Added `test_full_perception_marks_enemy_turret_danger_for_economy_builders()` and `test_full_perception_does_not_mark_enemy_turret_danger_for_assault_builders()`. Existing fast-perception tests still cover fast path behavior. |
| Cheap validation | `py_compile perception.py` passed; focused perception tests passed (`12 passed, 242 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Rechecked `_infer_from_grid_fast()`, `_infer_state_from_grid()`, helper TTL semantics, assault-role guard, temp-obstacle state lifetime, and visible-enemy target population. No introduced bug found. Main residual risk is economy builders pathing around a friendly/safe tile adjacent to a turret that they could have safely crossed, but this matches the already-live fast perception behavior. |
| In-g16 no-edit audit | While g16 was running, rechecked both helper call sites, helper body, focused test fixture, and temp-obstacle consumers. `_mark_hostile_turret_danger()` is reached only after hostile inference in both fast and full perception, preserves the old fast-path `round + 8` TTL and `max()` expiry behavior, and keeps the `is_assault_role` exemption. The full-path call is after harvester/core/visible-target bookkeeping and before connected-topology logic, so it does not alter hostile classification or friendly logistics inference. Navigation expires entries at `expiry <= current_round`, and existing build-failure/small-loop recovery paths clear `temporary_obstacles`, so this does not add a new persistence channel. No introduced bug found so far. |
| Local smoke | Same-seed `settlement`/`jon-6-a9bfs-surround` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) lost by titanium tiebreak at turn `2000`: got-any-grapes delivered/mined `43,000` Ti, final stored `9,290`, `16` units, `470` buildings; a9 delivered/mined `56,380` Ti, final stored `68`, `9` units, `331` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch24_full_turret_danger_a9_settlement.json`: active source ports `3`, source top1 share `44.7%`, top3 share `100%`, builder max small-loop streak `510`, no-progress streak `34`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; local timing fields remain all zero/untrustworthy. This is not a positive smoke, but it is not an obvious crash or zero-economy collapse. |
| Next validation | Completed by g16; no remote validation because the batch failed local cross-opponent evidence. |
| g16 report | `.dist/reports/got-any-grapes_batch24_full_turret_danger_g16_20260417.json` |
| g16 aggregate | `29-19` (`60.4%`), avg TiEq `36,119.8`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `10-6`, avg TiEq `40,226.9`, worst `5,010`; seat split AB `5-3` avg `44,211.2`, BA `5-3` avg `36,242.5`. |
| `jon-6-a9bfs-surround` | `11-5`, avg TiEq `35,246.2`, worst `590`; seat split AB `6-2` avg `29,260.0`, BA `5-3` avg `41,232.5`. |
| `leeroy-jonkins` | `8-8`, avg TiEq `32,886.2`, worst `0`; seat split AB `4-4` avg `37,252.5`, BA `4-4` avg `28,520.0`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `48/48`, and `core_port_concentration` `36/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-5` wins, `-7,094.2` avg TiEq, and `-740` worst TiEq. `jon-6` was `-1` win and `-7,427.5` avg TiEq but `+1,020` worst TiEq; `a9` was `0` wins and `+3,993.1` avg TiEq but `-150` worst TiEq; `leeroy` was `-4` wins, `-17,848.1` avg TiEq, and `-1,320` worst TiEq. |
| Decision | Revert and do not remote-test. The mechanism is defensible and cheap, but adding full-scan turret danger changes path invalidation near pressure in a behavior-sensitive way and materially weakens `leeroy`. Remote r2 would be validation of a known-bad candidate rather than timing truth for a viable batch. |
| Revert validation | Removed `_DANGER_TURRET_TYPES`, `_DANGER_TTL`, `_mark_hostile_turret_danger()`, the full-scan helper call, and the two Batch24 tests; restored the fast-path inline danger loop. `py_compile perception.py` passed; focused perception tests passed (`10 passed, 242 deselected`); full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; stale-symbol search found Batch24 helper/test names only in STATUS history. |
| Next target | Full-scan turret-danger parity should not be retried without replay evidence that the extra obstacle invalidations improve survival more than they damage `leeroy` pathing. Next ROI should focus on a runtime hot path or first-class no-progress/travel-without-build failure with stronger behavior-preservation guardrails. |

#### Batch 25: TILING_BACK buildability check reuse

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety cleanup in `mode_tiling_back._navigate_and_build()`, a live hot path on route-building turns. Current code asks `ct.can_build_conveyor()` twice on normal current-tile builds and twice again for normal lookahead conveyor builds; bridge lookahead has the same duplicate positive check. On remote, these SDK calls sit inside builder turns that already show high `% >1ms`/TLE pressure. |
| Planned code change | Cache the first positive current-tile `can_build_conveyor(current_pos, move_dir)` result and reuse it for the actual build. Cache lookahead `can_build_conveyor(next_pos, next_dir)` and `can_build_bridge(next_pos, jump_target)` similarly. If the first check is false, preserve old behavior by calling `_clear_obstacles_for_conveyor()` and then rechecking before a build. |
| Completion surface | Touched only `_navigate_and_build()` and focused runtime-substrate tests. No A* scoring, path order, mode transitions, marker protocol, direct-core routing, perception, or shared state changes. |
| Invariants to check | Positive buildability results are reused only within the same turn before any clearing action. False results still run the old clear-and-recheck flow. Protected pipeline preservation, pending-build fallback, move execution, and path popping stay unchanged. |
| Code changed | In `_navigate_and_build()`, introduced `current_can_build`, `next_can_build_conveyor`, and `next_can_build_bridge` local booleans. Current-tile conveyor builds now reuse the first successful `can_build_conveyor()` result; false results still call `_clear_obstacles_for_conveyor()` and recheck. Lookahead conveyor/bridge builds do the same for `can_build_conveyor()` and `can_build_bridge()`. |
| Pre-benchmark bug audit | Rechecked the current-tile conveyor branch, protected-pipeline branch, lookahead conveyor branch, lookahead bridge branch, and move/path-pop tail. Positive results are reused only before any state-changing clear/build for that tile; false results still clear and recheck; protected tiles still skip build attempts; pending-build fallback remains tied to current tile only; lookahead remains skipped under the existing timing gate. No introduced bug found. |
| Edge cases checked | Current tile protected but mismatched; current tile buildable; current tile blocked then clearable; lookahead protected/matching; lookahead protected/mismatched; lookahead conveyor buildable; lookahead bridge buildable; no lookahead path; lookahead skipped by timing governor. Bridge target argument remains the original target `Position`, not a direction. |
| Time-risk check | Removes duplicate SDK `can_build_*` calls on the common buildable path; adds only local booleans. No loops, scans, markers, A*, or persistent state added. |
| Execution model | Pure private per-unit local variables; no shared Python coordination and no communication changes. |
| Tests | Added `test_tiling_back_reuses_positive_conveyor_buildability_checks()` and `test_tiling_back_reuses_positive_lookahead_bridge_buildability_check()` to count controller buildability probes and enforce one positive probe per buildable current/lookahead tile. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_tiling_back.py` passed; focused TILING_BACK tests passed (`10 passed, 244 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by enemy core destruction on turn `735`: got-any-grapes delivered/mined `16,570` Ti, final stored `1,788`, `16` builder bots alive, `405` buildings; `jon-6` delivered/mined `25,160` Ti, final stored `3,645`, `11` builder bots alive, `532` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch25_buildability_reuse_settlement.json`: active source ports `3`, source top1 share `39.0%`, top3 share `100%`, builder max small-loop streak `206`, no-progress streak `18`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; local timing fields remain all zero/untrustworthy. The batch passes smoke because it core-killed early with no crash or route-collapse symptom. |
| In-g16 no-edit audit | While g16 was running, rechecked `_navigate_and_build()` current-tile build, protected-pipeline skip, lookahead conveyor, lookahead bridge, and the two new count-based tests. Remaining duplicate `can_build_*` calls are either the deliberate false-path recheck after `_clear_obstacles_for_conveyor()` or separate route/axionite sites outside this batch. No code bug found so far. |
| g16 report | `.dist/reports/got-any-grapes_batch25_buildability_reuse_g16_20260417.json` |
| g16 aggregate | `29-19` (`60.4%`), avg TiEq `45,662.3`, worst TiEq `230`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `10-6`, avg TiEq `58,258.1`, worst `230`; seat split AB `5-3` avg `71,226.2`, BA `5-3` avg `45,290.0`. |
| `jon-6-a9bfs-surround` | `10-6`, avg TiEq `42,392.5`, worst `670`; seat split AB `6-2` avg `42,395.0`, BA `4-4` avg `42,390.0`. |
| `leeroy-jonkins` | `9-7`, avg TiEq `36,336.2`, worst `770`; seat split AB `3-5` avg `25,257.5`, BA `6-2` avg `47,415.0`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `47/48`, and `core_port_concentration` `39/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-5` wins, `+2,448.3` avg TiEq, and `-510` worst TiEq. `jon-6` was `-1` win and `+10,603.8` avg TiEq but `-3,760` worst TiEq; `a9` was `-1` win and `+11,139.4` avg TiEq but `-70` worst TiEq; `leeroy` was `-3` wins, `-14,398.1` avg TiEq, and `-550` worst TiEq. |
| Decision | Revert and do not remote-test. The mechanism is pure runtime cleanup, but the local behavior/TiEq evidence shows genuine cross-opponent detriment, especially in the pressure matchup. Because TiEq does not improve for every opponent and wins fall outside expected noise, remote r2 would validate a known-bad candidate rather than timing truth for a viable batch. |
| Revert validation | Restored the old duplicate positive `can_build_*` probes in `_navigate_and_build()`, removed the two Batch25 tests, and kept all pre-existing retained code unchanged. `py_compile mode_tiling_back.py` passed; focused TILING_BACK/clear-obstacle tests returned to `8 passed, 244 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; stale Batch25 symbol search found no code/test matches. |
| Next target | Continue with a stronger ROI. Prefer a bugfix or runtime reduction with behavior-preservation evidence that does not perturb TILING_BACK action sequencing, or a first-class small-loop/travel-without-build failure mechanism with a tighter guard. |

#### Batch 22: marker-scan time gate decoupled from connected refresh

| Item | Finding |
| --- | --- |
| ROI target | Remote-safety under Graviton-style time pressure. Current `scan_around()` uses one `PERCEPTION_OPTIONAL_NS` gate to skip both marker scanning and connected-conveyor refresh. Marker decoding can be expensive on marker-heavy games, but connected membership is macro-critical for TILING_BACK/defense. Decoupling lets moderate-pressure turns skip marker work earlier while preserving exact connected membership until the old tighter reserve. |
| Code changed | Added `timing.MARKER_SCAN_RESERVE_NS = 1_100_000`. Full and fast perception now compute `marker_time_pressured` from that reserve and `connected_time_pressured` from the old `PERCEPTION_OPTIONAL_NS = 700_000`. Marker scanning skips at the earlier reserve; full-scan `_infer_state_from_grid(... refresh_connected=...)` still refreshes connected topology unless the old tighter connected reserve is breached. |
| Completion surface | Touched `timing.py`, `perception.scan_around()`, `_scan_local_fast()` marker gate, and focused tests. No pathfinding, target selection, spawn policy, marker encoding/decoding semantics, direct-core routing, assault scoring, or connected-load algorithm changed. |
| Invariants checked | With no governor or ample budget, old behavior is unchanged. Under moderate pressure, only marker decoding is skipped; grid update, stale unit clearing, enemy inference, and connected refresh still run. Under tighter pressure, connected refresh skips exactly as before. Assault-mode connected refresh remains disabled. |
| Edge cases checked | Full scan marker skip with connected refresh enabled; full scan marker skip with connected refresh disabled; timing governor budget checks at both reserves. Fast scan uses the same marker reserve but does not perform connected refresh in either old or new behavior. |
| Time-risk check | Adds two `has_budget_for()` checks in perception hot paths, but can avoid marker loops and `get_marker_value()` calls earlier on slow turns. Local fast hardware should remain behavior-identical because the reserve is only triggered by elapsed wall time. This is aimed at remote TLE reduction rather than local g16 performance. |
| Execution model | Pure per-unit timing gate; no shared mutable state, fake manager, or non-marker communication. Marker communication semantics stay unchanged when markers are scanned. |
| Tests | Added `test_full_scan_can_skip_markers_while_refreshing_connected()` and `test_full_scan_skips_connected_refresh_when_tighter_on_time()`. Updated timing-governor reserve coverage. |
| Cheap validation | `py_compile timing.py perception.py` passed; focused timing/perception tests passed (`4 passed, 250 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by enemy core destruction on turn `982`: got-any-grapes delivered/mined `25,310` Ti, final stored `6,052`, `17` units, `458` buildings; `jon-6` delivered/mined `37,400` Ti, final stored `12`, `11` units, `709` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch22_marker_gate_settlement.json`: got-any-grapes active source ports `4`, source top1 share `35.4%`, top3 share `98.1%`, builder max small-loop streak `339`, no-progress streak `18`, zero-flow tiles `175`, orphan tiles `71`, dead ends `3`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`. This is not behavior-identical locally, but it is a positive smoke with no route-collapse symptom. |
| Pre-g16 bug audit | Rechecked the gate split in full and fast perception, timing constants, and tests. Invariants: ample-budget behavior unchanged; moderate pressure skips only marker decoding; connected refresh remains governed by the old `700k` reserve; assault connected refresh stays disabled; fast scans never performed connected refresh before and still do not. Edge cases: no governor, moderate governor, tight governor, marker skip counters, and connected-refresh bool. No new bug found. |
| In-g16 no-edit audit | While the g16 was running, rechecked all references to `MARKER_SCAN_RESERVE_NS`, `PERCEPTION_OPTIONAL_NS`, marker skip profile counters, and connected refresh callers. The only issue found so far is a stale `_scan_nearby_markers()` comment that still describes the outer gate as `PERCEPTION_OPTIONAL_NS`; runtime code is correct and should be cleaned only after the evaluation stops. Marker-scan skip still preserves previous marker-derived claim caches when `_scan_nearby_markers()` is not entered, matching the old skip behavior but making that stale-cache risk more common under Batch 22. This is a behavioral risk to inspect in g16/remote evidence, not an immediate correctness bug. Execution model remains legal: no shared coordination state and marker communication semantics unchanged when marker scans run. |
| g16 report | `.dist/reports/got-any-grapes_batch22_marker_gate_g16_20260417.json` |
| g16 aggregate | `26-22` (`54.2%`), avg TiEq `31,932.3`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `13-3`, avg TiEq `45,933.8`, worst `0`; seat split AB `6-2` avg `37,766.2`, BA `7-1` avg `54,101.2`. |
| `jon-6-a9bfs-surround` | `8-8`, avg TiEq `23,450.0`, worst `780`; seat split AB `5-3` avg `26,725.0`, BA `3-5` avg `20,175.0`. |
| `leeroy-jonkins` | `5-11`, avg TiEq `26,413.1`, worst `160`; seat split AB `2-6` avg `31,178.8`, BA `3-5` avg `21,647.5`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `48/48`, and `core_port_concentration` `39/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-8` wins, `-11,281.7` avg TiEq, and `-740` worst TiEq. `jon-6` was `+2` wins but `-1,720.6` avg TiEq and `-3,990` worst TiEq; `a9` was `-3` wins and `-7,803.1` avg TiEq; `leeroy` was `-7` wins and `-24,321.2` avg TiEq. |
| Decision | Revert and do not remote-test. The batch targeted remote timing, but local g16 showed a large strategic regression, especially in the two pressure matchups. The likely mechanism is stale or missing marker-derived deconfliction under earlier marker skips, plus small timing perturbations affecting local path choices. Remote r2 would be validation of a known-bad candidate rather than useful bug-finding. |
| Revert validation | Removed `MARKER_SCAN_RESERVE_NS`, restored the single `PERCEPTION_OPTIONAL_NS` marker/connected gate in full and fast perception, and removed the two Batch22 tests plus timing-reserve assertions. `py_compile timing.py perception.py` passed; focused timing/perception tests passed (`24 passed, 228 deselected`); full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; stale-symbol search found Batch22 names only in STATUS history. |
| Next target | Do not reattempt marker-scan/connected-refresh gate splitting without replay evidence that stale marker-derived claim caches are harmless or with a safer cache-age contract. Prefer next ROI on a hot-path change with behavior-preserving tests, or a first-class failure signal such as travel-without-build recovery. |

#### Batch 23: tuple-based assault opening escape

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction for remote safety. Opening escape is an early assault/rusher hot path that can run without perception and previously used two small BFS-style helpers with repeated `Position.add()` allocations and `_in_spawn_shell()` calls. This targets per-turn spikes without changing role policy or macro strategy. |
| Code changed | Added immutable `_DIRECTION_DELTAS`, `_in_spawn_shell_key()`, `_direction_toward_key()`, and `_opening_escape_direction_order_key()`. Reworked `_shell_exit_target()` and `_shell_escape_route()` to operate on tuple keys for shell checks, bounds checks, neighbor expansion, and direction sorting. Cached the team lookup once for local obstacle refresh. |
| Completion surface | Touched only opening-escape helper internals in `mode_assaulting.py` plus focused runtime-substrate tests. No changes to opening-escape activation, direct outward move preference, blocked-yield limit, route TTL/replan interval, role transitions, assault anchor selection, markers, perception, navigation policy outside this helper, or economy behavior. |
| Invariants checked | BFS direction iteration still follows `utils.DIRECTIONS` order through `_DIRECTION_DELTAS`. `_direction_toward_key()` mirrors `utils.direction_toward()` tie behavior by iterating the same direction order. First-step `ct.can_move(direction)` is still enforced only from the current tile. Route reconstruction still uses `navigation._reconstruct_assault_path()`. Fallback target is still `core_pos + outward * (shell radius + 1)` clamped to map bounds. |
| Edge cases checked | Missing core/outward vector returns `None` as before. Cached bootstrap route validation still uses the old public shell check. Map-edge bounds are checked by tuple coordinates in `_shell_exit_target()` and by existing `_assault_is_walkable_key()` in route BFS. The start tile is not accepted as an exit even if route state is malformed. |
| Time-risk check | Replaces per-node `Position(...)`, per-neighbor `current.add(direction)`, repeated `direction.delta()` in sort keys, and repeated `_in_spawn_shell()` calls with tuple arithmetic. Work remains bounded by `SHELL_BFS_MAX_TILES = 49`; no SDK-heavy calls, A*, marker scans, or unbounded loops added. |
| Execution model | Pure private per-builder computation. Added only immutable module constants/helpers; no shared mutable coordination state and no non-marker communication. |
| Tests | Added `test_shell_exit_target_uses_tuple_shell_check()` and `test_shell_escape_route_uses_tuple_shell_checks()`, which monkeypatch the old `Position`-based shell check to fail if the optimized helpers regress to it. |
| Cheap validation | `py_compile mode_assaulting.py` passed; focused opening-shell tests passed (`4 passed, 250 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Pre-smoke bug audit | Rechecked route activation/caller flow in `builder_bot.run()`, `_execute_opening_escape()`, `_opening_escape_step()`, `_shell_exit_target()`, `_opening_escape_direction_order_key()`, and `_shell_escape_route()`. No introduced bug found. Main residual risk is tiny timing/order perturbation from tuple implementation, but sorted keys intentionally preserve the old direction order and scoring tuple. |
| In-g16 no-edit audit | While g16 was running, compared `_direction_toward_key()` and `_opening_escape_direction_order_key()` against a reconstructed copy of the old `Position.add()` scoring across sampled shell positions, exit targets, and eight outward vectors. Result: `direction_mismatches 0`, `order_mismatches 0`. Also compared tuple `_shell_exit_target()` against a reconstructed old BFS over sampled map/core/start cases: `shell_exit_target_mismatches 0`. This supports behavior equivalence for target and direction ordering; the remaining behavioral risk is only object-allocation/timing perturbation changing later anytime path choices. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by titanium tiebreak at turn `2000`: got-any-grapes delivered/mined `68,420` Ti, final stored `26,251`, `34` units, `751` buildings; `jon-6` delivered/mined `65,620` Ti, final stored `8,250`, `0` units, `476` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch23_opening_escape_tuple_settlement.json`: active source ports `4`, source top1 share `28.0%`, top3 share `80.9%`, builder max small-loop streak `471`, no-progress streak `18`, failure signals `small_loop`, `low_builder_progress`, and `travel_without_build`; local timing fields remain all zero and are not timing evidence. No route-collapse symptom appeared. |
| g16 report | `.dist/reports/got-any-grapes_batch23_opening_escape_tuple_g16_20260417.json` |
| g16 aggregate | `25-23` (`52.1%`), avg TiEq `37,279.6`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `12-4`, avg TiEq `64,442.5`, worst `0`; seat split AB `6-2` avg `59,403.8`, BA `6-2` avg `69,481.2`. |
| `jon-6-a9bfs-surround` | `7-9`, avg TiEq `19,765.6`, worst `790`; seat split AB `5-3` avg `18,965.0`, BA `2-6` avg `20,566.2`. |
| `leeroy-jonkins` | `6-10`, avg TiEq `27,630.6`, worst `1,470`; seat split AB `2-6` avg `25,493.8`, BA `4-4` avg `29,767.5`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `48/48`, and `core_port_concentration` `41/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-9` wins, `-5,934.4` avg TiEq, and `-740` worst TiEq. `jon-6` was `+1` win and `+16,788.1` avg TiEq but `-3,990` worst TiEq; `a9` was `-4` wins and `-11,487.5` avg TiEq; `leeroy` was `-6` wins and `-23,103.8` avg TiEq. |
| Decision | Revert and do not remote-test. The no-edit audits supported helper-level equivalence, but the local g16 shows a large pressure-matchup regression and no trustworthy local timing proof. Mechanistically, changing object allocation/timing inside an anytime-sensitive opening path can perturb later path choices enough to harm macro outcomes. |
| Revert validation | Removed `_DIRECTION_DELTAS`, tuple shell helpers, route rewrites, and two Batch23 tests. `py_compile mode_assaulting.py` passed; focused opening-shell tests returned to `2 passed, 250 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; stale-symbol search found Batch23 helper/test names only in STATUS history. |
| Next target | Do not reattempt opening-escape tuple refactors without a way to prove timing perturbation does not change macro paths. Prefer next ROI on a state-machine correctness fix for persistent failure signals or a runtime guard that reduces work only in genuinely optional branches. |

#### Batch 21: ore friend-claim lower-bound skip

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction inside `mode_finding_ore` target deconfliction while preserving per-turn ore re-ranking. Batch 20 showed target stickiness hurts pressure responsiveness, so this batch keeps full `_find_best_ore_target()` selection semantics and skips only exact access-resolution work that a geometric lower bound proves cannot affect the claim decision. |
| Code changed | Added `_min_access_distance_sq_from_tuple(ore_pos, pos_tuple)`. `_is_ore_claimed_by_friend()` now skips a friendly builder when its closest possible cardinal access tile is farther than our exact access distance, or equal but the friend loses the existing tuple tiebreak. `_find_best_ore_target_euclidean()` applies the analogous `>= d` skip because that fallback only treats strictly closer friends as claimed. |
| Completion surface | Touched only ore-target friend-claim/deconfliction. BFS ordering, Euclidean candidate ordering, access-cache lifetime, ore blacklists, build-failure handling, TILING_BACK entry, markers, pathfinding, perception, direct-core routing, and role transitions remain unchanged. |
| Invariants checked | The lower bound ignores obstacles and therefore can only under-approximate the exact valid-access distance. If the bound cannot beat/tie the current builder, no valid access tile can claim; if it can, the old `_cached_access_point()` exact path still runs. Self-position handling is preserved. Euclidean fallback still uses the old strict-closer rule without adding tie claims. |
| Edge cases checked | Far friends do not resolve exact access; equal-distance friends that win the existing tuple tie still resolve and claim; far friends in Euclidean fallback do not resolve; absent/blocked access still flows through `_cached_access_point()` when the bound allows a possible claim. |
| Time-risk check | Adds four integer squared-distance expressions per visible friendly builder before the expensive access helper. On skipped friends it avoids `Position` allocation plus `closest_non_obstacle_cardinal_point_on_grid()` and its map/grid checks. No SDK calls, A*, perception scans, markers, or persistent state are added. |
| Execution model | Pure local computation over private per-builder perception state. No shared mutable state, fake manager, or non-marker communication. |
| Tests | Added far-friend skip, equal-distance tiebreak preservation, and Euclidean far-friend skip tests. Existing ore access-cache/BFS tests still pass. |
| Cheap validation | `py_compile mode_finding_ore.py` passed; focused ore deconfliction tests passed (`6 passed, 249 deselected`); full runtime substrate passed (`255 passed`); touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) lost by titanium tiebreak at turn `2000`: got-any-grapes delivered/mined `55,420` Ti, final stored `21,239`, `27` units, `621` buildings; `jon-6` delivered/mined `61,710` Ti, final stored `55`, `9` units, `528` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch21_friend_bound_settlement.json`: got-any-grapes active source ports `3`, source top1 share `34.6%`, top3 share `100%`, builder max small-loop streak `906`, no-progress streak `18`, zero-flow tiles `230`, orphan tiles `88`, dead ends `1`, failure signals `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`. This is weaker than Batch9 smoke on delivered Ti and source spread, but not a crash or route-collapse class failure. |
| Pre-g16 bug audit | Rechecked the lower-bound math, Euclidean strict-closer rule, `_is_ore_claimed_by_friend()` tie handling, cache lifetime, and tests. Invariants: bound ignores obstacles so it can only be less than or equal to exact valid-access distance; exact access still runs whenever a friend could beat/tie; self skip remains first; no role/mode/path/marker state changes. Edge cases: far friend skip, equal-distance tie winner, Euclidean far friend, blocked access. Time risk is bounded integer math before skipping access helper calls. Execution model remains private state only. No new bug found. |
| g16 report | `.dist/reports/got-any-grapes_batch21_friend_bound_g16_20260417.json` |
| g16 aggregate | `30-18` (`62.5%`), avg TiEq `40,692.9`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `10-6`, avg TiEq `51,500.0`, worst `0`; seat split AB `5-3` avg `52,237.5`, BA `5-3` avg `50,762.5`. |
| `jon-6-a9bfs-surround` | `10-6`, avg TiEq `37,196.2`, worst `1,720`; seat split AB `6-2` avg `40,223.8`, BA `4-4` avg `34,168.8`. |
| `leeroy-jonkins` | `10-6`, avg TiEq `33,382.5`, worst `3,030`; seat split AB `4-4` avg `31,136.2`, BA `6-2` avg `35,628.8`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `48/48`, and `core_port_concentration` `39/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-4` wins and `-2,521.0` avg TiEq. `jon-6` was `-1` win but `+3,845.6` avg TiEq; `a9` was `-1` win but `+5,943.1` avg TiEq; `leeroy` was `-2` wins and `-17,351.9` avg TiEq. Worst TiEq dropped by `740` overall. |
| Decision | Revert and do not remote-test. Mechanistically the skip should preserve exact friend-claim semantics, but the timing/order perturbation materially weakens the `leeroy` stress matchup and does not clear the win/TiEq gate. Without trustworthy local timing or a positive cross-opponent TiEq result, remote validation would be premature. |
| Revert validation | Removed `_min_access_distance_sq_from_tuple()`, both lower-bound guard sites, and three Batch21 tests. `py_compile mode_finding_ore.py` passed; focused ore tests returned to `3 passed, 249 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; search found no stale Batch21 helper/test symbols in bot/tests. |
| Next target | Avoid deconfliction-order micro-optimizations unless remote timing proof is available. Prefer a runtime ROI with explicit time gates or one that reduces work only after preserving macro-critical path outcomes in smoke, such as bounded optional marker/topology work or a defense/economy correctness fix with strong replay mechanism. |

#### Batch 20: guarded current ore-target reuse

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic/algorithmic runtime reduction in `FINDING_ORE`. Debug profile rows show hot `FINDING_ORE` turns averaging `~1000us` in mode code while nav/perception slices are much smaller. Live code recomputes `_find_best_ore_target()` every turn even when `ore_target_state` already points at the same ore/access pair and the builder is still moving toward it. |
| Code changed | Added `_state_position()` and `_active_ore_target_from_state()` in `mode_finding_ore.py`. `execute()` now tries the active cached ore/access target first, and falls back to full `_find_best_ore_target()` only if the cached target is absent or invalid. |
| Validity guards | Cached target must have ore/access positions, access must be cardinal-adjacent to ore, ore must still be eligible and not temporarily blocked/blacklisted, ore must not be in `claimed_harvesters`, defender leash must allow the access tile, access tile must not be visible ore/wall, ore must not already have adjacent connected friendly transport, and friend-claim deconfliction must still pass for this one ore. |
| Completion surface | Touched only `mode_finding_ore.execute()` target selection and helper logic. Build-harvester, existing-harvester handling, build-failure blacklists, progress blacklists, TILING_BACK entry, exploration fallback, navigation, roads, assault, markers, and direct-core routing remain unchanged. |
| Invariants checked | If the cached target fails any guard, old full BFS/Euclidean selection runs. Successful movement still calls `_note_ore_target_progress()` and keeps state fresh. Stalls/build failures still clear or blacklist the target through existing paths. No target is shared across units except existing marker behavior. |
| Edge cases checked | Tuple and `Position` state values are accepted. Malformed/absent state returns `None`. Connected ore invalidates the cache. Defender out-of-leash access invalidates via existing helper. A friend-claimed ore invalidates via existing `_is_ore_claimed_by_friend()` for just this ore. |
| Time-risk check | Replaces a full bounded BFS/ore scan with a small set of O(1)/single-ore checks on continuing-to-target turns. It still calls `get_eligible_ore_locations()` and one friend-claim check, so it avoids stale strategy while bounding work. No new SDK-heavy loops or A* calls. |
| Execution model | Uses private per-builder `ore_target_state`; no shared mutable state, fake manager, or non-marker communication. |
| Tests | Added `test_active_ore_target_from_state_reuses_valid_target` and `test_active_ore_target_from_state_rejects_connected_ore`. Existing BFS/access-cache tests still pass. |
| Cheap validation | `py_compile mode_finding_ore.py` passed; focused ore target tests passed (`5 passed, 249 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) won by titanium tiebreak at turn `2000`: got-any-grapes delivered/mined `76,900` Ti, final stored `35,146`, `16` units, `783` buildings; `jon-6` delivered/mined `53,930` Ti, final stored `44,891`, `2` units, `368` buildings. |
| Smoke diagnostics | Replay analysis `.dist/replay_analysis/got-any-grapes_batch20_ore_target_cache_settlement.json`: got-any-grapes active source ports `5`, source top1 share `24.9%`, top3 share `68.8%`, builder max small-loop streak `422`, no-progress streak `18`, zero-flow tiles `246`, orphan tiles `97`, dead ends `3`, failure signals `small_loop`, `low_builder_progress`, and `travel_without_build`. |
| Pre-g16 bug audit | Rechecked `_active_ore_target_from_state()`, its caller in `execute()`, and focused tests. Invariants: malformed or stale private `ore_target_state` falls back to full selection; access must remain adjacent/standable/serviceable; connected ore and friend-claimed ore invalidate; existing build-failure/stall/blacklist/TILING_BACK transitions remain unchanged. Edge cases: tuple and `Position` state, absent state, connected ore, defender leash, visible blocked access, existing harvester, and friend claim. Time risk remains bounded to single-target checks plus existing eligibility set construction; no A*, loops over all friends beyond the existing friend-claim helper, or extra marker protocols added. No new bug found. |
| g16 report | `.dist/reports/got-any-grapes_batch20_ore_target_cache_g16_20260417.json` |
| g16 aggregate | `31-17` (`64.6%`), avg TiEq `39,174.4`, worst TiEq `170`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `11-5`, avg TiEq `49,346.9`, worst `9,300`; seat split AB `4-4` avg `41,898.8`, BA `7-1` avg `56,795.0`. |
| `jon-6-a9bfs-surround` | `9-7`, avg TiEq `28,445.6`, worst `580`; seat split AB `5-3` avg `24,163.8`, BA `4-4` avg `32,727.5`. |
| `leeroy-jonkins` | `11-5`, avg TiEq `39,730.6`, worst `170`; seat split AB `4-4` avg `32,281.2`, BA `7-1` avg `47,180.0`. |
| Timing pressure | Local replay timing remains all zero: builder `>0.5ms`, `>1ms`, `>1.5ms`, `>2ms` all `0.0%`; TLE turns `0`. This is not trustworthy remote-safety evidence. |
| Loop/no-progress signals | Failure signals matched Batch 9 aggregate: `small_loop` `48/48`, `low_builder_progress` `48/48`, `travel_without_build` `47/48`, and `core_port_concentration` `36/48`. Candidate small-loop games were `16/16` for every opponent. |
| Batch9 comparison | Same g16 shape vs kept Batch 9: aggregate `-3` wins and `-4,039.6` avg TiEq. `jon-6` was equal on wins and `+1,692.5` avg TiEq, but `a9` was `-2` wins/`-2,807.5` avg TiEq and `leeroy` was `-1` win/`-11,003.8` avg TiEq. Worst TiEq dropped by `570` overall. |
| Decision | Revert and do not remote-test. The same-seed smoke was promising, but g16 shows genuine cross-matchup detriment rather than noise: the batch did not improve TiEq for every opponent, weakened both pressure matchups, and provided no trustworthy local timing proof. Mechanistically, the likely issue is target stickiness: builders keep a still-valid older ore/access target instead of re-ranking newly discovered targets each turn, reducing map/pressure responsiveness. |
| Revert validation | Removed `_state_position()`, `_active_ore_target_from_state()`, the `execute()` cached-target call, and the two Batch20 tests. `py_compile mode_finding_ore.py` passed; focused ore tests returned to `3 passed, 249 deselected`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; search found no stale Batch20 helper/profile/test symbols in bot/tests. |
| Next target | Look for runtime savings that preserve target re-ranking semantics, likely inside `_find_best_ore_target()` itself, visibility/perception SDK call count, or bounded route construction. Do not reintroduce current-target stickiness without stronger evidence and a guard that periodically re-ranks new ore discoveries. |

#### Batch 19: road build before marker lookup

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction in movement road prep without removing required roads. Batch 18 proved economy builders need roads for movement, but the old road path still paid `get_tile_building_id()`/`get_entity_type()` through `destroy_marker_if_present()` before every road build attempt. On the common empty buildable tile, `can_build_road()` can succeed without marker lookup. |
| Code changed | Added `utils.build_road_or_clear_marker(ct, pos)`. It first tries `ct.can_build_road(pos)`/`ct.build_road(pos)`. Only when that fails does it call `destroy_marker_if_present()`, then retries `can_build_road()` after a marker clear. Replaced the three existing road-prep sequences in `navigation.try_pathfinding_move()`, `navigation._execute_assault_move()`, and `mode_tiling_back` bridge transit with the helper. |
| Completion surface | Inspected all live `destroy_marker_if_present(ct, next_pos)` plus `can_build_road(next_pos)` call sites. The helper is wired into ordinary pathfinding moves, assault movement with `build_road=True`, and bridge-transit road prep. No pathfinding, route scoring, marker encoding, spawning, ore selection, or direct-core routing changed. |
| Invariants checked | Buildable empty tiles still get roads before movement; marker-blocked tiles still clear the marker and then build a road; non-buildable/non-marker tiles still do nothing; TILING_BACK normal route construction remains outside this helper except the existing bridge-transit road-prep path; movement legality remains controlled by `ct.can_move()`. |
| Edge cases checked | If `can_build_road()` is true, marker lookup is skipped. If a marker blocks road construction, first `can_build_road()` is false, marker is destroyed when legal, and road construction is retried. If marker destruction fails, no build is attempted after it. Existing assault `build_road=False` calls still skip road prep. |
| Time-risk check | Common new-road move saves one `get_tile_building_id()` and often one `get_entity_type()` SDK call. Marker tiles add one extra `can_build_road()` probe before marker lookup, but marker-blocked road moves should be rare relative to empty-road construction. No loops, scans, A*, persistent state, or marker protocols were added. |
| Execution model | Helper is pure per-turn action sequencing through the local controller. No shared mutable state, fake manager, or non-marker communication added. |
| Tests | Added `test_build_road_or_clear_marker_skips_marker_lookup_when_road_buildable` and `test_build_road_or_clear_marker_clears_marker_then_builds`. |
| Cheap validation | `py_compile utils.py navigation.py mode_tiling_back.py` passed; focused road-helper/opening movement tests passed (`3 passed, 251 deselected`); full runtime substrate passed (`254 passed`); touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` smoke lost by titanium tiebreak: got-any-grapes delivered/mined `55,180` Ti, final stored `37,768`, `17` units, `397` buildings; `jon-6` delivered/mined `68,970`, final stored `48,301`, `11` units, `597` buildings. This trails the guard-only smoke (`55,710` vs `53,290` win) and shows reduced source spread. |
| Smoke diagnostics | got-any-grapes active source ports `3`, top1 source share `34.7%`, top3 source share `100%`, zero-flow tiles `181`, orphan tiles `68`, dead ends `2`, builder max small-loop streak `320`. Replay analysis: `.dist/replay_analysis/got-any-grapes_batch19_road_first_settlement.json`. |
| Decision | Revert before g16. Even behavior-preserving-looking road action sequencing changes are too timing/macro sensitive; this variant worsened the cheap same-seed smoke and reduced active source-port diversity. |
| Revert validation | Removed `utils.build_road_or_clear_marker()`, restored all three original road-prep call sites, and removed Batch19 tests. `py_compile utils.py navigation.py mode_tiling_back.py` passed; focused opening movement selection passed (`1 passed`); full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; search found no Batch19 helper in bot/tests. |
| Next target | Avoid road-prep reordering. Look for runtime savings in read-only bookkeeping or pure Python allocation paths where action order and movement timing are less likely to affect macro. |

#### Batch 18: opening-shell empty-move guard, lazy-road attempt rejected

| Item | Finding |
| --- | --- |
| ROI target | Started as a mechanistic remote-safety reduction in ordinary economy movement. A deterministic debug-profile run on `settlement`/`jon-6`/seed `204011053` produced 1,833 `turn_profile` rows with `EXPLORING` avg `1083us`/`>1ms` `66.7%` and `FINDING_ORE` avg `979us`/`>1ms` `50.7%`, while many cached-path rows had low A*/perception slices. Smoke testing falsified the hard no-road premise and exposed a separate live crash in `_try_opening_shell_escape()`. |
| Code changed | Current kept code only adds `or not movable_directions` to `_try_opening_shell_escape()` before selecting `max(movable_directions)`. If an economy builder near the core has at least two adjacent friendly builders but zero legal escape moves, the fallback now returns `False` and lets the normal no-move path handle the turn instead of throwing `ValueError`. |
| Completion surface | `navigation.try_pathfinding_move()`, `navigation.move_towards()`, `mode_finding_ore.execute()`, `mode_exploring.execute()`, `mode_rush._move_towards()`, `mode_hijacking` movement, `mode_tiling_back` movement, and `navigation.assault_move_towards()` were inspected. No spawning, ore scoring, TILING_BACK route construction, assault movement, marker encoding, or direct-core routing logic changed. |
| Invariants checked | Existing boxed-by-friends opening escape is unchanged when one or two legal escape moves exist. When no move is legal, no movement, path-cache, marker, road, or mode state is changed beyond the normal no-move shared-progress path. TILING_BACK, assault movement, rush/hijack road behavior, and direct-core routing are unchanged. |
| Edge cases checked | Zero legal moves now returns `False` instead of crashing. One legal escape move still chooses that move. More than two legal moves still declines the fallback as before. Friendly builder counting still only considers visible same-team builder bots. |
| Time-risk check | Adds one boolean check over a list already built with at most four cardinal entries. No new SDK calls, loops, scans, pathfinding, marker protocols, or persistent state. |
| Execution model | No shared mutable state, fake manager, or non-marker communication was added. The guard uses only private per-unit state and immediate controller checks. |
| Tests | Added `test_try_pathfinding_move_opening_shell_escape_handles_no_legal_moves` in `tests/test_got_any_grapes_runtime_substrate.py`. The reverted lazy-road tests were removed. |
| Cheap validation | Guard-only patch: `py_compile bots/got-any-grapes/navigation.py` passed; focused opening-shell regression test passed (`1 passed, 252 deselected`); full runtime substrate passed (`253 passed`); touched-file `git diff --check` clean; code/test search found no stale lazy-road symbols. |
| Local smoke pass 1 | Same-seed `settlement`/`jon-6` smoke was invalid as macro evidence. The bot repeatedly raised `ValueError: max() iterable argument is empty` in `_try_opening_shell_escape()` and collapsed to one building; replay analysis saved to `.dist/replay_analysis/got-any-grapes_batch18_no_econ_roads_settlement.json`. |
| Bug found | Existing opening-shell fallback assumed that `adjacent_friendly_builders >= 2` plus `len(movable_directions) <= 2` implied at least one legal escape move. When all cardinal moves were illegal, it called `max()` on an empty generator. Batch 18 made this visible in the smoke, but the root cause is a live navigation guard bug independent of speculative roads. |
| Revision A | Added `or not movable_directions` to the `_try_opening_shell_escape()` no-op guard so no legal escape move returns `False` and falls through to the normal no-move path. Added `test_try_pathfinding_move_opening_shell_escape_handles_no_legal_moves`. This preserves the existing boxed-by-friends escape behavior when one or two legal moves exist. |
| Cheap validation Revision A | `py_compile bots/got-any-grapes/navigation.py` passed; focused opening/speculative path tests passed (`4 passed, 251 deselected`); full runtime substrate passed (`255 passed`); touched-file `git diff --check` clean. |
| Local smoke pass 2 | Same-seed `settlement`/`jon-6` after only the empty-move guard no longer crashed but remained catastrophic: got-any-grapes ended with `0` mined/delivered titanium, `5,014` stored passive titanium, and one building. This rejects the hard no-road economy variant; roads are required walkable infrastructure, so skipping all economy road builds strands builders. Replay analysis saved to `.dist/replay_analysis/got-any-grapes_batch18_no_econ_roads_settlement_revA.json`. |
| Revision B | Replaced the hard no-road gate with lazy road-building for `FINDING_ORE`/`EXPLORING`: try `ct.can_move()` first, skip marker/road calls only if already walkable, otherwise run the old marker-clear/road-build path and retry movement. Rush/hijack eager road behavior is preserved. |
| Cheap validation Revision B | `py_compile bots/got-any-grapes/navigation.py` passed; focused lazy-road/opening tests passed (`5 passed, 251 deselected`); full runtime substrate passed (`256 passed`); touched-file `git diff --check` clean. |
| Local smoke pass 3 | Same-seed `settlement`/`jon-6` lazy-road smoke no longer crashed or stranded builders. got-any-grapes lost by titanium tiebreak at turn `2000`, delivering/mining `79,270` Ti with final stored `42,162`; `jon-6` delivered/mined `82,920` with final stored `60,095`. got-any-grapes had `19` units, `689` buildings, `5` active source ports, top1 source share `24.2%`, top3 source share `69.8%`, failure signals `small_loop` and `travel_without_build`, `227` zero-flow tiles, and `97` orphan tiles. Replay analysis: `.dist/replay_analysis/got-any-grapes_batch18_lazy_roads_settlement.json`. |
| Pre-g16 audit | Read-only audit during smoke rechecked the lazy-road branch, tests, opening-shell guard, and remaining `destroy_marker_if_present()` callers. No stale `SPECULATIVE_ROAD_MODES` symbol remains; the only movement road paths are the lazy/eager branch in `try_pathfinding_move()` and the separate assault movement helper. No new bug found after Revision B. |
| g16 lazy-road report | `.dist/reports/got-any-grapes_batch18_lazy_roads_g16_20260417.json` |
| g16 lazy-road aggregate | `29-19` (`60.4%`), avg TiEq `38,651.7`, worst TiEq `1,270`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` lazy-road | `10-6`, avg TiEq `47,928.8`, worst `7,590`; seat split AB `4-4` avg `56,746.2`, BA `6-2` avg `39,111.2`. |
| `jon-6-a9bfs-surround` lazy-road | `11-5`, avg TiEq `38,432.5`, worst `1,950`; seat split AB `5-3` avg `40,368.8`, BA `6-2` avg `36,496.2`. |
| `leeroy-jonkins` lazy-road | `8-8`, avg TiEq `29,593.8`, worst `1,270`; seat split AB `4-4` avg `36,445.0`, BA `4-4` avg `22,742.5`. |
| Decision on lazy roads | Revert. It materially trails Batch 9 (`34-14`, avg TiEq `43,214`) and collapses `leeroy-jonkins` from `12-4`/avg `50,734` to `8-8`/avg `29,594`. |
| Revision C | Reverted `LAZY_SPECULATIVE_ROAD_MODES`, restored eager speculative road behavior for non-`TILING_BACK`/non-`ASSAULTING` movement, and removed lazy-road tests. Kept only the opening-shell empty-move guard and regression test. |
| Cheap validation Revision C | `py_compile bots/got-any-grapes/navigation.py` passed; focused opening-shell regression test passed (`1 passed, 252 deselected`); full runtime substrate passed (`253 passed`); touched-file `git diff --check` clean; search found no stale lazy-road symbols in bot/tests. |
| Guard-only smoke | Same-seed `settlement`/`jon-6` smoke won by titanium tiebreak at turn `2000`: got-any-grapes delivered/mined `55,710` Ti, final stored `26,684`, `26` units, `635` buildings; `jon-6` delivered/mined `53,290`, final stored `179`, `4` units, `402` buildings. Replay analysis: `.dist/replay_analysis/got-any-grapes_batch18_guard_only_settlement.json`. |
| Guard-only smoke diagnostics | got-any-grapes active source ports `4`, source top1 share `34.4%`, source top3 share `99.3%`, builder max small-loop streak `425`, zero-flow tiles `257`, orphan tiles `83`, dead ends `1`. Failure signals remain loop/TWB related and are not introduced by the guard. |
| Guard-only pre-g16 audit | Rechecked restored eager road path, the empty-move guard, and tests. Code/test search found no lazy-road constants or tests. The only remaining Batch18 behavior change is the zero-legal-move guard before `max(movable_directions)`. No new bug found. |
| Guard-only g16 report | `.dist/reports/got-any-grapes_batch18_guard_only_g16_20260417.json` |
| Guard-only g16 aggregate | `29-19` (`60.4%`), avg TiEq `37,406.9`, worst TiEq `1,700`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` guard-only | `10-6`, avg TiEq `49,279.4`, worst `4,510`; seat split AB `4-4` avg `44,857.5`, BA `6-2` avg `53,701.2`. |
| `jon-6-a9bfs-surround` guard-only | `9-7`, avg TiEq `31,787.5`, worst `2,180`; seat split AB `4-4` avg `21,635.0`, BA `5-3` avg `41,940.0`. |
| `leeroy-jonkins` guard-only | `10-6`, avg TiEq `31,153.8`, worst `1,700`; seat split AB `5-3` avg `36,710.0`, BA `5-3` avg `25,597.5`. |
| Batch9 comparison | Same 48 map/seed/seat records as Batch9. Guard-only trails Batch9 by `5` wins and `5.8k` avg TiEq; biggest loss is `leeroy-jonkins` avg delta `-19,580.6`. |
| Decision | Revert completely. The hard no-road and lazy-road variants were mechanistically wrong or regressive. The empty-move guard fixed a real crash exposed by the rejected road variant, but guard-only g16 was not acceptable; it likely changes no-move progress handling in opening-core congestion. Revisit only with a semantics-preserving skip-turn guard if the crash appears under kept code. |
| Revert validation | Removed `LAZY_SPECULATIVE_ROAD_MODES`, lazy road branch/tests, the `or not movable_directions` guard, and the empty-move regression test. `py_compile bots/got-any-grapes/navigation.py` passed; focused opening-shell selection `1 passed`; full runtime substrate returned to `252 passed`; touched-file `git diff --check` clean; search found no Batch18-only code/test symbols. |
| Next target | Continue runtime-safe ROI selection. Do not skip or lazily delay economy road builds; roads are required movement infrastructure. Avoid changing opening no-move handling unless preserving old macro semantics is explicit. |

#### Batch 17: cached-path TILING_BACK micro perception

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety reduction for steady `TILING_BACK` turns. Live code has `perception.scan_micro()` and tests, but `rg` shows no production caller; `bots/got-any-grapes/README.md` also says it is not currently called. This leaves every non-full TILING_BACK turn paying the reduced fast scan instead of the unit-only micro scan. |
| Planned code scope | Add a private `BuilderBot._should_use_micro_perception()` gate, route `BuilderBot.run()` through `scan_micro()` when the gate is true, and add micro-scan danger-zone/dynamic-unit-overlay maintenance so cached-path builders still see current units. |
| Gate invariants | Current revision allows micro only for non-assault, non-defender `FINDING_ORE` builders, after at least one full scan, before the normal FINDING_ORE full-scan heartbeat expires, with an active ore/access target, with a cached path of at least three actions, and with the cached current target matching that access tile. TILING_BACK is deliberately excluded after same-seed smoke regressions. |
| Expected benefit | Replaces fast/full perception with one `get_nearby_units()` pass on low-risk travel-to-ore turns. No strategic intelligence is removed permanently because full/fast scans still run on heartbeat, search turns without a cached ore path, target changes, TILING_BACK route construction, and all assault/defender turns. |
| Pre-edit audit | Inspected `BuilderBot.run()`, `_should_use_fast_perception()`, `perception.scan_micro()`, fast/full scan inference, `mode_tiling_back.execute()`, `_navigate_and_build()`, pending-build/bridge/route-completion paths, and navigation friendly-blocker handling. The main risk is stale grid data while moving; the gate avoids no-path/replan and pending-build turns, and engine `can_move`/`can_build_*` checks remain final authority. |
| Tests to add/update | Add micro-gate tests for cached path, heartbeat expiry, pending work, short path, defender/assault exclusion, and scan-micro sentinel/gunner danger-zone marking. Add one run-wiring test if the existing substrate can patch `scan_micro`/`scan_around` cleanly without creating a brittle full-turn fixture. |
| Cheap validation pass 1 | `py_compile builder_bot.py perception.py` passed; focused micro/fast perception pytest `9 passed`; touched-file `git diff --check` clean; full runtime substrate `256 passed`. |
| Local smoke pass 1 | Same-seed `settlement`/`jon-6` smoke (`USE_GLOBAL_SEED=true`, seed `204011053`) with TILING_BACK micro completed without crash but lost badly: got-any-grapes `50,000` delivered/`28,085` final titanium vs `jon-6` `96,710` delivered/`74,597` final. Existing same-seed Batch 9 smoke had got-any-grapes `63,580` delivered/`24,992` final; Batch 14 probe had `66,670` delivered/`40,459` final. |
| Bug found after smoke | Production use of `scan_micro()` exposed an incomplete micro contract: it refreshed unit lists but left the remembered `grid` dynamic unit overlay stale. TILING_BACK navigation and blocker handling read `grid["entity"]`; using micro without clearing/replacing unit entities can route around stale builders or miss current blockers. |
| Revision A | `scan_micro()` now clears stale dynamic unit fields from prior micro/bot/enemy positions and writes current visible unit occupancy into `bot.grid`, while still avoiding tile env, building, marker, topology, and ore-set refresh. Added a unit-overlay regression test. |
| Local smoke pass 2 | Same-seed `settlement`/`jon-6` after the unit-overlay fix still lost badly: got-any-grapes `49,640` mined/`32,716` final vs `jon-6` `104,280` mined/`71,310` final. This rejects TILING_BACK micro as too behavior-changing; route construction needs the local fast scan. |
| Revision B | Move the production micro gate from TILING_BACK to cached FINDING_ORE travel only. TILING_BACK returns to the existing fast/full scan cadence; the scan_micro unit-overlay and danger-zone fixes remain because production micro now needs them. |
| Cheap validation pass 2 | FINDING_ORE-only revision: `py_compile builder_bot.py perception.py` passed; focused micro/fast perception pytest `10 passed`; full runtime substrate `257 passed`; touched-file `git diff --check` clean. |
| Local smoke pass 3 | Same-seed `settlement`/`jon-6` with FINDING_ORE-only micro won by enemy core destruction on turn `843`. got-any-grapes delivered `24,870`/final `4,019` Ti before the early core kill; `jon-6` delivered `29,500`/final `12,314`. Failure signals remained `small_loop`, `low_builder_progress`, `travel_without_build`, but no crash or obvious TILING_BACK starvation reproduced. |
| g16 report | `.dist/reports/got-any-grapes_batch17_finding_micro_g16_20260417.json` |
| g16 aggregate | `28-20` (`58.3%`), avg TiEq `39,171.5`, worst TiEq `740`; local timing fields are unavailable/all-zero and not trustworthy timing evidence. |
| `jon-6` | `8-8`, avg TiEq `40,758.8`, worst `2,200`; seat split AB `4-4` avg `36,411`, BA `4-4` avg `45,106`. |
| `jon-6-a9bfs-surround` | `10-6`, avg TiEq `28,934.4`, worst `740`; seat split AB `5-3` avg `38,215`, BA `5-3` avg `19,653`. |
| `leeroy-jonkins` | `10-6`, avg TiEq `47,821.2`, worst `3,530`; seat split AB `4-4` avg `39,070`, BA `6-2` avg `56,572`. |
| Pre-benchmark/no-edit audit | Inspected `BuilderBot.run`, `_should_use_fast_perception`, Batch17 `_should_use_micro_perception`, `perception.scan_micro`, `mode_finding_ore.execute`, and the TILING_BACK scan path after Revision B. Invariants checked: no globals or non-marker coordination; micro state was per-builder only; full/fast scan heartbeat remained; TILING_BACK was excluded after same-seed regressions; engine `can_move`/`can_build_*` checks remained final authority. Edge cases checked: missing full scan, no cached path, mismatched cached target, defender/assault role exclusion, stale dynamic-unit overlay, and no production use during route construction. Time-risk check: micro reduced SDK calls, but local timing was unavailable and the behavioral regression dominated. |
| Decision | Revert and do not remote-test. FINDING_ORE-only micro materially trailed Batch 9 (`34-14`, avg TiEq `43,214`), especially `jon-6` (`11-5` to `8-8`) and aggregate wins (`34-14` to `28-20`). TILING_BACK micro had already failed deterministic smoke twice. |
| Revert validation | Removed `_should_use_micro_perception`, `MICRO_PATH_MIN_STEPS`, production `scan_micro()` routing, dynamic-unit-overlay/danger-zone `scan_micro()` expansion, README production-use wording, and Batch17-only tests. `py_compile builder_bot.py perception.py` passed; stale Batch17 symbol search returned no matches in bot/tests; focused `scan_micro`/fast-perception tests `5 passed`; full runtime substrate `252 passed`; touched-file `git diff --check` clean. |
| Next target | Treat production `scan_micro()` routing as rejected until there is a safer contract. Continue with live-code ROI selection around stronger runtime or route-quality mechanisms that do not reduce perception during active route construction or target selection. |

#### Batch 14: visible assault harvester evaluation cap

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic/runtime bound for ASSAULTING turns. A debug-profile smoke on `settlement`/`jon-6`/seed `204011053` showed assault spikes up to `4288us` when dense enemy visibility caused every visible harvester to be assessed and ranked against large clusters. |
| Code changed | Added `_visible_harvester_assault_candidates()` in `mode_assaulting.py` and routed `_best_visible_site()` through it. The helper keeps at most four visible harvester anchors per turn: the best three by live/committed-anchor priority, local distance, core-rusher core-distance tiebreak, and stable map order, plus one round-robin tail candidate. Nonselected visible harvesters are passed through `ignored_harvesters` so target scoring still sees non-harvester enemies. Selected candidates are still assessed before site choice to preserve the live-anchor filter. |
| Completion surface | Live anchors, committed anchors, claimed anchors, blacklisted anchors, exhausted regions, anchor assessment cache use, `choose_best_visible_assault_site()` call shape, core-rusher tiebreak semantics, and marker publication are covered. No pathfinding, spawning, direct-core routing, or shared state changed. |
| Bug audit | Inspected `_best_visible_site()`, `_anchor_assessment()`, `_committed_plan_hint()`, `_blocked_ring_positions()`, `execute()`, and `assault.choose_best_visible_assault_site()`. Invariants checked: cap applies only to visible HARVESTER anchors; full enemy list is still supplied for scoring; live/committed anchors cannot be dropped by overflow; blacklisted/exhausted/claimed anchors stay ignored; core distance remains a tiebreak after local distance, not a leading key; selected anchors are still live-filtered before commit; no globals or cross-unit state added. |
| Edge cases checked | No visible enemies returns `None`; `<=4` eligible harvesters preserves old evaluation count; overflow uses deterministic round-robin tail sampling; dried/non-live selected anchors are added to `ignored_harvesters`; absent `turn_profile` is safe because profile helpers compile to no-ops. |
| Time-risk check | Adds one bounded sort over currently visible harvesters only on overflow, then caps expensive `_anchor_assessment()` and assault-site ranking to four anchors per turn. No SDK calls are added on non-overflow turns; overflow uses one existing position/map-width/id lookup class and should reduce dense-cluster inner work. |
| Tests | Added focused tests for overflow capping, live-anchor preservation, committed-anchor preservation, and kept the existing core-rusher tiebreak regression. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_assaulting.py` passed; focused selector/core-rusher tests `4 passed`; full runtime substrate `255 passed`; touched-file `git diff --check` clean. Global `git diff --check` still reports pre-existing trailing whitespace in `FIRST_LONGFORM_PROMPT.md`, unrelated to this batch. |
| Local smoke finding | Same-seed debug-profile smoke won by enemy core destruction on turn `816`; the earlier Batch 14 probe without this cap reached turn `2000` and won by tiebreak. Assault max remained high (`3993us`) because selected visible anchors are still live-assessed before ranking, but sites scored fell from prior worst examples up to `48`/`54` to `24` on the slowest assault turn. |
| Reverted follow-up | A duplicate-assessment-removal follow-up made ASSAULTING cheap but removed useful pressure on the same deterministic smoke: it lost to `jon-6` by titanium tiebreak at turn `2000` with `0` assault profile rows above `500us`. Reverted that follow-up and kept the original live-filtering cap. |
| g16 report | `.dist/reports/got-any-grapes_batch14_visible_assault_cap_g16_20260417.json` |
| g16 aggregate | `29-19` (`60.4%`), avg TiEq `37,202`, worst TiEq `180`; local replay timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `13-3`, avg TiEq `61,071`, worst `180`; seat split AB `6-2`, BA `7-1`. |
| `jon-6-a9bfs-surround` | `7-9`, avg TiEq `25,813`, worst `830`; seat split AB `5-3`, BA `2-6`. |
| `leeroy-jonkins` | `9-7`, avg TiEq `24,723`, worst `1,260`; seat split AB `5-3`, BA `4-4`. |
| Decision | Revert. Despite a same-seed smoke core win, the g16 result is materially worse than the kept Batch 9 baseline (`34-14`, avg TiEq `43,214`) and weakens both pressure matchups. The cap appears to reduce some dense visible-site work but disrupts useful target pressure/anchor coverage. |
| Revert validation | Removed the cap constants, helper, caller wiring, and focused tests. `git diff -- bots/got-any-grapes/mode_assaulting.py` is empty; no Batch14 test names remain. `py_compile bots/got-any-grapes/mode_assaulting.py` passed; focused core-rusher selector test `1 passed`; full runtime substrate `252 passed`; touched-file `git diff --check` clean. |
| Next target | Avoid further visible-harvester cap/deferred-assessment changes without stronger replay evidence. Continue with a lower-risk hot-path pass or a route/perception fix that does not reduce assault target coverage. |

#### Batch 15: full-scan inference loop allocation cleanup

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic full-scan perception cost in `_infer_state_from_grid()`. Debug profile rows repeatedly show `perception_infer_ns` in the `200-500us` range on full scans, and the loop runs over every visible tile. |
| Code changed | Changed the visible-tile loop to reuse the tuple already stored in `visible_positions` instead of allocating a duplicate `(x, y)` tuple per tile. Bound hot set/list operations (`known_obstacles`, ore sets, enemy target append, passable enemy building add) to locals, and reused a per-tile `Position` object when one is already needed for ore/hostile tracking. |
| Completion surface | Only `_infer_state_from_grid()` changed. Scan mode selection, marker parsing, topology dirty detection, connected-conveyor refresh, harvester tracking, pathfinding, and assault/economy decisions are unchanged. |
| Bug audit | Checked ore add/discard behavior, hostile target creation, enemy core handling, confirmed harvester updates, known obstacle add/discard, topology dirty keys, and visible friendly builder population. The change does not add state, markers, SDK calls, or cross-unit coordination. |
| Time-risk check | This is behavior-neutral local-loop cleanup: fewer tuple allocations and fewer attribute lookups in the hot inference loop. It does not alter the amount of map data scanned or any time gates. |
| Tests | No new behavior-specific tests; existing perception/snapshot/infer tests cover the data contracts. |
| Cheap validation | `py_compile bots/got-any-grapes/perception.py` passed; focused perception/snapshot/infer substrate tests `33 passed`; full runtime substrate `252 passed`; touched-file `git diff --check` clean. |
| Local smoke | Same-seed `settlement`/`jon-6` debug profile lost by titanium tiebreak at turn `2000`, got-any-grapes `39,581` delivered vs jon-6 `57,605`. This same seed without Batch 15 had previously been a got-any-grapes tiebreak win around `40,459` delivered. Full-scan `perception_infer_ns` still averaged `184,706ns` across the sampled full-ish rows, with max `487,000ns`; no strong runtime win was visible. |
| Decision | Revert before g16. The change is technically behavior-neutral at the Python semantics level, but it touches timing-sensitive per-turn code, showed no compelling profile improvement, and produced worse deterministic smoke behavior. |
| Revert validation | Removed the infer-loop allocation edits. `py_compile bots/got-any-grapes/perception.py` passed; focused perception/snapshot/infer tests `33 passed`; full runtime substrate `252 passed`; touched-file `git diff --check` clean; search found no Batch15-only diff markers (`grid_get`, `ti_add`, `known_add`, `position_obj`) remaining in the perception diff. |
| Next target | Do not spend more time on tiny infer-loop allocation rewrites unless a profile identifies a specific Python operation dominating the turn. Look for stronger mechanistic signals in navigation/path construction or perception scan policy. |

#### Batch 16: core-port turret barrier guard

| Item | Finding |
| --- | --- |
| ROI target | Early survival against turret pressure. Batch 9 losses include `leeroy-jonkins` on `first_sound` ending by enemy core destruction at turn `494`, with enemy sentinel pressure appearing early while our supplied sentinel defense is often unavailable. |
| Code changed | Extended `defense.core_port_guard_if_needed()` so visible hostile turrets near the core shell can trigger the existing bounded barrier response. Builder threats keep the old close-builder slot threshold; turret threats use a wider slot threshold but still respect the same visible approach-slot list, lane-protection guard, two-barrier cap, and cooldown. |
| Completion surface | Only `defense.py` core-port barrier candidate selection changed. No marker protocols, spawning, pathfinding, supplied-sentinel gating, or direct-core economy code changed. |
| Bug audit | Checked that assault builders are still skipped, quiet turns still no-op, damaged core ports are healed before barriers, hostile logistics underfoot still clear first, visible barrier cap/cooldown still apply, own direct-core lane tiles remain protected, and candidate enumeration is bounded to the 12 core approach slots. |
| Time-risk check | Adds one small loop over already-filtered core threats and only inside the existing core-port guard path. No SDK calls are added beyond existing `ct.can_build_barrier()` checks on bounded candidates. |
| Tests | Added `test_core_port_guard_blocks_visible_core_turret_threat`; existing core-port guard tests cover quiet no-op, assault skip, heal, hostile clear, builder barrier, TILING_BACK emergency behavior, cooldown, cap, lane protection, and bounded slot use. |
| Cheap validation | `py_compile bots/got-any-grapes/defense.py` passed; focused core-port guard tests `12 passed`; full runtime substrate `253 passed`; touched-file `git diff --check` clean. |
| Local smoke | Same-seed `first_sound`/`leeroy-jonkins`/seed `535813031` still lost by enemy core destruction, and regressed from Batch 9's turn `494`/`1,320` delivered Ti failure to turn `390`/`135` delivered Ti. |
| Decision | Revert before g16. The barrier response likely consumed/blockaded early economy without stopping the sentinel rush, exactly the failure mode the hard constraints warn about for unsupplied defense. |
| Revert validation | Removed the turret-barrier constants, candidate-selection changes, and focused test. `py_compile bots/got-any-grapes/defense.py` passed; focused core-port guard tests returned to `11 passed`; full runtime substrate `252 passed`; touched-file `git diff --check` clean. |
| Next target | Do not add core-port turret barriers without a stronger replay mechanism for preserving the first titanium lane. Defensive work should prefer supplied-gun or lane-preservation primitives. |

#### Batch 1: assault opening escape tuple planner

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic remote-safety pass on `mode_assaulting` opening escape. Prior notes identify the old path as a high-cost double BFS with many `Position` allocations during early assault turns. |
| Code changed | Replaced the old `_shell_exit_target` BFS with a tuple-based shell-perimeter target, changed `_shell_escape_route` to expand tuple keys and reconstruct `Direction` paths directly, and precomputed opening-escape direction deltas/sign lookup. |
| Completion surface | `opening_escape_active`, cached bootstrap reuse, direct outward step, blocked-turn limit, and economy-yield behavior are unchanged. The fallback route still uses `navigation._assault_is_walkable_key` and per-unit private state only. |
| Bug audit | Checked core-pos/spawn-vector guards, map-edge clamping, target-outside-shell invariant, start-tile `ct.can_move` legality, no marker/global coordination changes, and bounded work (`SHELL_BFS_MAX_TILES = 49`). Found and fixed an edge case where a clamped target could remain inside the spawn shell near map borders. |
| Tests | Added shell-vector target, map-edge target, and blocked-direct-step route tests in `tests/test_got_any_grapes_runtime_substrate.py`. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_assaulting.py` passed; focused `pytest -q tests/test_got_any_grapes_runtime_substrate.py -k 'opening_escape or shell_exit'` = `4 passed`; full substrate = `246 passed`; `git diff --check` clean for touched files. |
| Next validation | Run local `USE_GLOBAL_SEED=true` g16 against `jon-6`, `jon-6-a9bfs-surround`, and `leeroy-jonkins`; do a no-edit audit while it runs. |

| Follow-up audit item | Resolution |
| --- | --- |
| Benchmark interruption | First g16 attempt was stopped after the no-edit audit found a same-batch micro-allocation follow-up; no result should be treated as evidence. |
| Hot-loop allocation | `_shell_escape_route` now passes a shared immutable empty obstacle set instead of allocating `{}` for each neighbor expansion. |
| Duplicate spawn-vector lookup | `_shell_escape_route` computes the spawn vector once and passes it to `_shell_exit_target`. |
| Revalidation | After the follow-up: `py_compile` passed; focused opening tests `4 passed`; full substrate `246 passed`; diff check clean for touched files. |

| Second follow-up audit item | Resolution |
| --- | --- |
| Direct-step overhead | A second g16 attempt was stopped before evidence collection because `_opening_escape_step` still used `utils.direction_toward()` plus a temporary `Position` for the preferred outward move every opening turn. |
| Direct-step fix | Added `_direction_from_delta()` and used it for both tuple-key direction selection and the direct outward step. |
| Revalidation | After this follow-up: `py_compile` passed; focused opening tests `4 passed`; full substrate `246 passed`; diff check clean. |
| Remaining audit result | Read-only search found no `temporary_obstacles={}`, no opening direct-step `Position(current_pos...)`, and no remaining `direction_toward()` call in the opening escape flow. |

| g16 result | Evidence |
| --- | --- |
| Report | `.dist/reports/got-any-grapes_opening_escape_tuple_g16_20260417.json` |
| Aggregate | `26-22` (54.2%), avg TiEq `32150.0`, worst TiEq `0`, local timing fields all `0.0%` because local replay timing is not trustworthy evidence. |
| `jon-6` | `11-5`, avg TiEq `37836.9`, worst TiEq `150`; seat split AB `3-5`, BA `8-0`. |
| `jon-6-a9bfs-surround` | `9-7`, avg TiEq `26246.9`, worst TiEq `980`; seat split AB `5-3`, BA `4-4`. |
| `leeroy-jonkins` | `6-10`, avg TiEq `32366.2`, worst TiEq `0`; seat split AB `3-5`, BA `3-5`. |
| Failure decision | Revise, not keep. The allocation-reduction idea is still mechanistically valid, but the arithmetic outward shell target changed early assault/rusher routing and likely caused the behavior regression. Next revision restores the old shell-exit target-selection semantics using tuple keys instead of `Position` objects. |

| Revision | Evidence |
| --- | --- |
| `opening_escape_tuple_bfspreserve` scope | Restored old `_shell_exit_target` BFS-order semantics with tuple keys, kept direct-step `_direction_from_delta()`, direct `Direction` path reconstruction, shared empty obstacle set, and no `Position.add()` inside the BFS expansions. |
| Regression guard | Updated shell-exit test to assert the old BFS-order target `Position(14, 7)` for the east-spawn fixture; kept map-edge and blocked-direct-step route tests. |
| Bug audit | No illegal shared state, no marker protocol change, no route-work beyond `SHELL_BFS_MAX_TILES`, start-step movement still checked by `ct.can_move`, route walkability still goes through `navigation._assault_is_walkable_key`. Read-only search found no `direction_toward()` or temporary `{}` allocation in the opening escape path. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_assaulting.py` passed; focused opening tests `4 passed`; full substrate `246 passed`; diff check clean. |
| Next validation | Run `USE_GLOBAL_SEED=true` g16 as `.dist/reports/got-any-grapes_opening_escape_tuple_bfspreserve_g16_20260417.json`. |

| Revision g16 result | Evidence |
| --- | --- |
| Report | `.dist/reports/got-any-grapes_opening_escape_tuple_bfspreserve_g16_20260417.json` |
| Aggregate | `29-19` (60.4%), avg TiEq `38859.0`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `11-5`, avg TiEq `56444.4`, worst TiEq `0`; seat split AB `5-3`, BA `6-2`. |
| `jon-6-a9bfs-surround` | `10-6`, avg TiEq `23900.6`, worst TiEq `540`; seat split AB `5-3`, BA `5-3`. |
| `leeroy-jonkins` | `8-8`, avg TiEq `36231.9`, worst TiEq `660`; seat split AB `4-4`, BA `4-4`. |
| Dot-product direction audit | Added `_direction_from_delta()` parity with `utils.direction_toward`; focused tests `5 passed`, full substrate `247 passed`. This did not materially change the g16 interpretation because the sign-based direction was already equivalent for nonzero `dx,dy`. |
| Decision | Revert this batch. The revised version is no longer the obvious arithmetic-target bug, but it still fails local g16 and materially trails the current comparison reports on aggregate and TiEq, while local timing cannot prove the intended remote-safety gain. Remote validation would be premature under the current gate. |

| Revert validation | Evidence |
| --- | --- |
| Code state | Removed the opening-escape tuple planner and its tests; `git diff -- bots/got-any-grapes/mode_assaulting.py` is empty again, so only pre-existing unrelated dirty files remain. |
| Cheap validation after revert | `py_compile bots/got-any-grapes/mode_assaulting.py` passed; focused opening slice `1 passed`; full runtime substrate returned to `243 passed`; diff check clean. |
| Next target | Abandon opening-escape tuple planner for now. Continue with a narrower performance/correctness ROI that avoids early assault path geometry changes. |

#### Batch 2: BFS ore access-cache reuse

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic cost reduction in `mode_finding_ore._find_best_ore_target` during BFS ore selection. Known bug note said `_is_ore_claimed_by_friend` rebuilt access-point cache for each candidate instead of reusing the current selection pass cache. |
| Code changed | `_is_ore_claimed_by_friend` now accepts an optional `access_cache`; BFS selection passes its existing cache into the helper. Fallback Euclidean logic is unchanged. |
| Execution model | Cache remains private local state inside one builder's turn/selection call. No globals, markers, or cross-unit coordination added. |
| Invariants checked | Same target ordering, same friend distance/tie-break logic, same "my access missing means claimed" behavior, no persistence past the current call, and no mutation of bot state. |
| Tests | Added tests that `_is_ore_claimed_by_friend` uses a supplied cache and that `_find_best_ore_target` passes its BFS cache to friend-claim deconfliction. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_finding_ore.py` passed; focused ore-cache tests `3 passed`; full runtime substrate `245 passed`; diff check clean. |
| Next validation | Run local `USE_GLOBAL_SEED=true` g16 as `.dist/reports/got-any-grapes_ore_access_cache_g16_20260417.json`. |

| g16 result | Evidence |
| --- | --- |
| Report | `.dist/reports/got-any-grapes_ore_access_cache_g16_20260417.json` |
| Aggregate | `28-20` (58.3%), avg TiEq `44181.2`, worst TiEq `100`; local replay timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `8-8`, avg TiEq `46095.0`, worst TiEq `1570`; seat split AB `3-5`, BA `5-3`. |
| `jon-6-a9bfs-surround` | `12-4`, avg TiEq `40775.6`, worst TiEq `100`; seat split AB `6-2`, BA `6-2`. |
| `leeroy-jonkins` | `8-8`, avg TiEq `45673.1`, worst TiEq `1720`; seat split AB `5-3`, BA `3-5`. |
| Decision | Keep as a behavior-neutral mechanistic cleanup, not promotion-worthy and not sufficient for remote validation. Code audit shows the cache key includes `(ore, from_pos)` and the cache is private to one selection call; the `jon-6` win-rate drop is likely local run noise rather than a causal behavior change, but the batch should not be committed by itself. |
| Next target | Continue with a mechanistic `FINDING_ORE` hot-path pass or another low-risk correctness fix; no remote tests until a local g16 candidate is stronger. |

#### Batch 3 setup: labyrinth no-progress profile

| Item | Finding |
| --- | --- |
| Profile run | `USE_GLOBAL_SEED=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=0 cambc run bots/got-any-grapes bots/jon-6 maps/labyrinth.map26 --seed 204011053 --replay .dist/replays/got-any-grapes_profile_labyrinth_seed_204011053.replay26` |
| Replay analysis | `.dist/replay_analysis/got-any-grapes_profile_labyrinth_seed_204011053.json` |
| Result | Loss on tiebreak at turn `2000`; got-any-grapes delivered/mined `23850` titanium and ended with `21899` stored titanium; jon-6 delivered/mined `28830` titanium and ended with `32432` stored titanium. |
| Failure signals | `small_loop`, `low_builder_progress`, `travel_without_build`, `core_port_concentration`. |
| Pipeline diagnostics | `81` zero-flow tiles, `34` orphan tiles, `2` dead ends, `3` active source ports, source top1 share `41.3%`, source top3 share `100%`. |
| Travel-without-build diagnostics | `203` builder travel-without-build events; `146` at streak `8`, `57` at streak `16`. Worst event count by builder: id `528` had `48`, id `579` had `30`, id `19` had `21`. |
| Live-code audit so far | Existing `_note_small_loop_progress` already tracks all modes, preserves ore blacklists, clears path/planner/pending build state, and does not force a mode change. `FINDING_ORE` already blacklists stationary ore stalls and repeated harvester build failures; `TILING_BACK` has separate stationary/ping-pong/pending-build stall guards. |
| Implementation target | Correct the existing small-loop detector so it matches the documented/replay-analyzer 3-position loop signature instead of only detecting 2-position loops. This is narrower than adding a new travel-without-build policy and directly addresses hot builders with `small_loop_streak` above `1000`. |

| Batch 3 item | Finding |
| --- | --- |
| ROI target | Emergent/mechanistic recovery for builders trapped in 3-tile loops across `FINDING_ORE`/`TILING_BACK`/`EXPLORING`. The live comment claimed 1-3 tile loop coverage, but constants only detected `<=2` unique positions over `8` turns while the analyzer flags `<=3` over `24`. |
| Code changed | In `builder_bot.py`, set `SMALL_LOOP_HISTORY = 24` and `SMALL_LOOP_UNIQUE_THRESHOLD = 3`; kept `SMALL_LOOP_BREAK_THRESHOLD = 12` and kept the existing recovery action unchanged. |
| Execution model | Still per-builder private state only: `small_loop_position_history`, `small_loop_streak`, and `last_small_loop_recovery_round`. No globals, markers, shared manager, or cross-unit coordination added. |
| Invariants checked | Recovery still skips heal turns, preserves ore blacklists, clears only active target/path/planner/pending-build state, does not force a mode switch, and rate-limits repeated recovery by `last_small_loop_recovery_round`. A 4-tile patrol does not trigger recovery. |
| Time-risk check | History memory rises from `8` to `24` tuple entries per builder; each turn still performs one append, one bounded `pop(0)`, and one `set(history)` over at most `24` entries. No SDK calls, pathfinding, perception, or marker work added. |
| Tests | Added `test_small_loop_recovery_catches_three_tile_cycle` and `test_small_loop_recovery_ignores_four_tile_patrol`. |
| Cheap validation | `py_compile bots/got-any-grapes/builder_bot.py` passed; focused small-loop tests `2 passed`; full runtime substrate `247 passed`; diff check clean for touched files. |
| Local profile validation | Same `labyrinth`/`jon-6`/seed `204011053` profile flipped from a tiebreak loss to a got-any-grapes tiebreak win. Delivered titanium increased from `23850` to `31370`, harvesters from `6` to `7`, bridges from `27` to `36`, active source ports from `3` to `4`, source top1 share from `41.3%` to `31.4%`, and source top3 share from `100%` to `87.0%`. |
| Local profile caveat | Analyzer-level loop diagnostics did not improve: travel-without-build events increased from `203` to `623`, `builder_max_small_loop_streak` stayed high (`1538` to `1603`), and zero-flow/orphan counts increased (`81/34` to `99/47`). This suggests the batch may improve productive throughput on the profiled map but does not fully solve the replay-level loop signature. |
| g16 report | `.dist/reports/got-any-grapes_small_loop3_g16_20260417.json` |
| g16 aggregate | `27-21` (56.2%), avg TiEq `41284.2`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `8-8`, avg TiEq `51994.4`, worst TiEq `460`; seat split AB `2-6`, BA `6-2`. |
| `jon-6-a9bfs-surround` | `9-7`, avg TiEq `31207.5`, worst TiEq `1330`; seat split AB `4-4`, BA `5-3`. |
| `leeroy-jonkins` | `10-6`, avg TiEq `40650.6`, worst TiEq `0`; seat split AB `6-2`, BA `4-4`. |
| Loop diagnostic from g16 | Every game still had candidate small-loop signal; avg candidate max small-loop streaks: `jon-6` `1130.2`, `a9` `1523.1`, `leeroy` `1294.0`. |
| Decision | Revert this batch. It improved one deterministic `labyrinth` profile, but failed g16, regressed aggregate/TiEq against the kept comparison point, did not reduce the loop counters it targeted, and is not suitable for remote validation. |
| Revert validation | Removed the small-loop constant changes and the two small-loop tests. `py_compile bots/got-any-grapes/builder_bot.py` passed; focused `small_loop_recovery` selection now has no tests; full runtime substrate returned to `245 passed`; diff check clean. Remaining `builder_bot.py` diff is pre-existing defender-role work, not from this batch. |
| Next target | Prefer a more mechanistic loop/TWB fix that changes what a stuck builder attempts after recovery, or a different low-risk runtime pass; do not simply broaden loop detection further. |

#### Batch 4: TILING_BACK 3-position oscillation recovery

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic/emergent recovery for route builders cycling among 3 positions while `TILING_BACK`. Batch 3 proved broader global detection is not enough; this targets the mode that already has meaningful recovery actions: direct-core slot rotation, pipeline fallback, and eventual harvester blacklist/abandon. |
| Code changed | In `mode_tiling_back.py`, changed `NAV_PING_PONG_HISTORY` from `6` to `12` and `NAV_PING_PONG_UNIQUE_THRESHOLD` from `2` to `3`, so `_note_nav_stall` treats a 3-position rolling local cycle as route oscillation. Existing recovery action is unchanged. |
| Completion surface | No changes to pathfinding, perception, marker protocols, ore selection, or global small-loop recovery. Successful pending-build turns still skip `_note_nav_stall`, so active conveyor/bridge build sequences are not counted as navigation stalls. |
| Execution model | Private per-builder `pathfinding_state` only (`tiling_back_pos_history`, `tiling_back_osc_count`). No shared globals or illegal coordination. |
| Invariants checked | 2-position ping-pong still abandons, 3-position loops now abandon/rotate, 4-position patrols do not trigger, direct-core builders rotate their current lane slot before blacklisting, and harvester blacklisting still goes through `_abandon_tiling_back`. |
| Time-risk check | History size doubles from `6` to `12` positions only for `TILING_BACK` movement turns. Per-turn work remains one append, one bounded pop, and one `set(history)` over at most 12 entries; no SDK calls added. |
| Tests | Added/updated focused tests for 2-position ping-pong, 3-position abandon, 4-position non-oscillation, and 3-position direct-core slot rotation. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_tiling_back.py` passed; focused oscillation tests `4 passed`; full runtime substrate `248 passed`; diff check clean. |
| Local profile validation | Same `labyrinth`/`jon-6`/seed `204011053` profile won on tiebreak. Delivered titanium rose to `32980` versus original profile `23850` and Batch 3 profile `31370`; harvesters rose to `10`; zero-flow tiles fell to `73` versus original `81` and Batch 3 `99`. |
| Local profile caveat | Loop/TWB diagnostics are still present: failure signals remain `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; TWB events were `553` versus original `203` and Batch 3 `623`; active source ports stayed at `3` and source top1 share worsened to `50.7%`. |
| g16 report | `.dist/reports/got-any-grapes_tiling_osc3_g16_20260417.json` |
| g16 aggregate | `28-20` (58.3%), avg TiEq `34615.4`, worst TiEq `0`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `11-5`, avg TiEq `46476.9`, worst TiEq `0`; seat split AB `4-4`, BA `7-1`. |
| `jon-6-a9bfs-surround` | `8-8`, avg TiEq `22116.9`, worst TiEq `580`; seat split AB `4-4`, BA `4-4`. |
| `leeroy-jonkins` | `9-7`, avg TiEq `35252.5`, worst TiEq `0`; seat split AB `4-4`, BA `5-3`. |
| Loop diagnostic from g16 | Small-loop max improved for `a9`/`leeroy` but every game still had small-loop signal; avg max streaks: `jon-6` `1186.8`, `a9` `828.7`, `leeroy` `788.1`. |
| Decision | Revert this batch. It reduced some loop-streak metrics but materially harmed TiEq and pressure-matchup results, especially `a9` avg TiEq `22.1k`. Existing TILING_BACK oscillation recovery is too blunt when widened this way. |
| Revert validation | Removed the TILING_BACK oscillation constant changes and the three focused tests. `py_compile bots/got-any-grapes/mode_tiling_back.py` passed; focused removed-test selection has no tests; full runtime substrate returned to `245 passed`; diff check clean. |
| Next target | Stop broad loop-threshold work. Look for a lower-risk mechanistic runtime/passive-cost reduction or a route-quality fix that does not abandon/retarget working lanes so aggressively. |

#### Batch 5: scan_micro friendly non-builder position skip

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime cleanup in `perception.scan_micro`, which runs on many economy and tiling turns. The old loop fetched `ct.get_position(unit_id)` before knowing whether a visible friendly unit mattered; friendly non-builder units are ignored, so their position fetch was wasted. |
| Code changed | Reordered `scan_micro` unit handling to fetch team/type first, fetch position only for friendly builder bots and enemies, and continue immediately for friendly non-builders. Enemy core/harvester tracking and friendly-builder tracking are unchanged. |
| Execution model | No state sharing or marker protocol changes. Only local perception data in a single builder turn is affected. |
| Invariants checked | Self position is still recorded, friendly builders are still tracked in `bot_locations` and `visible_friendly_builders`, all enemy units still become `VisibleEnemy`, enemy cores still set `enemy_core_anchor`, enemy harvesters still update `confirmed_enemy_harvesters`, and exceptions still skip the unit. |
| Time-risk check | Reduces SDK calls in micro scans by avoiding one `get_position` for each friendly non-builder visible unit. Adds no loops, allocations beyond existing enemy object creation, pathfinding, or marker work. |
| Tests | Added `test_scan_micro_skips_position_for_friendly_non_builder`, keeping existing enemy/friendly-builder and grid-preservation tests. |
| Cheap validation | `py_compile bots/got-any-grapes/perception.py` passed; focused `scan_micro` tests `3 passed`; full runtime substrate `246 passed`; diff check clean. |
| g16 report | `.dist/reports/got-any-grapes_scan_micro_skip_friendly_pos_g16_20260417.json` |
| g16 aggregate | `30-18` (62.5%), avg TiEq `46058.8`, worst TiEq `210`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `10-6`, avg TiEq `54515.0`, worst TiEq `4840`; seat split AB `5-3`, BA `5-3`. |
| `jon-6-a9bfs-surround` | `11-5`, avg TiEq `38536.9`, worst TiEq `240`; seat split AB `6-2`, BA `5-3`. |
| `leeroy-jonkins` | `9-7`, avg TiEq `45124.4`, worst TiEq `210`; seat split AB `5-3`, BA `4-4`. |
| Loop diagnostic from g16 | Every game still had small-loop signal; avg max streaks: `jon-6` `936.6`, `a9` `883.6`, `leeroy` `1085.3`. This is a remaining target, not solved by the micro-scan cleanup. |
| Decision | Keep. The batch has a strong mechanistic runtime rationale, unit-level call-count validation, no obvious behavior regression in g16, improved aggregate TiEq versus the immediately kept Batch 2 state, and materially better `a9` g16 than the recent kept comparison. Do not remote-test solely on this local gate because the bot still does not meet the promotion win-rate bar and local replay timing is unavailable. |
| Commit | Deferred: the worktree contains substantial pre-existing unrelated edits in shared files such as `tests/test_got_any_grapes_runtime_substrate.py` and `STATUS.md`; avoid committing unrelated hunks accidentally. |
| Follow-up | Bound `ct.get_team`, `ct.get_position`, `ct.get_entity_type`, and `ct.get_nearby_units` to local variables inside `scan_micro`. This is a direct mechanical follow-up to the retained micro-scan cleanup; focused `scan_micro` tests still `3 passed`, full substrate `246 passed`, and diff check is clean. No separate g16 was run because it does not change decisions and Batch 5 already provided the scan_micro behavior sanity check. |
| Second follow-up | In `mode_tiling_back._check_connect_to_conveyor`, cached `ct.get_tile_building_id`, `ct.get_entity_type`, `ct.get_team`, and `my_team` inside the helper to avoid repeated controller attribute/team lookups during route-completion checks. Focused same-tile/adjacent merge tests `3 passed`; full substrate `246 passed`; diff check clean. No separate g16 was run because this is a mechanical call-cache change with existing merge behavior tests. |
| Next target | Continue with behavior-neutral or very narrow runtime reductions, or inspect remaining small-loop/TWB cases without changing broad recovery thresholds. |

| No-edit audit while remote r2 runs | Finding |
| --- | --- |
| Touched call paths inspected | `perception.scan_micro`, `mode_finding_ore._find_best_ore_target`, `mode_finding_ore._is_ore_claimed_by_friend`, `mode_tiling_back._check_connect_to_conveyor`, and the focused runtime substrate tests for those helpers. |
| Invariants checked | `scan_micro` still records self/friendly builders, still creates `VisibleEnemy` for every enemy, and still updates enemy core/harvester memory. Ore access-cache reuse remains private to one selection call and preserves access/tie-break semantics. Conveyor merge checks still verify live same-tile and adjacent target buildings against team/type before completion. |
| Edge cases checked | Friendly non-builder position exceptions are no longer observable because the position is intentionally skipped; friendly-builder and enemy position exceptions still skip only that unit. Missing ore access still treats the target as claimed. Stale adjacent conveyor targets are rejected before route completion. |
| Time-risk checks | All retained follow-ups remove or cache SDK/controller calls. No loops, scans, A* expansion, marker writes, or persistent data structures were added in the retained runtime cleanup. |
| Execution-model checks | All caches are function-local or per-unit `bot` private state. No shared Python global coordination and no non-marker inter-unit communication were introduced. |
| Audit result | No bugs found in the retained Batch 2/5/B7 changes. Large unrelated dirty hunks remain in shared files; do not stage/commit without hunk-level review. |

| Remote r2 diagnostic status | Evidence |
| --- | --- |
| Queued matches | `got-any-grapes jon-6` (`bcb2b88f-02cf-4198-9b96-eabbe4d0d830`), `jon-6 got-any-grapes` (`11995063-3255-4171-bc25-3b3bd036ef18`), `got-any-grapes jon-6-a9bfs-surround` (`1a8976ed-c059-4616-a994-222a0f2810e1`), `jon-6-a9bfs-surround got-any-grapes` (`11732487-f834-41bb-bb76-91da5e1a6c29`), `got-any-grapes leeroy-jonkins` (`2b4b31de-e598-43e1-b07a-8101381a397b`). |
| Pending match | None. `leeroy-jonkins got-any-grapes` initially hit the remote rate limit, then queued and completed as `ccc4b095-502c-486a-90da-7152dd278f0d`. |
| Latest poll | All six five-game bundles completed and were analyzed. |
| Next evidence to record | For the next batch, run focused unit tests first, then a cheap local smoke/profile if useful. Do not run more remote validation until a coherent follow-up change batch and cheap validation are complete. |

| Remote r2 analyzed bundle | Us W-L | Avg TiEq | Worst TiEq | Builder >0.5ms | >1ms | >1.5ms | >2ms | TLE turns | Loop/no-progress |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `got-any-grapes` vs `jon-6` (`bcb2b88f`) | `2-3` | `37,694` | `29,780` | `74.3%` | `53.1%` | `49.3%` | `46.8%` | `62,944` | `1648 / 1647` |
| `jon-6` vs `got-any-grapes` (`11995063`) | `4-1` | `51,088` | `16,330` | `64.6%` | `45.9%` | `38.7%` | `34.6%` | `48,749` | `1329 / 1178` |
| `got-any-grapes` vs `jon-6-a9bfs-surround` (`1a8976ed`) | `3-2` | `29,012` | `11,060` | `67.7%` | `53.0%` | `49.2%` | `45.3%` | `57,795` | `1418 / 1387` |
| `jon-6-a9bfs-surround` vs `got-any-grapes` (`11732487`) | `1-4` | `28,056` | `3,190` | `63.4%` | `43.4%` | `34.7%` | `29.8%` | `42,552` | `1351 / 989` |
| `got-any-grapes` vs `leeroy-jonkins` (`2b4b31de`) | `1-4` | `29,950` | `0` | `76.0%` | `52.5%` | `46.3%` | `43.0%` | `60,848` | `1875 / 1586` |
| `leeroy-jonkins` vs `got-any-grapes` (`ccc4b095`) | `2-3` | `25,860` | `9,730` | `77.7%` | `58.9%` | `52.4%` | `48.3%` | `67,497` | `1831 / 1617` |
| **Overall** | `13-17` | `33,610` | `0` | `70.6%` | `51.1%` | `45.1%` | `41.3%` | `340,385` | high in all bundles |

Interim remote timing conclusion: Batch 5/B7 is worth keeping as a small mechanistic cleanup, but it does not solve remote safety. The next ROI must still target hot builder turn cost on complex maps. The dominant evidence is builder turns above `2ms` at roughly `30-47%` in analyzed bundles, with very high TLE-turn counts and persistent `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration` signals.

Live-code correction from the no-edit audit: the retained `scan_micro` optimization is safe but not on the current `BuilderBot.run()` perception path. The actual fast-turn path is `scan_around(..., fast=True)` -> `_scan_local_fast`, and `_scan_local_fast` still fetches `get_position(uid)` before checking whether a visible friendly non-builder matters. The next batch should move that exact skip to `_scan_local_fast` and also use the already-bound `_get_hp`/`_get_max_hp` handles in its building-health branch.

#### Batch 8: live fast/full unit-scan passable-friendly skip

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime cleanup in the live perception hot path after the no-edit audit found `scan_micro` is not called by `BuilderBot.run()`. The actual path is `scan_around(..., fast=True)` -> `_scan_local_fast`, with periodic full `_collect_visible_snapshot` refreshes. |
| Code changed | `_collect_visible_snapshot` and `_scan_local_fast` now fetch unit type/team before position and skip `get_position(uid)` for friendly passable non-builder units, currently most importantly friendly cores. Friendly builders, all enemies, and friendly non-passable turrets still fetch position. `_collect_visible_snapshot` also uses bound SDK handles for direction/bridge/health reads, and `_scan_local_fast` now uses its already-bound `_get_hp`/`_get_max_hp`. |
| Completion surface | The skip is intentionally narrower than the earlier `scan_micro` version: it does not skip friendly sentinels/gunners because those are blocking units and must remain in `known_obstacles`. Full and fast perception use the same rule. No mode policy, marker protocol, pathfinding algorithm, or shared state changed. |
| Execution model | All data remains per-unit local perception state. No globals, no shared manager, no cross-unit communication beyond existing markers. |
| Bug-finding audit | Inspected `_collect_visible_snapshot`, `_update_master_grid`, `_infer_state_from_grid`, `_scan_local_fast`, `_infer_from_grid_fast`, and `BuilderBot.run()` perception selection. Checked that friendly builders still fill `bot_locations`/`visible_friendly_builders`, all enemy units still become grid entities/targets, friendly blocking sentinels remain obstacles, friendly passable cores can be skipped safely, and SDK mocks without unused optional methods still pass. |
| Time-risk checks | Removes selected `get_position` SDK calls and avoids repeated controller attribute lookup in existing branches. Adds no new loops, scans, A*, markers, or persistent structures. Unit-loop work remains one pass over `get_nearby_units()`. |
| Tests added | `test_snapshot_skips_friendly_passable_non_builder_position`, `test_fast_perception_skips_friendly_passable_non_builder_position`, and `test_fast_perception_keeps_friendly_blocking_turret_position`. Existing `scan_micro` skip test remains as non-live helper coverage. |
| Cheap validation | `py_compile bots/got-any-grapes/perception.py` passed; focused perception tests `10 passed`; full runtime substrate `249 passed`; `git diff --check` clean for `perception.py`, runtime substrate tests, and `STATUS.md`. |
| Local smoke | `USE_GLOBAL_SEED=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=2000000 cambc run bots/got-any-grapes bots/jon-6 maps/default_small2.map26 --seed 204011053 --replay .dist/replays/got-any-grapes_batch8_default_small2_smoke.replay26` won by core destruction on turn `515`. Local replay timing fields were all zero again, so local timing remains unavailable. Failure signals still included `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`. |
| g16 report | `.dist/reports/got-any-grapes_batch8_fast_unit_skip_g16_20260417.json` |
| g16 aggregate | `32-16` (66.7%), avg TiEq `40,659.4`, worst TiEq `0`; local timing fields were all `0.0%` and remain unusable as timing evidence. |
| `jon-6` | `12-4`, avg TiEq `53,697.5`, worst `0`; seat split AB `5-3`, BA `7-1`. |
| `jon-6-a9bfs-surround` | `9-7`, avg TiEq `21,835.6`, worst `0`; seat split AB `5-3`, BA `4-4`. |
| `leeroy-jonkins` | `11-5`, avg TiEq `46,445.0`, worst `890`; seat split AB `4-4`, BA `7-1`. |
| No-edit audit during g16 | Read-only search confirmed the live position-read sites affected by this batch are `_collect_visible_snapshot` and `_scan_local_fast`; both now use the passable-friendly skip. `scan_micro` remains helper-only coverage. The audit did not find hidden callers or a missing friendly-turret obstacle path. |
| Decision | Keep only as part of the ongoing runtime batch, not as a promotion candidate and not worth remote-testing alone. Mechanistically it removes live SDK calls and preserves required unit state, but the g16 a9 TiEq is materially worse than the previous Batch 5 report, likely through timing-sensitive path divergence. If the next larger runtime batch does not recover `a9` TiEq or materially reduce remote timing, revise/revert this skip. |
| Next target | Continue runtime work in live perception/navigation. Do not spend remote validation on this tiny batch alone; first identify a larger bottleneck than one friendly-core position skip. |

#### Batch 9 setup: local profile hot-path audit

| Item | Finding |
| --- | --- |
| Profile run | `USE_GLOBAL_SEED=true DEBUG=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=1000000 cambc run bots/got-any-grapes bots/jon-6 maps/settlement.map26 --seed 204011053 --replay .dist/replays/got-any-grapes_batch8_settlement_profile.replay26` |
| Replay analysis | `.dist/replay_analysis/got-any-grapes_batch8_settlement_profile.json` |
| Result | got-any-grapes won by core destruction on turn `996`; got-any-grapes delivered/mined `13,813 / 23,830` titanium, jon-6 delivered/mined `20,462 / 38,720`, units `17` vs `11`, buildings `344` vs `557`. |
| Timing caveat | Local replay `execTimeUs` remained all zero, so replay timing fields are unusable. The debug stdout profile is useful only as a directional local hot-path signal, not remote timing truth. |
| Hot route signal | Economy/tiling full scans were often around `190-320us` local and fast scans around `80-150us`, but mode work was frequently `800-1000us`. A `TILING_BACK` turn at round `247` recorded `nav_anytime_iterations=73`, `nav_anytime_ns=636000`, `nav_compute_ns=659000`, and total turn around `1049us`, pointing at route A* as a large live-mode cost. Many later lines logged `A* failed after 70-100 iterations`. |
| Hot assault signal | Late assault builder `#18` saw `assault_visible_enemies` roughly `24-57`, `assault_target_summary_tile_checks` roughly `102-396`, `assault_sites_scored` up to `24`, and `mode_us` roughly `800-1173`. Assault scoring is a second clear live hot path when enemy structures crowd the area. |
| Failure signals | Replay analysis still flags `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; stdout had `705` messages and `278,945` stdout chars from debug instrumentation. |
| Next target | Inspect route A*/planner state first, because it affects economy, tiling repair, and exploration in all matchups. If the route batch is not safely bounded, pivot to caching/bounding assault target summaries without changing attack intent. |

#### Batch 9: navigation state reuse and failed-A* cooldown

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction in the live route wrapper. `compute_pathfinding_step` runs under economy, exploration, and tiling-back; local profile showed route-mode turns spending hundreds of microseconds in A* and repeated no-path slices. |
| Code changed | `compute_pathfinding_step` now mutates the private per-builder pathfinding state in place instead of copying the state dict and path list every call; temporary obstacles expire in place; empty temp blockers reuse `_EMPTY_BLOCKERS`; and a short `FAILED_ASTAR_COOLDOWN_TURNS = 3` skips re-running exhausted A* for the same full planner signature when bugnav also cannot move. |
| Completion surface | Added `_current_astar_signature`, `_clear_failed_astar_cooldown`, and `_store_failed_astar_cooldown`; target changes, reaching target, any valid path, or bugnav progress clear the failed-A* cooldown. Existing A* budgets, bridge allowance, straight tiling path, micro-plan, and bugnav decision order are preserved. |
| Touched call paths inspected | `navigation.try_pathfinding_move`, `mode_tiling_back._navigate_and_build`, `navigation.assault_navigate`, `_calculate_assault_bfs_result`, `_resume_anytime_astar`, `_calculate_straight_tiling_path_if_clear`, and `calculate_micro_plan`. The only live `compute_pathfinding_step` callers immediately assign the returned state back to `bot.pathfinding_state`. |
| Invariants checked | State remains private to one builder; no marker protocol or global coordination changed. Cached paths are still invalidated on target change or blocked lookahead. Failed-A* cooldown requires exact signature match including start/target, cardinal/tiling/bridge flags, and full obstacle fingerprints; signature changes or expiry re-enable A*. |
| Edge cases checked | Empty temp-obstacle dicts no longer allocate blockers; expired temp obstacles are removed in place; target-tile temp obstacles are still discarded before planning; budget-too-low turns do not create failed-A* cooldown entries; active resumable planners are not skipped. |
| Time-risk checks | Removes dict/list copies on every navigation call and set allocation on no-temp replan turns. The new full-signature check only runs while a short failed-A* cooldown is active or when storing an exhausted failure; this is bounded and replaces a much larger repeated A* search. |
| Execution-model checks | Cooldown is stored in `bot.pathfinding_state`, which is per-unit private state. No shared Python globals, shared manager, or non-marker communication added. |
| Tests added | `test_compute_pathfinding_step_reuses_state_and_path_on_cache_hit`, `test_compute_pathfinding_step_failed_astar_cooldown_skips_same_signature`, and `test_compute_pathfinding_step_failed_astar_retries_when_signature_changes`. Existing temp-obstacle and resumable-A* tests cover unchanged behavior. |
| Cheap validation | `py_compile bots/got-any-grapes/navigation.py` passed; focused navigation slice `10 passed`; full runtime substrate `252 passed`; `git diff --check` clean for `navigation.py`, runtime substrate tests, and `STATUS.md`. |
| Bug audit result | No introduced bugs found before local smoke. Remaining risk is behavioral: skipping repeated failed A* for three turns could delay recovery from a far-grid change not reflected in obstacle fingerprints, so local g16 and replay failure signals must be checked before remote testing. |
| Local smoke | Same `settlement`/`jon-6`/seed `204011053` debug-profile smoke regressed from Batch 8's turn-`996` core kill to a turn-`2000` tiebreak loss: got-any-grapes `24,992` titanium (`63,580` mined) vs jon-6 `45,738` (`77,580` mined). Replay analysis: `.dist/replay_analysis/got-any-grapes_batch9_settlement_smoke.json`; failure signals stayed `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`. |
| Smoke hot-path finding | `rg` found no `nav_failed_astar_cooldown_*` profile keys in the analyzed replay, so the cooldown did not meaningfully fire in this smoke. The remaining hot profile shape is unchanged: many TILING_BACK partial/exact A* slices still hit roughly `650us` local (`nav_compute_ns` around `660-680us`), and full perception/conveyor inference can hit `500-700us` local late-game. |
| Smoke behavioral finding | First sentinel/marker pressure was delayed from Batch 8's roughly turn `913/920` to Batch 9's `1267/1277`; combat lasted longer but did not kill the core. Because local planner decisions depend on `time.time_ns()` and the new cooldown did not fire, this is not yet enough to identify a specific code bug, but it is a strong caution against remote validation. |
| No-edit audit during g16 | Inspected all Batch 9 code while the benchmark ran. `compute_pathfinding_step` live callers (`try_pathfinding_move` and `mode_tiling_back._navigate_and_build`) immediately persist the returned state, so in-place mutation stays within private per-builder state. Cooldown stores/clears on target change, reaching target, any path, or bugnav progress. No illegal coordination or direct correctness bug found. |
| g16 report | `.dist/reports/got-any-grapes_batch9_nav_state_cooldown_g16_20260417.json` |
| g16 aggregate | `34-14` (`70.8%`), avg TiEq `43,214.0`, worst TiEq `740`; local timing fields still `0.0%` and unusable as timing evidence. |
| `jon-6` | `11-5`, avg TiEq `47,654.4`, worst `3,990`; seat AB `5-3`, BA `6-2`. |
| `jon-6-a9bfs-surround` | `11-5`, avg TiEq `31,253.1`, worst `740`; seat AB `5-3`, BA `6-2`. |
| `leeroy-jonkins` | `12-4`, avg TiEq `50,734.4`, worst `1,320`; seat AB `5-3`, BA `7-1`. |
| Timing/failure signals | Local replay timing remains all zero. Every game still had candidate small-loop signals; smoke still showed TILING_BACK A* slices at the existing mode cap and full-perception inference spikes late-game. |
| Decision | Keep as current local runtime baseline, but do not commit or remote-test yet. The batch improves aggregate g16 and repairs the Batch 8 `a9` regression, but it does not pass the per-opponent gate and did not visibly hit the dominant smoke hot path. |
| Next target | Batch 10 should target full-scan connected-topology/load recomputation and perception inference, which local profile shows reaching `500-700us` on high-conveyor-count late turns. |

#### Batch 10: perception ore-key and connected-load bookkeeping

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction in live perception inference and connected-load maintenance. Local profile showed late full perception/inference spikes around `500-700us`; the old code allocated `Position(x, y)` for every visible non-ore tile just to discard it from ore sets, rebuilt the connected-load membership dict on every topology recompute, and copied a second load-count dict before propagation. |
| Code changed | Added private per-builder tuple-key caches for titanium/axionite ore membership, used by both `_infer_from_grid_fast` and `_infer_state_from_grid`. Ore `Position` objects are now created only when a visible tile is new ore, changes ore type, or a remembered ore visibly depletes. Ore markers update the tuple cache too. `_recompute_connected_loads` now syncs connected membership in place before the time gate and computes connected counts directly without `source_counts.copy()`. |
| Completion surface | Full and fast inference, ore marker ingestion, connected incremental refresh, full connected refresh, time-gated load recompute, and focused tests were updated together. No pathfinding policy, marker format, role logic, or direct-core routing changed. |
| Execution model | The new ore-key caches live on the private bot instance only. No shared globals, no shared manager, and no new inter-unit communication were introduced. Connected-load state remains the same private `connected_friendly_conveyors` dict. |
| Bug audit | Inspected `_infer_from_grid_fast`, `_infer_state_from_grid`, `_scan_nearby_markers`, `_update_connected_incremental`, `_refresh_connected_friendly_conveyors`, and `_recompute_connected_loads`. Checked stale ore removal, titanium/axionite type flips, marker ore insertion, connected membership freshness under time pressure, empty connected sets, non-dict load state recovery, and detailed load propagation equivalence after removing the extra dict copy. |
| Time-risk checks | Hot non-ore inference now does tuple membership checks and no `Position` allocation unless a tile was actually remembered as ore. Connected time-gated turns avoid replacing the whole load dict; unchanged membership returns before list allocation. Detailed load recompute still remains graph-linear and governed by `CONNECTED_LOAD_RESERVE_NS`. |
| Tests | Added `test_connected_load_time_gate_syncs_membership_in_place`, `test_full_inference_ore_key_cache_removes_only_seen_depleted_ore`, `test_ore_marker_updates_private_ore_key_cache`, and extended fast inference ore coverage to assert the tuple cache. |
| Cheap validation | `py_compile bots/got-any-grapes/perception.py` passed; focused perception/connected tests `6 passed`; full runtime substrate `255 passed`; `git diff --check` clean for touched files. |
| First smoke/profile | `.dist/replays/got-any-grapes_batch10_settlement_profile.replay26` lost on tiebreak at turn `2000`: got-any-grapes `24,675` titanium (`64,960` mined) vs jon-6 `40,889` (`69,970` mined). Analyzer path `.dist/replay_analysis/got-any-grapes_batch10_settlement_profile.json`; local replay timing remains all zero. Failure signals remained `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`. Debug profile showed the original ore-cache/in-place batch did not reduce the dominant late hot path enough: high-connected full scans still had `perception_connected_ns` around `300-370us`, `perception_infer_ns` around `460-520us`, and `perception_scan_ns` around `600-680us`. |
| Interval-gate revision | Added a large-graph interval gate for optional detailed connected-load counts. For connected graphs below `160` tiles, exact detailed load recompute stayed unchanged. For larger graphs, membership was synced every refresh, but detailed load counts were recomputed only after `4` rounds or a `24`-tile connected-size jump. |
| Interval-gate validation | Cheap validation passed (`py_compile`, focused tests `8 passed`, full substrate `257 passed`), but the fixed `settlement` smoke lost worse than the original Batch 10 smoke: got-any-grapes `21,508` titanium (`55,370` mined/delivered) vs jon-6 `65` stored (`59,660` mined/delivered). Replay analysis: `.dist/replay_analysis/got-any-grapes_batch10b_settlement_profile.json`; active source ports dropped from `4` to `3`, source top3 share worsened to `100%`, and our `builder_max_small_loop_streak` rose from `431` to `817`. Debug profile did show many full scans down around `200-300us`, but the stale-load gate changed route/port quality enough to fail the smoke gate. |
| Second revision | Removed the connected-load interval gate, its round/count state, and its tests. Kept ore tuple-key caches, ore-marker cache updates, in-place membership sync before the existing time gate, and direct connected-count propagation without the extra copy. |
| Second revision tests | `py_compile bots/got-any-grapes/perception.py` passed; focused perception/connected tests `6 passed`; full runtime substrate `255 passed`; `git diff --check` clean. |
| Second revision smoke/profile | `.dist/replays/got-any-grapes_batch10c_settlement_profile.replay26` lost on tiebreak by only `90` mined titanium: got-any-grapes `43,654` stored (`69,420` mined/delivered) vs jon-6 `41` stored (`69,510` mined/delivered). Replay analysis: `.dist/replay_analysis/got-any-grapes_batch10c_settlement_profile.json`. Compared with the first Batch 10 smoke, delivered titanium rose `64,960 -> 69,420`, active source ports stayed `4`, source top3 share improved `85.3% -> 79.8%`, and max small-loop streak improved `431 -> 337`. Failure signals remain `small_loop`, `low_builder_progress`, `travel_without_build`, and `idle_output_spam`. |
| Bug audit after smoke | Read-only audit checked live ore-set mutation paths, connected-topology assignments, the new tests, and `_recompute_connected_loads`. No live builder path mutates ore sets outside perception helpers after key-cache creation; `core_bot.py` has separate private state. Connected membership is exact before the existing time gate; detailed load values are still recomputed exactly unless the existing budget gate fires. No execution-model violation found. |
| g16 result | `.dist/reports/got-any-grapes_batch10c_perception_bookkeeping_g16_20260417.json`: aggregate `28-20` (`58.3%`), avg TiEq `37,490`, worst `0`, local timing all zero/untrustworthy. `jon-6` `9-7`, avg TiEq `37,039`, worst `0`, seat AB `4-4`, BA `5-3`. `jon-6-a9bfs-surround` `10-6`, avg TiEq `36,285`, worst `190`, seat AB `7-1`, BA `3-5`. `leeroy-jonkins` `9-7`, avg TiEq `39,146`, worst `130`, seat AB `4-4`, BA `5-3`. All 48 games still had small-loop signal. |
| Decision | Revert Batch 10. The fixed-map smoke was better than the interval-gated version, but g16 materially trailed the kept Batch 9 baseline (`34-14`, avg TiEq `43,214`) and did not improve TiEq across all opponents. With no trustworthy local timing evidence, remote validation would be premature. |
| Revert validation | Removed ore tuple-key caches, ore-marker cache updates, in-place connected-load membership sync, direct connected-count propagation, and Batch 10 tests. Kept earlier retained perception scan skips. `py_compile bots/got-any-grapes/perception.py` passed; focused perception tests `7 passed`; full runtime substrate `252 passed`; `git diff --check` clean. |
| Next target | Navigation/A* failure throttling in `TILING_BACK` and related economy modes. Smoke profiles repeatedly show `nav_anytime_ns`/`nav_compute_ns` around `650us` on failed route turns and many `A* failed after ...` lines, while Batch 10 showed connected-load shortcuts are risky when they stale route load scoring. |

#### Batch 11: batched resumable-A* time checks

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction in `_resume_anytime_astar`, the live navigation hot loop used by `compute_pathfinding_step` and bridge transit planning. Local debug profiles repeatedly show economy/TILING_BACK turns spending roughly `650us` in `nav_anytime_ns`/`nav_compute_ns`. |
| Code changed | Added `ANYTIME_ASTAR_TIME_CHECK_INTERVAL = 8` and changed `_resume_anytime_astar` to check `time.time_ns()` once every 8 expansions instead of before every heap pop. The planner still checks on iteration `0`, still uses the same mode budgets, same slice-iteration caps, same scoring, same obstacle signatures, same bridge policy, and same path reconstruction. |
| Completion surface | Only the resumable A* loop and its focused regression test changed. No pathfinding budget was lowered, no mode transition changed, and no marker/perception/shared-state behavior changed. |
| Bug audit | Checked that the first iteration still honors an already-expired budget, the maximum overshoot is bounded by 7 extra node expansions, and the existing `A_STAR_TIME_GUARD_NANOSECONDS = 400_000` remains much larger than the expected overshoot. Exact path, partial path, and planner-state return semantics are unchanged. |
| Execution model | Pure per-turn local computation. No shared state, no globals for coordination, and no marker protocol changes. The new constant is a static tuning constant, not cross-unit communication. |
| Tests | Added `test_resumable_astar_batches_time_checks`, which monkeypatches time and verifies a 48-expansion partial slice uses batched time reads rather than one read per expansion. |
| Cheap validation | `py_compile bots/got-any-grapes/navigation.py` passed; focused navigation tests `2 passed`; full runtime substrate `253 passed`; `git diff --check` clean. |
| Smoke/profile | `.dist/replays/got-any-grapes_batch11_astar_timecheck_settlement_profile.replay26` won by core destruction on turn `845`: got-any-grapes `3,470` stored (`20,810` mined/delivered) vs jon-6 `6,988` stored (`26,740` mined/delivered). Replay analysis: `.dist/replay_analysis/got-any-grapes_batch11_astar_timecheck_settlement_profile.json`. Failure signals still include `small_loop`, `low_builder_progress`, `travel_without_build`, and `core_port_concentration`; local timing remains all zero. |
| Smoke audit | The profile did not show a universal `nav_anytime_ns` drop on every hot TILING_BACK turn, but no navigation-budget bug or behavioral crash appeared. The change can affect deterministic timing/order enough to alter the fixed seed, so g16 was required before keeping it. |
| g16 report | `.dist/reports/got-any-grapes_batch11_astar_timecheck_g16_20260417.json` |
| g16 aggregate | `30-18` (`62.5%`), avg TiEq `41,833`, worst `0`; local timing fields all zero/untrustworthy. |
| `jon-6` | `12-4`, avg TiEq `57,635`, worst `8,280`; seat AB `5-3`, BA `7-1`. |
| `jon-6-a9bfs-surround` | `7-9`, avg TiEq `26,559`, worst `540`; seat AB `4-4`, BA `3-5`. |
| `leeroy-jonkins` | `11-5`, avg TiEq `41,304`, worst `0`; seat AB `5-3`, BA `6-2`. |
| Timing/failure signals | All 48 games still had small-loop signal. Local timing fields remained unusable, so the proposed runtime gain could not offset the matchup regressions. |
| Decision | Revert Batch 11. The `jon-6` gain did not compensate for the `a9` collapse and lower `leeroy` TiEq versus the kept Batch 9 baseline. The likely failure mode is that batched time checks altered A* slice boundaries and path quality enough to change route/pressure timing, while local replay timing could not prove a remote-safety win. |
| Revert validation | Removed `ANYTIME_ASTAR_TIME_CHECK_INTERVAL`, restored per-iteration `_time_ns()` checks in `_resume_anytime_astar`, restored the final `nav_anytime_ns` timestamp call, and removed the focused batching test. `py_compile bots/got-any-grapes/navigation.py` passed; focused navigation slice `2 passed`; full runtime substrate `252 passed`; `git diff --check` clean. |
| Next target | Inspect a different hot-path class, especially assault/defense scoring or repeated SDK/perception scans, before editing. Do not reattempt A* time-check batching without new evidence. |

#### Batch 12: assault enemy-cache scoring cleanup

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction in repeated assault scoring. Live `mode_assaulting.execute()` can call visible-site and anchor scoring repeatedly on assault builders; `assault.rank_assault_sites_for_harvester()` rebuilt enemy logistics and threat lists per candidate harvester, and `_friendly_ring_sentinel_state()` built an enemy-position set even when no friendly sentinel existed. This targets repeated assault scoring without changing pathfinding, role policy, marker format, or direct-core economy. |
| Code changed | Added `_enemy_logistics_positions()` and threaded optional `logistics_positions`/`threatening_enemies` through `connected_enemy_logistics_cluster()`, `rank_assault_sites_for_harvester()`, `choose_best_site_for_harvester()`, `assess_anchor()`, `choose_best_visible_assault_site()`, and `choose_best_assault_site()`. `choose_best_visible_assault_site()` and `choose_best_assault_site()` now build those lists once per scoring pass and reuse them across candidate harvesters. `_friendly_ring_sentinel_state()` now builds visible enemy positions lazily only after a friendly sentinel with a direction is found. |
| Completion surface | All public assault scoring entrypoints preserve default behavior for callers that do not pass caches. Direct tests and live callers remain source-compatible. No new bot state, marker messages, or global coordination were added. |
| Pre-smoke bug audit | Inspected all changed call paths plus `mode_assaulting._anchor_assessment`, `_best_site_for_anchor`, `_best_visible_site`, `sentinel_bot.py`, and existing assault tests. The cache contents derive solely from the immutable `enemies` list passed into one scoring call. The threat/logistics filters are the same predicates as before. Lazy sentinel coverage only skips enemy iteration when no friendly sentinel direction could use it. |
| Invariants checked | Best-site ranking tuple order is unchanged; `enemies_by_key` reuse still builds once; anchor assessment still computes cluster status and ranked sites with the same inputs; no caller sees a mutable cache escape except through optional internal parameters. `assault_logistics_position_builds` is a profile counter only. |
| Edge cases checked | No visible harvesters means no cache build. Ignored/blacklisted harvesters do not force cache construction. Friendly sentinel with missing direction still produces no covered targets, matching old behavior. Direct `connected_enemy_logistics_cluster()` and `rank_assault_sites_for_harvester()` calls still build their own cache when none is supplied. |
| Time-risk checks | Removes repeated O(visible enemies) set/list construction during assault scoring. Adds only local references and optional-parameter plumbing. No SDK calls, grid scans, A*, or persistent memory growth added. |
| Execution-model checks | Pure local computation inside one unit turn. No shared Python state for coordination and no non-marker communication. |
| Tests added | `test_assault_visible_site_reuses_enemy_logistics_cache` and `test_friendly_ring_sentinel_state_does_not_scan_enemies_without_sentinel`. Existing core-hitting, threat-filter, and core-rusher tie-break assault tests were rerun. |
| Cheap validation | `py_compile bots/got-any-grapes/assault.py` passed; focused assault scoring slice `5 passed`; full runtime substrate `254 passed`; `git diff --check` clean for touched files. |
| Local smoke/profile | `USE_GLOBAL_SEED=true DEBUG_TURN_PROFILE=true TURN_PROFILE_THRESHOLD_NS=1000000 cambc run bots/got-any-grapes bots/jon-6 maps/settlement.map26 --seed 204011053 --replay .dist/replays/got-any-grapes_batch12_assault_cache_settlement_profile.replay26` won by tiebreak at turn `2000`: got-any-grapes `45,129` stored / `67,900` delivered titanium vs jon-6 `31,117` stored / `63,020` delivered. Replay analysis: `.dist/replay_analysis/got-any-grapes_batch12_assault_cache_settlement_profile.json`. |
| Smoke diagnostics | Local replay timing remained all zero/untrustworthy. Failure signals still include `small_loop`, `low_builder_progress`, and `travel_without_build`. `builder_max_small_loop_streak` was `338`, `builder_max_no_progress_streak` was `18`, active source ports were `4`, source top1 share `28.2%`, source top3 share `80.7%`, zero-flow tiles `209`, and orphan tiles `76`. |
| g16 report | `.dist/reports/got-any-grapes_batch12_assault_cache_g16_20260417.json` |
| g16 aggregate | `34-14` (`70.8%`), avg TiEq `40,527`, worst `0`; local timing fields all zero/untrustworthy. |
| `jon-6` | `13-3`, avg TiEq `48,691`, worst `100`; seat AB `6-2`, BA `7-1`. |
| `jon-6-a9bfs-surround` | `11-5`, avg TiEq `29,538`, worst `270`; seat AB `5-3`, BA `6-2`. |
| `leeroy-jonkins` | `10-6`, avg TiEq `43,353`, worst `0`; seat AB `5-3`, BA `5-3`. |
| No-edit audit during g16 | Checked cache lifetime, direct caller fallback behavior, `mode_assaulting` and `sentinel_bot` compatibility, profile-counter effects, and execution-model constraints. No direct correctness or coordination bug was found, but the batch did not produce enough local outcome evidence to keep. |
| Decision | Revert Batch 12. It matched Batch 9 aggregate wins but lowered aggregate TiEq (`43,214 -> 40,527`), lowered `a9` TiEq (`31,253 -> 29,538`), lowered `leeroy` wins/TiEq (`12-4`, `50,734 -> 10-6`, `43,353`), and local timing cannot prove the intended runtime gain. |
| Revert validation | Removed the enemy-cache/lazy-sentinel changes and the two focused tests. `py_compile bots/got-any-grapes/assault.py` passed; focused assault slice `3 passed`; full runtime substrate returned to `252 passed`; `git diff --check` clean. |
| Next target | Abandon assault scoring cache reuse for now. Inspect a higher-impact runtime/economy ROI, likely a live SDK-call cache or route-progress fix, before editing. |

#### Batch 13: A* g-cost single-lookup relaxation

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic runtime reduction in `_resume_anytime_astar`, after a true `DEBUG=true DEBUG_TURN_PROFILE=true` fixed `settlement` profile showed repeated TILING_BACK `nav_anytime_ns` slices around `450-660us` while fast perception was usually below `100us` and full perception around `180-280us`. |
| Code changed | Bound `g_costs.get` once per A* slice and changed both conveyor and bridge relaxations from `nb_key not in g_costs or new_g < g_costs[nb_key]` to a single `old_g = g_costs_get(nb_key)` check. |
| Completion surface | No budget, time-check, neighbor ordering, heuristic, bridge policy, obstacle signature, path reconstruction, marker, perception, or mode-transition behavior changed. This is strictly an inner-loop hash-lookup reduction. |
| Pre-smoke bug audit | Inspected `_resume_anytime_astar` conveyor and bridge relaxation paths plus existing planner-state resume tests. A* `g_costs` values are floats and never `None`, so `old_g is None or new_g < old_g` is equivalent to the old membership/index condition. `g_costs` is never rebound after binding `g_costs_get`, so the bound method remains valid for in-place updates. |
| Time-risk checks | Removes one hash lookup on previously-seen neighbors and avoids `__contains__` lookups during relaxation. It may allow slightly more nodes before the unchanged time guard, so smoke/g16 still need behavior checks. |
| Execution-model checks | Pure local computation inside one unit turn. No shared state, marker changes, or non-marker coordination. |
| Tests added | `test_anytime_astar_relaxation_uses_single_g_cost_lookup`, using a counting `dict` subclass to prove the relaxation path uses `get()` rather than `__contains__`. Existing partial/resume/cooldown tests were rerun. |
| Cheap validation | `py_compile bots/got-any-grapes/navigation.py` passed; focused navigation slice `5 passed`; full runtime substrate `253 passed`; `git diff --check` clean for touched files. |
| Local smoke | `USE_GLOBAL_SEED=true cambc run bots/got-any-grapes bots/jon-6 maps/settlement.map26 --seed 204011053 --replay .dist/replays/got-any-grapes_batch13_astar_gcost_settlement_smoke.replay26` won by core destruction on turn `1197`: got-any-grapes `11,011` stored / `37,260` delivered titanium vs jon-6 `21,280` stored / `41,950` delivered. Replay analysis: `.dist/replay_analysis/got-any-grapes_batch13_astar_gcost_settlement_smoke.json`. |
| Smoke diagnostics | Local timing remained all zero/untrustworthy. Failure signals still include `small_loop`, `low_builder_progress`, and `travel_without_build`; `builder_max_small_loop_streak` was `503`, `builder_max_no_progress_streak` was `31`, active source ports were `4`, source top1 share `29.8%`, source top3 share `84.0%`. No new route-collapse signal found. |
| g16 report | `.dist/reports/got-any-grapes_batch13_astar_gcost_g16_20260417.json` |
| g16 aggregate | `28-20` (`58.3%`), avg TiEq `43,297`, worst `0`; local timing fields all zero/untrustworthy. |
| `jon-6` | `10-6`, avg TiEq `53,540`, worst `0`; seat AB `5-3`, BA `5-3`. |
| `jon-6-a9bfs-surround` | `9-7`, avg TiEq `40,318`, worst `750`; seat AB `5-3`, BA `4-4`. |
| `leeroy-jonkins` | `9-7`, avg TiEq `36,033`, worst `2,150`; seat AB `4-4`, BA `5-3`. |
| No-edit audit during g16 | The old two-lookup pattern remained only in the non-runtime full A* helper. Live `_resume_anytime_astar` used the single lookup in both conveyor and bridge relaxations; no direct correctness bug or execution-model issue was found. The behavioral risk was timing drift from extra work under the same guard, which g16 exposed. |
| Decision | Revert Batch 13. The smoke was promising, but g16 collapsed vs the kept Batch 9 baseline (`34-14` -> `28-20`) and materially regressed `leeroy` (`12-4`, avg `50,734` -> `9-7`, avg `36,033`). The tiny aggregate TiEq increase was not robust and did not improve every opponent. |
| Revert validation | Removed the `g_costs.get` relaxation change and its counting-dict test. `py_compile bots/got-any-grapes/navigation.py` passed; focused navigation slice `4 passed`; full runtime substrate returned to `252 passed`; `git diff --check` clean. |
| Next target | Avoid A* timing/order micro-changes for now. The remaining remote-safety ROI likely needs a higher-level bounded-work guard or a concrete no-progress repair that reduces how often expensive TILING_BACK A* is invoked, not just a faster inner loop. |

#### Batch 6: Euclidean ore fallback friend-position reuse

| Item | Finding |
| --- | --- |
| ROI target | Mechanistic allocation reduction in `mode_finding_ore._find_best_ore_target_euclidean`. The fallback converted each visible friendly builder tuple into a `Position` once per ore candidate during deconfliction. |
| Code changed | Added a lazy `friend_positions` list initialized only after the first candidate survives existing filters, then reused across all candidates in the same selection call. Candidate scoring, tie-breaks, access-cache keys, and friend-claim comparisons are unchanged. |
| Execution model | Private call-local cache only; no bot-state persistence, globals, or markers. |
| Invariants checked | No friend-position conversion occurs if no candidate reaches deconfliction; set iteration order is preserved by materializing the list once; Euclidean candidate ordering and claimed-by-friend logic are unchanged. |
| Time-risk check | Avoids repeated `Position` allocations in a fallback path that can run on sparse/blocked maps. Adds at most one list allocation per fallback call, and only when deconfliction is actually needed. |
| Tests | Added `test_euclidean_ore_target_reuses_friend_position_objects`; kept Batch 2 cache-reuse tests. |
| Cheap validation | `py_compile bots/got-any-grapes/mode_finding_ore.py` passed; focused ore-cache/fallback tests `4 passed`; full runtime substrate `247 passed`; diff check clean. |
| g16 report | `.dist/reports/got-any-grapes_euclidean_friend_pos_cache_g16_20260417.json` |
| g16 aggregate | `27-21` (56.2%), avg TiEq `40016.7`, worst TiEq `940`; local timing fields all `0.0%` and not trustworthy timing evidence. |
| `jon-6` | `11-5`, avg TiEq `54396.9`, worst TiEq `2480`; seat split AB `6-2`, BA `5-3`. |
| `jon-6-a9bfs-surround` | `8-8`, avg TiEq `27944.4`, worst TiEq `940`; seat split AB `3-5`, BA `5-3`. |
| `leeroy-jonkins` | `8-8`, avg TiEq `37708.8`, worst TiEq `1630`; seat split AB `3-5`, BA `5-3`. |
| Loop diagnostic from g16 | Every game still had small-loop signal; avg max streaks: `jon-6` `745.8`, `a9` `989.0`, `leeroy` `1054.5`. |
| Decision | Revert. The change is mechanistically safe but too small to justify carrying after a clearly weaker behavior sanity run than Batch 5; no remote timing evidence is available to offset the macro result. |
| Revert validation | Removed the lazy friend-position cache and its test. `py_compile bots/got-any-grapes/mode_finding_ore.py` passed; focused ore/scan tests `6 passed`; full runtime substrate returned to `246 passed`; diff check clean. |
| Next target | Keep Batch 5 as the current retained runtime cleanup. Avoid more tiny ore-fallback micro-optimizations unless they have stronger direct timing evidence. |

### Latest notes (2026-04-17): g16 gate and reporting format

| Item | Current note |
| --- | --- |
| Gating correction | The bot has not passed the local g16 per-opponent bar, so remote r2 runs are premature and should be treated only as non-gating diagnostics. Do not run more remote validation before local g16 clears the studied-opponent bar. |
| Current kept baseline | `explore_target_norm` remains the comparison point for the latest economy/exploration work. |
| Latest rejected batch | `core_visible_ore` was reverted after g16 despite cheap tests passing. It improved narrow core-side ore awareness but regressed pressure matchups and caused map collapses. |
| Reporting preference | Use compact Markdown tables for status reports, winrates, TiEq, validation decisions, timing pressure, and TODOs. Keep caveats visible in prose next to the tables. |

| Report | Aggregate | `jon-6` | `jon-6-a9bfs-surround` | `leeroy-jonkins` |
| --- | ---: | ---: | ---: | ---: |
| Kept baseline: `explore_target_norm` | `31-17` (64.6%), TiEq `45481.7` | `14-2` (87.5%), TiEq `59393.8` | `8-8` (50.0%), TiEq `30904.4` | `9-7` (56.2%), TiEq `46146.9` |
| Rejected: `core_visible_ore` | `30-18` (62.5%), TiEq `39602.9` | `13-3` (81.2%), TiEq `61672.5` | `8-8` (50.0%), TiEq `21283.8` | `9-7` (56.2%), TiEq `35852.5` |

| Decision field | Result |
| --- | --- |
| Attempted batch | Core-visible titanium scan for post-opening spawn bias. |
| Decision | Reverted. |
| Reason | Failed g16 and regressed pressure matchup TiEq, especially `jon-6-a9bfs-surround` and `leeroy-jonkins`. |
| Code left from this batch | None. |
| Commit | None. |

| Priority | TODO |
| ---: | --- |
| 1 | Reduce runtime/TLE pressure without lowering intelligence blindly. |
| 2 | Improve exploration speed and deconfliction without unsafe generic marker spam. |
| 3 | Fix throughput and core-port concentration with replay-grounded mechanisms, not broad load penalties. |
| 4 | Add narrow frontier defense that does not charge a broad defense tax. |
| 5 | Preserve bridge/conveyor pipeline integrity and repair broken first lanes without increasing travel-without-build. |

### Current checkpoint (2026-04-16): bridge/defense/economy g16 loop

- Active strategy: `got-any-grapes` bridge integrity + direct-core economy
  restoration while keeping the core-defense conveyor-destroy invariant.
- Current validation state:
  - The core-lane spread-band and narrower multi-source port-load penalty
    variants both failed g16. Both edits have been removed; cheap validation
    passed: `py_compile bots/got-any-grapes/mode_tiling_back.py`, focused
    core-lane/return-target tests `7 passed`, and full substrate `243 passed`.
- Latest completed g16 evidence:
  - `.dist/reports/got-any-grapes_ore_access_g16_20260416.json`
    - aggregate `33-15` (68.8%), avg TiEq `39779.8`
    - `jon-6`: `13-3` (81.2%), avg TiEq `65217.5`
    - `jon-6-a9bfs-surround`: `9-7` (56.2%), avg TiEq `23045.0`
    - `leeroy-jonkins`: `11-5` (68.8%), avg TiEq `31076.9`
  - `.dist/reports/got-any-grapes_core_slot_target_g16_20260416.json`
    was a genuine regression after changing the path target to the core
    approach slot: aggregate `25-23` (52.1%), `jon-6` fell to `10-6`.
    Keep the lesson, not that shape.
  - `.dist/reports/got-any-grapes_core_exit_accepts_coretarget_g16_20260416.json`
    completed mixed/regressive: aggregate `27-21` (56.2%), avg TiEq `44003.8`;
    `jon-6` `9-7` avg TiEq `39636.9`; `a9` `9-7` avg TiEq `45204.4`;
    `leeroy` `9-7` avg TiEq `47170.0`.
  - Replay-analysis assessment, not a blind revert call:
    - The change improved delivered titanium in the embedded report summaries
      for `jon-6` and `a9`, and increased early core kills for `a9`/`leeroy`,
      but it collapsed `jon-6` early core kills from `7` to `2` and flipped
      several previously won `jon-6` maps (`default_small2`, `donut`,
      `flowers`, `labyrinth`, `default_large1` BA) into tiebreak losses.
    - Latest detailed replay analysis does not support "bridges disappeared" as
      the primary cause: bridge placements still appear on bridge-heavy maps.
      The stronger current failure signals are no turret fire in several losses,
      zero active source ports on some losses, high zero-flow/orphan/dead-end
      conveyor counts, travel-without-build, and core-port concentration.
    - Old report `analysis_path` files are overwritten by later
      `benchmark_matrix.py` runs because the paths are stable names under
      `.dist/replay_analysis/`. Cross-run detailed replay comparisons must use
      archived per-run analysis files or embedded report metrics only.
- Current code hypothesis under review:
  - Preserve the old core-tile target for bridge/direct-core planning unless
    replay analysis shows a narrower final-exit fix that does not reduce
    `jon-6` core pressure.
  - Do not treat the failed core-target-completion smoke as proof that bridge
    placement is broken; inspect route integrity, offense supply, and frontier
    defense failures directly.

#### Confirmed audit bugs to address after the current smoke

Exploration speed:
- `mode_exploring.py` parses `EXPLORE_CLAIM` markers through perception, but no
  live code publishes explore-claim markers. Exploration deconfliction is
  therefore only local-visibility based (`bot.bot_locations`), so builders
  outside each other's vision can still duplicate frontier chunks.
- `mode_exploring._get_chunk_center()` targets the geometric chunk center
  without validating that the tile is passable/reachable. After only
  `EXPLORE_STUCK_RETRY_TURNS = 4` stalled moves, `execute()` blacklists the
  entire chunk. On wall/ore-centered chunks this can mark useful frontier as
  unreachable and slow map coverage.
  - Implemented normalization batch: target selection now resolves the selected
    chunk to a viable in-chunk tile when the center is visibly blocked, and
    stalled exploration retargets within the same chunk before blacklisting the
    whole chunk. Cheap validation: exploration-focused tests `5 passed`; full
    substrate `241 passed`.
- Assault/frontier scouting has the same unknown-tile weakness:
  `mode_assaulting._is_viable_scout_staging_tile()` treats tiles with missing
  grid data or missing `env` as viable. `_select_enemy_half_frontier_target()`
  can therefore cache a chunk-center target that later turns out to be a wall,
  ore, or blocked terrain, causing travel without useful discovery before the
  target is normalized or abandoned.

Conveyor/bridge pipeline integrity:
- `_complete_tiling_back_or_wait_for_verification()` waits at a presumed route
  endpoint and then calls `_abandon_tiling_back()` after 12 turns if the local
  delivery graph is not verified. It does not identify or repair the first
  broken edge in the just-built route. Current zero-delivery losses show many
  conveyors/roads with zero active core source ports, consistent with partial
  routes being abandoned instead of locally repaired.
  - Implemented candidate repair batch: after verification timeout, a
    HARVESTER-origin route now gets one private-state repair attempt. The
    builder selects the deepest locally observed broken transport edge from
    the harvester, walks back to that repair seed without laying reverse
    conveyors, then resumes normal TILING_BACK toward the current return
    target. If it cannot reach the seed within 12 stalled repair turns, it
    falls back to the existing abandon/blacklist path.
  - Cheap validation: `py_compile bots/got-any-grapes/mode_tiling_back.py`;
    focused route-completion tests `5 passed`; full
    `tests/test_got_any_grapes_runtime_substrate.py` `238 passed`.
  - Pending validation: `USE_GLOBAL_SEED=true` g16 smoke against `jon-6`,
    `jon-6-a9bfs-surround`, and `leeroy-jonkins`, then replay analysis of
    zero-flow/orphan/dead-end/TWB/core-port signals.
  - g16 result for first repair batch:
    `.dist/reports/got-any-grapes_route_repair_g16_20260416.json` regressed:
    aggregate `27-21` (56.2%), avg TiEq `36023.8`; `jon-6` `11-5` avg
    TiEq `41495.6`; `a9` `7-9` avg TiEq `27500.0`; `leeroy` `9-7` avg
    TiEq `39075.6`.
  - Replay-analysis decision: revise, not blind revert. The batch reduced
    average zero-flow/orphan/dead-end counts mostly by building fewer total
    lanes, but it also cut live-harvester/economy output for `a9` and
    `leeroy` and did not restore `jon-6` core-kill pressure. Likely failure
    mode: verification timeout can send a builder walking back to a shallow or
    empty harvester-adjacent "repair" seed, creating more travel-without-build
    and delaying the next ore target. Next revision should only repair when
    the private graph shows a meaningful partial route before the break.
  - Revision applied: repair candidates now require at least two remembered
    transport steps before the broken edge. Shallow/no-route verification
    failures use the old abandon/blacklist path instead of sending the builder
    back to the harvester. Cheap validation: focused route-completion tests
    `6 passed`; full substrate `239 passed`.
  - g16 result for min-prefix repair:
    `.dist/reports/got-any-grapes_route_repair_minprefix_g16_20260416.json`
    remains below target: aggregate `29-19` (60.4%), avg TiEq `43574.0`;
    `jon-6` `9-7` avg TiEq `43076.2`; `a9` `10-6` avg TiEq `40513.8`;
    `leeroy` `10-6` avg TiEq `47131.9`.
  - Decision: keep as current working base while fixing the next economy
    bottleneck, not because it is promotion-worthy. It improves `a9`/`leeroy`
    TiEq and core-kill pressure vs ore-access, but `jon-6` regresses because
    several old core kills (`default_small2`, `settlement`, `shrub`) became
    slower tiebreak games and map losses (`chess`, `donut`, `flowers`) still
    show small loops, travel-without-build, and core-port concentration.
- The old core-slot target mismatch is confirmed: core-lane slot assignment
  stored both an approach slot and paired core tile, while final-exit helpers
  only recognized the approach-slot target. The lane-slot-target attempt
  regressed, so the current test preserves the core-tile planner target and
  broadens final-exit completion instead.

Throughput optimization:
- `core_bot._get_directions_toward_ore()` has an ore-biased post-opening spawn
  path, but the core only learns ore from ore markers and live builders call
  `_share_ore_marker()` through `utils.place_marker_around()`, which currently
  returns `False` unconditionally. Result: the core's spawn rotation is mostly
  blind after the opening, even when builders have found titanium. This is a
  plausible jon-6 economy gap because we pay the defense tax while later
  builders are not steered toward known Ti lanes. Do not blindly re-enable
  generic markers; they previously regressed badly by occupying construction
  tiles. Any fix must use safe marker placement or a different core-visible
  signal.
  - Attempted narrow core-visible titanium scan in `CoreBot.run()` so the
    existing spawn bias could use ore in core vision without enabling generic
    markers. Cheap validation passed (`py_compile`, targeted core-spawn tests,
    full substrate `244 passed`) but g16 regressed and the edit was reverted:
    `.dist/reports/got-any-grapes_core_visible_ore_g16_20260416.json` =
    aggregate `30-18` (62.5%), `jon-6` `13-3` avg TiEq `61672.5`,
    `a9` `8-8` avg TiEq `21283.8`, `leeroy` `9-7` avg TiEq `35852.5`.
    Compared with `explore_target_norm`, it lost one aggregate win, cut
    delivered Ti for `jon-6`/`a9`, and caused large map collapses
    (`donut`, `default_large1`, `shish_kebab`, `bar_chart`). Lesson: core-side
    ore bias alone can create clumping/fragile spawn steering; solve this with
    safer distributed exploration/claims or route-health signals instead.
- `RETURN_TARGET_HYSTERESIS = 3` is defined in `mode_tiling_back.py` and the bot
  explainer says return-target switching uses hysteresis, but live
  `_update_return_target_while_tiling()` switches to a conveyor target whenever
  `conveyor_score < best_score`. The intended hysteresis is not enforced,
  which can cause target churn and redundant lanes.
  - Implemented bounded hysteresis batch: switching from core to conveyor now
    requires the conveyor score to beat the core score by at least
    `RETURN_TARGET_HYSTERESIS`, while forced direct-core and forced
    core-approach-full merge behavior are unchanged. Cheap validation:
    focused return-target/direct-core tests `6 passed`; full substrate
    `243 passed`.
  - First two-sided hysteresis g16:
    `.dist/reports/got-any-grapes_return_hysteresis_g16_20260416.json`
    was mixed/regressive: aggregate `31-17` (64.6%), avg TiEq `43489.4`;
    `jon-6` fell to `11-5` avg TiEq `52373.8`; `a9` improved to `10-6`
    avg TiEq `40833.1`; `leeroy` improved to `10-6` avg TiEq `37261.2`.
    Replay analysis suggested the harmful part was retaining an existing
    conveyor target after the core became slightly better, reducing `jon-6`
    core pressure.
  - Revision applied: hysteresis is now one-sided. It only blocks a
    marginal core -> conveyor switch; an existing conveyor target is not pinned
    when the core becomes better. Cheap validation after revision: focused
    return-target/direct-core tests `6 passed`; full substrate `243 passed`.
  - One-sided hysteresis g16:
    `.dist/reports/got-any-grapes_return_hysteresis_onesided_g16_20260416.json`
    was a genuine detriment: aggregate `28-20` (58.3%), avg TiEq `37148.3`;
    `jon-6` `11-5` avg TiEq `43403.8`; `a9` `8-8` avg TiEq `23798.1`;
    `leeroy` `9-7` avg TiEq `44243.1`. Replay metrics showed fewer active
    source ports for `a9`/`leeroy`, repeated zero/one-port losses, high
    travel-without-build, and core-port concentration. Decision: revert the
    hysteresis behavior to the pre-batch strict `conveyor_score < core_score`
    selector and keep the bug as unresolved rather than forcing a weaker
    heuristic. Revert validation passed: focused return-target/direct-core
    tests `6 passed`; full substrate `243 passed`.
- Core-port concentration remains a confirmed replay failure signal across
  current smokes. The live slot scorer has a `port_load * 4` penalty but no
  hard per-port saturation cap, no splitter/parallel-lane plan, and no repair
  behavior when a direct-core lane ends as a zero-flow/orphan port stub.
  - Implemented bounded core-lane spread-band batch: `_assign_core_lane_slot()`
    now scores route cost and penalties first, then uses the existing
    owner-id slot hash only within a one-tile near-equivalent band. Known
    connected port load now keeps the historical cost for one source but grows
    superlinearly for multi-source ports. This targets same-side concentration
    without expanding the rejected `slot_count * 3` spread multiplier and
    without adding broad connected-load penalties.
  - Cheap validation: same-side origin distribution contract, port-load penalty
    contract, return-target/direct-core focused slice `9 passed`, full
    substrate `245 passed`.
  - g16 result for spread-band scorer:
    `.dist/reports/got-any-grapes_core_lane_spreadband_g16_20260416.json`
    failed: aggregate `25-23` (52.1%), avg TiEq `46458.5`; `jon-6`
    collapsed to `7-9` avg TiEq `46695.6`; `a9` improved to `10-6`
    avg TiEq `50153.1`; `leeroy` fell to `8-8` avg TiEq `42526.9`.
    Replay analysis showed the preemptive band changed early direct-core lane
    geometry before any load evidence existed, hurting the pure-econ matchup,
    while core-port concentration still appeared in most losses. Decision:
    revise, not keep.
  - Revision applied: remove the preemptive spread band and restore the old
    `distance + spread_offset + penalties` selector for zero-load ports. Keep
    only the multi-source load penalty helper, which is inert until a builder
    sees a connected port carrying more than one source. Cheap validation:
    focused core-lane/return-target tests `8 passed`; full substrate
    `244 passed`.
  - g16 result for load-penalty-only revision:
    `.dist/reports/got-any-grapes_core_port_loadpen_g16_20260416.json`
    failed: aggregate `29-19` (60.4%), avg TiEq `42685.0`; `jon-6`
    `10-6` avg TiEq `49015.0`; `a9` `8-8` avg TiEq `29558.8`;
    `leeroy` `11-5` avg TiEq `49481.2`. Replay metrics showed some lower
    average `jon-6` top1 port share, but zero-port/one-port losses,
    travel-without-build, and core-port concentration remained, while
    `jon-6` and `a9` stayed below the current best. Decision: revert the
    remaining port-load change and leave core-port concentration unresolved
    for a different, replay-grounded mechanism. Revert validation passed:
    focused core-lane/return-target tests `7 passed`; full substrate
    `243 passed`.

Frontier defense:
- `defense.defend_lane_if_needed()` exits when the builder is more than
  `LANE_CORE_RESPONSE_RADIUS_SQ = 49` from the core. This means frontier
  harvesters and long lanes outside radius 7 receive no lane-defense sentinel
  response, even when a local builder can see the asset and the threat.
  - Attempted frontier response batch, then reverted after g16:
    `.dist/reports/got-any-grapes_frontier_defense_g16_20260416.json`
    regressed to aggregate `27-21` (56.2%), `jon-6` `10-6`, `a9` `8-8`,
    `leeroy` `9-7`. Replay metrics showed higher sentinel/defense tax and
    no-progress/TWB pressure without improved matchup wins. The bug remains,
    but the broad "remove core-distance gate" shape is rejected. Post-revert
    validation: defense-focused tests `17 passed`; full substrate `241 passed`.
- The proactive builder-threat branch is also core-side only via
  `max_asset_core_dist_sq=LANE_PROACTIVE_ASSET_CORE_RADIUS_SQ`. Frontier
  enemy builders can stand next to a harvester/conveyor before visible damage
  is refreshed without triggering proactive defense.

### Current checkpoint (2026-04-16): travel-without-build recovery batch

- Active strategy: `got-any-grapes` focus on removing travel-without-build (TWB)
  loopers in `FINDING_ORE` without weakening direct-core economy.
- Task objective: implement a bounded build-failure recovery when an ore target
  cannot be harvested after repeated adjacent attempts, then validate locally.
- Success criteria for this batch:
  - no state-model violations (private bot state + marker-only comm preserved),
  - targeted tests pass,
  - TWB events decline in replay traces when candidate builders hit blocked ore targets.
- Evidence baseline before this batch:
  - STATUS baseline logged `56-119` TWB events across typical games,
  - status report confirms this remains dominant in multiple maps.
- Evidence after this batch:
  - added build-failure streak tracking keyed by `(ore, access)` with 3-attempt
    escalation,
  - added escalating ore blacklist handoff on repeated adjacent build failures,
  - kept successful harvester-connect and progress branches clearing fail-streak state,
  - added three focused regression tests for streak escalation, reset, and execute-level
    abandon.
- Immediate next action: keep this batch intact and run a controlled local smoke
  or full runtime cohort for `got-any-grapes` only if the new failure-mode edge
  cases show no side effects in gameplay traces.
- Compaction-safe resume point: after this turn, rerun
  `pytest -q tests/test_got_any_grapes_runtime_substrate.py` (already passing), then
  plan local `g16`/remote `r2` once full bug-finding is complete.

### Earlier checkpoint (2026-04-16): comprehensive bug fix pass

- Active strategy: delta perception + strategic bug fixes + defense tuning.
- Local g16 (USE_GLOBAL_SEED): **35-13 (72.9%)** session best.
  `jon-6` **12-4 (75.0%)**, `a9` **12-4 (75.0%)**, `leeroy` **11-5 (68.8%)**.
- Remote r2 timing (with all fixes): avg **25.9% >2ms** (down from 53.2%).
  Simple maps show 0.1-1.2% >2ms. Complex maps still 60-90% >2ms (A* + topology
  dominate, not perception).

**Changes committed this session (15+ fixes):**

Mechanistic / timing:
- Delta perception (spatial deferral for full scans): entered + safety ring are
  fresh, persisted tiles reuse cached grid data. ~50% fewer SDK calls per full scan.
- Delta entity clearing order fix: clear stale unit fields BEFORE _update_master_grid
  so fresh get_nearby_units data (including enemy sentinels) is preserved.
- Reduced TILING_BACK fast scan radius (9 → 2).
- Inlined direction deltas in _refresh_local_obstacle_memory.
- Removed depths dict from anytime A*.
- Topology reverse_links built as sets directly.
- Reverted obstacle fingerprint len-only (caused false A* signature matches).
- scan_micro() function (available, not called in current routing).
- FINDING_ORE A* budget increased (180/350μs → 250/500μs).
- SDK-verify conveyor merge to prevent phantom pipeline completion.

Strategic:
- Defender active healing (moves toward damaged buildings within leash).
- Defender demotion after 80 turns (clears stale state on transition).
- Hijack gate strengthened (4+ connected transports, positive load, Ti reserves).
- Removed RESOURCE_MAX_SPAWN_BUILDER cap.
- EXPLORING → FINDING_ORE only when unclaimed ore exists.
- Lane defense fires BEFORE healing (sentinels > heal against sentinels).
- DIRECT_CORE_RETURN_MAX_DIST 18 → 12 (more pipeline merges).
- Port load penalty in core lane slot scoring (4 × load_count).
- ECON_STALL_RESET_INTERVAL 150 → 100.
- LANE_THREAT_RADIUS_SQ 9 → 18 (covers sentinel fire range).
- Assault → economy transition clears stale state.
- Explorer stays in EXPLORING on chunk arrival when no ore known.
- S31 v2: never-connected harvester retile with enemy/distance gates (testing).
- 8 new maps extracted from remote replays.

**Remaining known bugs (not yet fixed):**

Mechanistic / performance:
- Bug 6: `_is_ore_claimed_by_friend` creates fresh access_cache per BFS call
  instead of reusing across candidates. Performance-only, low impact.
  (mode_finding_ore.py:368)
- Bug 13-16: Assault opening escape BFS creates Position objects in the hot loop
  (49 nodes × 8 directions × Position.add). Takes 1-2.4ms locally / 3-12ms
  Graviton. Double BFS (_shell_exit_target + _shell_escape_route) could merge.
  _opening_escape_direction_order calls _in_spawn_shell 8× per node.
  Complex refactor, separate batch. (mode_assaulting.py:401-469)
- Danger zone around enemy sentinels is 3×3 (1 tile each direction) but sentinel
  fire range is ~5.7 tiles along facing direction. Builders approaching along the
  fire line from 4+ tiles aren't in the danger zone. Fix would need directional
  danger zones using sentinel facing info. (perception.py:962-977)

Strategic:
- S27: `_is_ore_claimed_by_friend` doesn't account for friend's MODE. A friend
  in TILING_BACK near ore "claims" it via distance deconfliction even though it's
  heading to the core, not the ore. Needs inter-builder communication (markers)
  or mode-awareness approximation. (mode_finding_ore.py:365-391)
- S31: Never-connected harvester retile: v1 (round 120, no gates) regressed
  leeroy 43.8%; v2 (round 200, enemy+distance gates) under test.
  (mode_finding_ore.py:664-673)
- No pipeline completion verification: after TILING_BACK completes, the builder
  never checks if titanium is actually flowing. A route with a directional error
  at one tile stays broken forever unless the retile system catches it (which
  requires prev_adjacent_conveyors > 0). (mode_tiling_back.py:1892-1904)
- `_recheck_claimed_harvesters` uses stale `_has_adjacent_conveyor` which reads
  `connected_friendly_conveyors` — on delta turns this may be stale, causing
  unnecessary unclaim/retile cycles. (mode_finding_ore.py:701-726)
- `_is_visible_current_round` in mode_hijacking checks `last_seen == current_round`
  — on delta perception turns, persisted tiles have `last_seen` from a previous
  turn. Hijack targets on persisted tiles appear invisible even though they're
  still in view. (mode_hijacking.py:93-100)
- `main.py` line 11: `random.seed(1)` always pins the global random state to
  seed 1 unless USE_GLOBAL_SEED overrides it. This makes the core's spawn
  rotation deterministic across all non-USE_GLOBAL_SEED games. Opponents could
  fingerprint the fixed rotation order. (main.py:11)

**Rejected ideas (with evidence):**
- Pure micro perception (unit-only scan, no grid updates): 8.3% g16 — stale
  obstacles caused permanent A* stalls.
- Obstacle fingerprint len-only: remote 8-22 — false signature matches.
- Three-tile small-loop threshold: collapsed jon-6 locally.
- Target-aware small-loop recovery: collapsed all opponents locally.
- Opening fast-perception grace: collapsed a9 locally.
- S31 v1 retile (round 120, no enemy gate): leeroy 43.8% regression.

**Failure mode analysis (2026-04-16 g16 diagnostic):**

Two g16 runs of the SAME code gave 33-15 (68.8%) and 29-19 (60.4%). The 4-win
swing comes from `time.time_ns()` budget cuts in A* producing different paths
on each run. Leeroy is most timing-sensitive: 12-4 vs 8-8 across runs.

Per-game diagnostic findings:

1. **bear_of_doom LOSS (21×21, 441 area):** 16 harvesters but only 56 conveyors
   (3.5 C/H). All harvesters do direct-core routes (map is ≤12 manhattan) that
   converge on the same 2-3 approach slots. Port congestion: 16 harvesters ×
   ~10 Ti/round through ~3 slots at 10 Ti/round each = 53 Ti/round demand on
   30 Ti/round capacity. 43% of production sits as backpressure. Opponent uses
   17 harvesters with 21 conveyors (1.2 C/H) — ultra-short routes with no
   congestion. FIX DIRECTION: on small maps, cap the number of active harvesters
   per core port to avoid congestion, or use splitters to multiply port capacity.

2. **Travel-without-build epidemic:** 56-119 TWB events per game across ALL maps.
   Top offenders (bear_of_doom Units 694/1063) have 34-38 TWB events = ~270-300
   turns of walking without building. These are FINDING_ORE builders that reach
   ore access points but can't build harvesters (insufficient Ti, all access
   points blocked by obstacles, or ore deconflicted away from them). They walk
   to the next ore, fail there too, walk to the next. IMPACT: ~15% of all
   builder turns are TWB — pure waste. FIX DIRECTION: when a builder fails to
   place a harvester 3+ times in succession, switch to EXPLORING to discover
   new ore rather than cycling between the same known-but-unclaimable targets.

3. **62-76% no-progress rate persists:** Improved from the session-start 50-67%
   but still very high. The small-loop recovery (SMALL_LOOP_BREAK_THRESHOLD=12)
   fires but builders immediately re-select the same target. The stall reset
   at 100 turns helps but most stuck builders are stuck for 100-200 turns
   between resets. Core issue: builders exhaust nearby ore, enter EXPLORING,
   explore nearby chunks (all already explored), and cycle without discovering
   new ore.

4. **Conveyor efficiency inversely correlates with harvester count:** spikes
   (8 H, 18.6 C/H, 4201 xfer/H) vs bear_of_doom (16 H, 3.5 C/H, 2194 xfer/H).
   More harvesters with shorter routes produce LESS per-harvester throughput due
   to port congestion. Optimal harvester count depends on port capacity.

5. **Run-to-run noise is ±4 wins (±8%) from A* timing variance.** The
   `time.time_ns()` guard in A* (`A_STAR_TIME_GUARD_NANOSECONDS = 400_000`)
   terminates at different points in the search on each run. This changes path
   quality, which cascades into route layout, port selection, and economy. The
   noise is irreducible without removing the time guard (which would cause TLE).

**Compaction-safe resume point:** all fixes committed. S31 v2 committed.
Next ROI targets:
- Assault opening escape optimization (Bug 13-16) — biggest single-builder TLE
- Perception age threshold to replace fixed full-scan intervals
- Pipeline completion verification after TILING_BACK
- Port congestion mitigation (splitters, per-port harvester caps)
- TWB epidemic fix (fail-to-place → EXPLORING transition)
