# CODEX Scratchpad

## Active Long-Form Task

Iterate on `bots/got-any-grapes/` vs studied opponents `jon-6`,
`jon-6-a9bfs-surround`, and `leeroy-jonkins`. Current strategic focus is
defense against (1) early offense (Tootill Labs / 4 buffons style) and
(2) sustained disruption (`leeroy-jonkins`, `a9bfs-surround`, `laapa
chondey`), while preserving a relative economy large enough to fund
offense. Direct-core economy stays in. Markers are the only legal
cross-unit communication.

### Current checkpoint (2026-04-13): first-lane repair / hot-path investigation

- Active strategy name: bounded first-lane completion and local route repair,
  with mechanistic hot-path reductions accepted only when they preserve
  current behavior.
- Task description: inspect live `got-any-grapes` code and implement one
  coherent batch that improves delivered titanium on mined-but-not-delivered
  failure maps, especially `metropolitan_dystopia`, without removing the
  direct-core engine or adding illegal shared coordination.
- Criteria: cheap tests first, then deterministic smoke, then
  `USE_GLOBAL_SEED=true` g16 only if the change batch is complete and
  offline review finds no obvious bug. Treat deltas smaller than ±4 g16 wins
  as noise unless supported by strong mechanistic evidence. Do not remote test
  before local g16 is at least not clearly worse and timing risk is acceptable.
- Latest evidence: best current USE_GLOBAL_SEED g16 remains
  `.dist/reports/got-any-grapes_corerush_fixed_g16_20260413.json`
  at **29-19 / 60.4%**, with catastrophic zero/near-zero TiEq maps still
  present. `metropolitan_dystopia` mined 18k Ti but delivered 577, pointing to
  route completion / TILING_BACK execution failure rather than ore discovery.
- Immediate next action: read live `builder_bot`, `mode_tiling_back`,
  `navigation`, `perception`, and existing tiling tests; define the smallest
  full batch that can repair missing road/conveyor segments or stale route
  progress without broad scans or fake shared state.
- Compaction-safe resume point: continue from the live code inspection for
  first-lane completion. Preserve user edits outside `bots/got-any-grapes/`,
  and do not benchmark until helper/caller/tests/review are complete.

### Current checkpoint (2026-04-13): directed-fed defense sentinel batch

- ROI target and rationale: custom remote replay audit showed defense
  sentinels were often not supplied. In 10 downloaded recent remote games
  (`faf09699...` vs leeroy and `c0293184...` vs a9), our bot built
  **21** sentinels; **19/21** had no directed feed at build time under the
  first same-team-transport audit, and **12/21** never received ammo or
  fired. Concrete failures included sentinels beside conveyors whose next
  tile was elsewhere, e.g. leeroy/wall sentinel at `(7, 26)` next to
  conveyor `(7, 27)` directed east to `(8, 27)`, and leeroy/cold sentinels
  at `(15, 19)` / `(7, 13)` beside conveyors that did not feed them.
- Full retained change batch scope: `defense._sentinel_supply_class` now
  treats adjacent harvesters as valid immediate ammo sources, enemy
  transports as valid only when their actual output points into the
  sentinel tile, and friendly transports as valid only when their actual
  output points into the sentinel tile. Mere adjacency to a connected
  conveyor no longer counts as supply.
- Cheap tests added: focused tests for rejecting non-feeding adjacent
  transports, accepting enemy transport directed into the sentinel,
  accepting directed friendly transport branches, and skipping the exact
  unfed-connected-conveyor core defense case.
- Rejected sub-variant: source-aware suppression of unconnected friendly
  directed branches. It preserved the no-side-adjacent invariant but
  collapsed clean g16 to **21-27 / 43.8%** overall (`jon-6` **9-7**,
  a9 **7-9**, leeroy **5-11**) and made `wall` vs leeroy build **0**
  sentinels; reverted to the narrower directed-feed gate.
- Cheap validation of retained batch: targeted defense tests **7 passed**;
  runtime substrate + replay analyzer **160 passed**; compileall passed;
  tiling subset **6 passed**. Deterministic `default_small1` seed 1 vs a9
  won **9513 Ti vs 11**. Deterministic `wall` seed 1 vs leeroy still lost
  (**2868 Ti vs 7013**), so this is not a wall/first-lane fix.
- Clean isolated `USE_GLOBAL_SEED=true` g16:
  `.dist/reports/got-any-grapes_directed_sentinel_supply_isolated_g16_20260413.json`,
  **30-18 / 62.5%**, avg TiEq **31,667**, worst **0**; `jon-6` **9-7**
  avg **31,886**, a9 **11-5** avg **30,673**, leeroy **10-6** avg
  **32,442**. vs reference **29-19 / 60.4%**: overall **+1**, a9 **+2**,
  leeroy **+1**, jon-6 **-2**. This is within noise on aggregate but has
  strong mechanistic rationale and improves both user-priority offensive
  matchups.
- Post-run local replay audit of this g16 found candidate sentinels at build
  time: `jon-6` **70/70 fed**, a9 **85/85 fed**, leeroy **96/96 fed**;
  `side_transport_only` examples **0**. This audit counts any adjacent
  harvester as feed and any adjacent transport only when its actual next tile
  is the sentinel tile.
- Immediate next action: keep this batch. Next ROI should not be "fewer
  sentinels"; it should be either (a) staged supply construction for maps
  where no fed sentinel tile exists yet, or (b) return to timing hot paths
  such as fast-perception metadata reuse and optional marker gating.

### Current checkpoint (2026-04-13): fast-perception SDK-call reduction

- ROI target and rationale: remote replay timing still shows builder-heavy
  TLE pressure, while local replay `execTimeUs` remains all-zero. Live
  `_scan_local_fast` re-queried stable building metadata every fast turn
  (`get_entity_type`, `get_team(id)`, `get_direction`, bridge target), even
  though the full snapshot path already reuses type/team/direction by stable
  `building_id`. This is a pure mechanistic Graviton-risk reduction.
- Full change batch scope: `_scan_local_fast` now captures cached building
  metadata before clearing dynamic tile fields. If the visible
  `building_id` matches the cached id and cached type/team exist, it reuses
  type/team plus cached direction/bridge target, re-reading only HP/max HP
  when requested. Fast marker scanning also now uses the same
  `PERCEPTION_OPTIONAL_NS` timing gate as full scans; when the hard budget
  is already tight, marker decoding waits for a later perception turn.
- Invariants checked: no new shared state, no marker communication changes
  when time budget is healthy, dynamic HP is still refreshed, changed
  building ids still fall back to SDK metadata reads, and marker skipping
  only happens under the existing optional-work budget gate.
- Tests added: fast-perception cached metadata reuse test and fast-marker
  time-gate test. The reuse test asserts type/team/direction SDK calls are
  skipped for stable ids while HP/max HP still read; the marker-gate test
  asserts `get_marker_value` is not called under an expired governor.
- Cheap validation: fast-perception test subset **5 passed**; runtime
  substrate + replay analyzer **162 passed**; compileall passed; tiling
  subset **6 passed**; diff check passed. Deterministic `default_small1`
  seed 1 vs a9 won by core destruction on turn 1655 (**5307 Ti vs 1295**).
- Clean `USE_GLOBAL_SEED=true` g16:
  `.dist/reports/got-any-grapes_fast_perception_g16_20260413.json`,
  **28-20 / 58.3%**, avg TiEq **29,424**, worst **0**; `jon-6` **12-4**
  avg **37,202**, a9 **8-8** avg **17,895**, leeroy **8-8** avg
  **33,175**. Compared with sentinel-only **30-18**, this is **-2** wins
  and inside the known ±4 local timing noise band; compared with the
  pre-batch reference **29-19**, it is **-1** overall. Keep for
  mechanistic timing rationale, but do not claim macro improvement.
- Immediate next action: if continuing locally, prefer staged fed-sentinel
  construction or first-lane route repair. If validating timing remotely,
  keep replay downloads bounded and compare builder `% >0.5/1/1.5/2ms`
  against Tier 1/Tier 2 remote pressure.

### Current checkpoint (2026-04-13): score-tuple audit + corerush fix

- HEAD: `07af436 STATUS: log score-tuple audit findings + corerush fix g16 result`.
- Best USE_GLOBAL_SEED g16 of the session:
  `.dist/reports/got-any-grapes_corerush_fixed_g16_20260413.json`,
  **29-19 / 60.4%**, avg TiEq **28,099**, worst **0**;
  `jon-6` **11-5** avg **32,833**, `a9` **9-7** avg **20,390**,
  `leeroy` **9-7** avg **31,076**. Total core destructions 3.
- Timing noise floor: USE_GLOBAL_SEED fixes the spawn-rotation shuffle
  but does NOT remove timing-driven A*/navigation non-determinism. Two
  manual cambc reproductions of the same seed on `cold` gave 19553 vs
  15799 delivered Ti. Treat g16 deltas smaller than ±4 wins as noise.

### Retained features added this session

- Cardinal-spawn role assignment in `core_bot._spawn_random_around`:
  first 4 economy builders spawn in fixed order `NORTH, EAST, SOUTH,
  WEST`. `BuilderBot._init_turn` derives role from
  `spawn_pos - core_pos`: N/S → ore finder, E → defender
  (`is_defender_role`), W → core rusher (`is_assault_role=True` +
  `is_core_rusher=True` + `ASSAULTING` mode). Opening assault rounds
  `{5, 6}` are unchanged.
- Defender hold-near-core fallback:
  `mode_finding_ore.execute` no-ops in place for defenders instead of
  transitioning to `EXPLORING` when no ore target is found. Keeps a
  reactive responder inside `CORE_PORT_RESPONSE_RADIUS_SQ`. Tested
  revert-ablation: defender removal collapsed a9 **8-8 → 4-12**.
- Symmetry-aware core rusher with `core_dist` as TIEBREAKER (not
  primary): `assault.choose_best_visible_assault_site` accepts
  `core_rusher_anchor`, and `mode_assaulting._best_visible_site` threads
  `bot.enemy_core_anchor` (populated from `WORLD_ORIENTATION` markers
  or visible enemy-core inference) only for core rushers. `core_dist`
  is tuple position 7, after `manhattan`, so it tiebreaks among
  equivalent sites — prior leading-key bug dominated all other terms
  and cost ~7 g16 wins (commit `0f181cb`).
- Core port barrier cap `MAX_VISIBLE_CORE_PORT_BARRIERS` raised 1 → 2.
- Responsive defense (`defense.defend_lane_if_needed`): TILING_BACK
  mode added to allowed responders; `MAX_VISIBLE_LANE_DEFENSE_SENTINELS`
  is adaptive, scaling to `min(2, enemy_count + 1)` when the enemy
  stacks sentinels in the same lane. Both changes ship together —
  TILING_BACK alone collapsed a9; adaptive cap alone was slower.
- Exploration dispersion: `mode_exploring.EXPLORE_ALLY_CLOSER_PENALTY`
  relaxed 1000 → 5 so the per-chunk score band no longer saturates and
  randomizes; `spread_hash` multiplier raised 0.001 → 0.02 for stable
  per-builder tiebreaks.
- TLE/mechanistic: `_visible_lane_sentinel_counts(bot, ct, asset_pos)`
  replaces two separate `visible_positions` iterations in
  `defend_lane_if_needed` with a single pass returning
  `(friendly, enemy)`; `distance_squared` inlined to avoid Position
  construction in the hot loop.
- `USE_GLOBAL_SEED` diagnostic (default off so deployed bots stay
  non-deterministic): when set, `core_bot.__init__` re-seeds
  `random` from the cambc per-game seed parsed out of `sys.argv` via
  `utils.cambc_game_seed_from_argv()` (handles `--seed N` and
  `--seed=N`). `GLOBAL_SEED_VALUE` env var overrides with a fixed int
  when reproducibility across games is needed.
- Lexicographic score-tuple audit of the rest of `got-any-grapes`:
  `assault.choose_best_site_for_harvester`,
  `mode_assaulting._best_recent_anchor`, `_best_predicted_scout_anchor`,
  `_best_scout_staging_target`, and
  `mode_tiling_back._assign_core_lane_slot` all use healthy structures
  (leading boolean primaries or weighted scalar penalty sums). No
  other leading-domination bug found.

### Rejected / reverted this session

- Symmetry rusher with `core_dist` as leading score key (the bug fixed
  by `0f181cb`). Under USE_GLOBAL_SEED the buggy variant scored
  **22-26 / 45.8%**, rusher-disabled ablation scored **22-26 / 45.8%**,
  fix scored **29-19 / 60.4%**.
- `spread_offset` multiplier expansion from `slot_count` to
  `slot_count * 3`. Improved `metropolitan_dystopia` vs leeroy smoke
  577 → 19,315 delivered, but g16 collapsed to **18-30 / 37.5%** with
  leeroy **8-8 → 4-12**. Port diversification needs a different
  mechanism.
- Removing the defender no-EXPLORING fallback (a9 collapses).
- Ti-floor gate on `core_port_guard` underfoot fire (commit
  `0c4545d`, lost a9/leeroy harassment fire).

### Known catastrophic failure maps (zero / near-zero TiEq losses)

`cold` (vs leeroy, vs a9 partially), `donut`, `git_branches` (vs a9),
`pls-buy-cucats-merch`, `hourglass`, `labyrinth`, `butterfly`,
`minimaze`, `vase`, `metropolitan_dystopia` (mines 18k Ti but delivers
577 — pipeline/TILING_BACK completion bug), `castle_walls`. Fix
priority is first-lane completion and route repair (algorithmic) and
congestion/clumping (emergent) rather than more sentinels.

### Next-ROI candidates (MAE split, not yet attempted)

- Mechanistic: continue TLE reduction in per-turn hot paths other
  than `defend_lane_if_needed` — perception full scan, assault ring
  rank scoring that still walks `enemies_by_key` N times per site,
  connected-conveyor refresh cadence on large maps.
- Algorithmic: `metropolitan_dystopia`-style mined-but-not-delivered
  — investigate why the pipeline executor fails to close the loop to
  the core when ore is abundant; fix TILING_BACK/road-progress for
  the "close but blocked" corridor case.
- Emergent: `cold`/`donut` vs leeroy early collapse — verify the
  cardinal-W rusher doesn't leave the own core vulnerable and that
  the defender is positioned in time on these topologies.

### Compaction-safe resume point

- Read live `bots/got-any-grapes/core_bot.py`,
  `builder_bot.py::_init_turn`, `mode_finding_ore.py::execute`,
  `mode_assaulting.py::_best_visible_site`, and
  `assault.py::choose_best_visible_assault_site` to see the retained
  session features in place.
- Next iteration must benchmark under `USE_GLOBAL_SEED=true` for
  meaningful comparisons; the main-module `random.seed(1)` shuffle
  otherwise pins a single fortunate rotation and overstates deltas.
- Any change smaller than ±4 wins on a single g16 is noise; either
  re-run with a different seed or accept the change on mechanistic
  rationale.
