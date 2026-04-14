# CODEX Scratchpad

## Active Long-Form Task

### Current checkpoint (2026-04-15): lane-gated hijack port sentinel batch

- Active strategy name: bounded supplied hijack activation.
- ROI target and rationale: the high-level builder contract says enemy
  harvester hijacks should first place a supplied sentinel on an open port
  before piping the capture home, but live `mode_hijacking` only contested /
  sealed outlets and tiled back. A lower scratchpad section records a rejected
  earlier hijack-port-sentinel branch (**13-19 / 40.6%**) that often failed to
  place the sentinel and perturbed route choices, so this variant deliberately
  adds two guards: opportunistic hijack only starts after this builder has
  locally observed connected friendly conveyors, and sentinel staging only
  happens when the team can afford the sentinel.
- Full change batch scope:
  - `BuilderBot._maybe_switch_to_hijack()` now requires local connected-lane
    evidence before peeling an economy builder into hijack mode.
  - `mode_hijacking.execute()` now stages next to a visible open enemy
    harvester outlet and builds one fed sentinel on that port before entering
    / sealing it. Direction scoring is bounded to 8 directions and the current
    visible enemy target list; it prioritizes visible builders, then turrets,
    then core/logistics, otherwise points away from the anchor harvester.
  - Per-builder memory suppresses repeated sentinel builds on the same
    harvester for 80 rounds. This is private state only; no shared globals or
    illegal coordination.
- Files/functions changed:
  - `bots/got-any-grapes/builder_bot.py`: hijack state fields and lane-ready
    gate in `_maybe_switch_to_hijack`.
  - `bots/got-any-grapes/mode_hijacking.py`: lane-readiness helper, sentinel
    affordability / direction / stance / build helpers, execute wiring.
  - `tests/test_got_any_grapes_runtime_substrate.py`: focused hijack tests.
- Pre-benchmark bug audit:
  - Touched call paths inspected: `BuilderBot.run()` defense/heal/hijack
    ordering, `_maybe_switch_to_hijack`, `find_visible_hijack_target`,
    `mode_hijacking.execute`, `SentinelBot` adjacent-anchor behavior, and rush
    / defense adjacent-supply helpers for consistency.
  - Invariants checked: direct-core economy untouched; first-lane evidence
    required before hijack; sentinel is only built on visible open outlets
    adjacent to the enemy harvester; active enemy conveyor outlets still use
    the old contest-and-clear path; builder does not try to build under itself.
  - Edge cases checked: target lost while on a secured entry still tiles back;
    low titanium skips sentinel staging; recent same-harvester sentinel skips
    duplicate builds; direction tie-break uses direct target alignment over
    diagonal splash; no map-boundary assumptions outside `utils.in_bounds`.
  - Time-risk checks: new work is bounded to 8 neighbor stance checks plus
    `8 * len(visible_enemy_targets)` attack-arc scoring only while already in
    hijack mode; no A*, whole-map scan, or marker scan added.
  - Execution-model checks: all memory is per-builder private state; no Python
    globals are used for coordination; markers are unchanged.
- Cheap tests added/updated:
  - lane gate prevents pre-lane hijack switching
  - open enemy harvester port builds a fed sentinel
  - sentinel direction prioritizes a visible enemy builder
  - far builder stages next to the open port before entering it
  - low titanium does not waste a turn staging for an unaffordable sentinel
  - recent same-harvester sentinel suppresses duplicate builds
- Validation:
  - Focused subset `-k 'hijack or sentinel_supply or defense_skips_sentinel
    or rush_uses_enemy_transport or core_port_guard'`: **27 passed** before
    the final low-Ti test; final `-k hijack`: **12 passed**.
  - `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
    tests/test_analyze_replay.py`: **209 passed**.
  - `python -m compileall bots/got-any-grapes tools/analyze_replay.py`:
    passed.
  - Tiling subset:
    `tests/test_jon_6_a8bfs_tiling.py`,
    `tests/test_jon_6_a4bfs_tiling.py`,
    `tests/test_jon_6_a4bfsclaude_tiling.py`, and
    `tests/test_leeroy_jonkins_a8bfs_tiling.py`: **6 passed**.
  - Deterministic `default_small1` g2 vs a9:
    `.dist/reports/got-any-grapes_hijack_lane_gated_port_sentinel_default_small1_g2_20260415.json`,
    **0-2**, avg TiEq **1,835**, worst **760**. Clean `HEAD` comparison on
    the same seeds was also **0-2**, avg TiEq **2,975**, worst **690**, so
    this smoke is a warning but not a standalone revert signal.
  - `USE_GLOBAL_SEED=true` g16:
    `.dist/reports/got-any-grapes_hijack_lane_gated_port_sentinel_g16_20260415.json`,
    **29-19 / 60.4%**, avg TiEq **42,100**, worst **20**, TLE turns **0**.
    Local replay timing buckets were all **0.0%** for `>0.5ms`, `>1ms`,
    `>1.5ms`, and `>2ms`; treat timing as unavailable locally, not proof of
    remote safety.
    - `jon-6`: **12-4**, avg TiEq **49,711**, worst **5,960**
    - `jon-6-a9bfs-surround`: **9-7**, avg TiEq **38,411**, worst **20**
    - `leeroy-jonkins`: **8-8**, avg TiEq **38,178**, worst **5,080**
- Decision: keep/revise locally and commit. This is not promotion-grade and
  not remote-ready, but it is not the prior rejected hijack-sentinel failure:
  it ties the older all-opponent **29-19** reference, improves jon/a9 average
  TiEq substantially, removes zero-worst TiEq in this g16, and is covered by a
  coherent legality/timing-bounded rationale. Leeroy regresses by one g16 win,
  so the next batch should target route completion / early-collapse robustness
  rather than adding more hijack offense.
- Next target: algorithmic route completion on mined-but-not-delivered maps
  (`metropolitan_dystopia`, `git_branches`, `pls_buy_cucats_merch`) and
  small-loop / no-progress reduction. Do not remote test this stack yet.
- Rejected follow-up immediately after this commit: raising
  `BuilderBot.SMALL_LOOP_UNIQUE_THRESHOLD` from `2` to `3` to match replay
  analyzer small-loop semantics. Focused tests passed and cheap validation
  passed, but same-seed `metropolitan_dystopia` g2 vs a9 regressed from clean
  hijack-baseline **0-2**, avg TiEq **10,895**, worst **4,440** to **0-2**,
  avg TiEq **7,015**, worst **20**. Reverted as genuine target-map detriment;
  do not retry broad 3-tile generic recovery without a more local TILING_BACK
  mechanism.
- Compaction-safe resume point: preserve unrelated user changes
  (`FIRST_LONGFORM_PROMPT.md`, `.claude/scheduled_tasks.lock`). The intended
  commit should include only `STATUS.md`, `builder_bot.py`,
  `mode_hijacking.py`, and `tests/test_got_any_grapes_runtime_substrate.py`.

Iterate on `bots/got-any-grapes/` vs studied opponents `jon-6`,
`jon-6-a9bfs-surround`, and `leeroy-jonkins`. Current strategic focus is
defense against (1) early offense (Tootill Labs / 4 buffons style) and
(2) sustained disruption (`leeroy-jonkins`, `a9bfs-surround`, `laapa
chondey`), while preserving a relative economy large enough to fund
offense. Direct-core economy stays in. Markers are the only legal
cross-unit communication.

### Current checkpoint (2026-04-14): spawn-cap g16 autopsy + correctness bugfix batch

- Active strategy name: chronological opening-role contract plus cap-16 map
  exploitation, with targeted correctness fixes for passability, sentinel
  targeting, and rush core-fire supply.
- User correction retained: use `USE_GLOBAL_SEED=true` g16 with 8 jobs for
  local iteration checks. Do not treat g4 as macro evidence. Deltas of roughly
  ±2 wins in g16 are noise unless backed by concrete replay mechanics.
- Pre-fix g16 requested by the user:
  `.dist/reports/got-any-grapes_spawn_cap16_interval8_g16_20260414.json`,
  overall **15-17 / 46.9%**, avg TiEq **34,711**, worst **30**;
  `jon-6` **7-9**, avg **31,791**, worst **30**; a9 **8-8**, avg
  **37,631**, worst **100**. Local replay timing buckets were all zero and are
  not decision-grade timing evidence.
- Autopsy of the pre-fix g16:
  - Losses were dominated by low delivery/mining, high revisit rates, small
    loops, orphan/dead-end logistics, and severe core-port concentration.
  - Worst examples: `git_branches` vs `jon-6` delivered **30 Ti** with
    small-loop streak **1193** and **0/12** active core ports; a9 losses on
    `face`, `wall`, `metropolitan_dystopia`, `git_branches`, `cold`, and
    `rush_bait` all had low TiEq and `small_loop`/`low_builder_progress`.
  - Spawn cap helped slightly versus the immediately previous shell batch
    (**14-18 → 15-17**) but stayed far below the retained
    `.dist/reports/got-any-grapes_corerush_fixed_g16_20260413.json` reference.
- Correctness bugs fixed after the no-edit audit:
  - `utils.is_passable` checked `entity_team` for core building tiles. It now
    checks `building_team`, so own core tiles are passable and enemy core
    tiles are not.
  - `SentinelBot._target_priority` ignored its
    `prefer_core_over_logistics` argument. It now cuts connected logistics
    before core when the hijack cluster is deeper, and prefers core when only
    one logistics tile remains.
  - `mode_rush._turret_supply_class` treated adjacent friendly connected
    transport as supply without checking direction and could not use enemy
    conveyors feeding a cleared core-fire tile. It now requires directed
    transport into the turret tile and treats enemy directed logistics as the
    best supply class.
- Cheap validation after fixes:
  - Focused subset `-k 'passable or sentinel or rush'`: **27 passed**.
  - `tests/test_got_any_grapes_runtime_substrate.py tests/test_analyze_replay.py`:
    **199 passed**.
  - `compileall bots/got-any-grapes tools/analyze_replay.py`: passed.
  - Tiling regression subset: **6 passed**.
- Post-fix g16:
  `.dist/reports/got-any-grapes_bugfix_passability_sentinel_rush_g16_20260414.json`,
  overall **17-15 / 53.1%**, avg TiEq **37,438**, worst **70**;
  `jon-6` **8-8**, avg **31,723**, worst **70**; a9 **9-7**, avg
  **43,153**, worst **1,350**. Local timing buckets are still all zero, so
  local timing pressure is unavailable rather than 0.0%.
- Counterfactual flips from pre-fix to post-fix:
  - Positive: `git_branches` vs `jon-6` **30 → 100020** TiEq; `hooks` vs
    `jon-6` **9090 → 26590**; `default_medium1` vs `jon-6` **19240 →
    53260**; `git_branches` vs a9 **3970 → 100030**; `corridors` seat B vs
    a9 **33600 → 35060**.
  - Negative: `first_sound` vs `jon-6` **30100 → 3060**; `pixel_forest` vs
    `jon-6` **15990 → 15970** while opponent jumped **10340 → 38470**;
    `the_great_divide` vs `jon-6` **26240 → 20450**; `galaxy` vs a9
    **25110 → 9760**.
- Decision: keep/revise locally. The bugfixes are mechanistically correct and
  unit-covered, and g16 improved by **+2** overall with better a9 TiEq/core
  kills, but this is still below target and not remote-ready. Do not remote
  test this stack yet.
- Wider audit findings not fixed in this batch:
  - Hijack mode still does barrier sealing and then tiles home; it does not
    implement the user's "build a sentinel on an open enemy harvester port,
    let it destroy, then pipe out" contract.
  - `core_port_guard_if_needed` still skips `TILING_BACK` builders entirely;
    if revisited, only consider a defender-only exception with replay evidence,
    because broad TILING_BACK core-port maintenance was previously rejected.
  - Role derivation is local/spatial only; if an opening role spawn is delayed
    past `OPENING_ROLE_MAX_SPAWN_ROUND`, that builder can no longer infer the
    intended defender/rusher role.
  - Marker-based shared ore/enemy-harvester communication remains effectively
    disabled (`utils.place_marker_around` returns `False`), so the high-level
    "note them down for others" contract is not fully implemented.
- Compaction-safe resume point: preserve unrelated user changes
  (`FIRST_LONGFORM_PROMPT.md`, `.claude/scheduled_tasks.lock`). Live bot edits
  are uncommitted. Next highest-ROI target is either (1) a bounded hijack
  sentinel-on-port batch, because it is a direct contract mismatch and can
  exploit enemy supply, or (2) a defender-only core-port guard exception for
  `TILING_BACK` if replay inspection shows the designated defender stuck in
  tiling while a core-shell threat is active.

### Previous checkpoint (2026-04-14): role-contract bugfix batch

- Active strategy name: chronological opening-role contract with defender leash
  bugfix; no promotion claim yet.
- User correction: do not treat g4 as decision evidence. Use g16 with 8 jobs
  for iteration checks; g4 is only useful for reproducing a specific replay
  path and was too noisy for macro claims.
- Implemented / retained in live code:
  - Opening spawn contract changed to `BUILDER, BUILDER, BUILDER, DEFENDER,
    RUSHER`, with directions expressed from own core toward the physical map
    center rather than fixed compass seats.
  - Builder role inference recognizes the center-facing defender and
    center-facing diagonal rusher during the opening window; fallback builder
    directions prevent the first-three-builder phase from stalling when
    preferred shell tiles are blocked.
  - Defender leash bug fixed: core defender is now pulled back to L1 <= 5 even
    if it drifted into `TILING_BACK` or another economy mode. This matches the
    user's high-level contract; ordinary non-defender tiling builders are not
    leashed.
  - Rusher clears hostile core-directed logistics underfoot before planning a
    turret, so walking onto an enemy conveyor into the enemy core can sever the
    feed immediately.
- Rejected / reverted in this checkpoint:
  - Core defender station behavior inside the L1 shell: fixed-seed
    `default_small1` a9 smoke dropped from **1-3** to **0-4** and produced
    worse TiEq on matching seeds.
  - Core defender gunner/redirect variants: fixed-seed smoke variants were
    mixed or worse; the capped redirect version collapsed to **0-4**. The
    tests protecting that branch were removed with the code.
  - Direct-core return target changed from core tile to approach slot. g16 with
    that change collapsed `jon-6` to **5-11**. It was reverted to the retained
    baseline behavior: assign a lane slot, but route to the core tile.
- Counterfactual evidence:
  - Retained baseline report
    `.dist/reports/got-any-grapes_corerush_fixed_g16_20260413.json`:
    `jon-6` **11-5**, a9 **9-7**.
  - Failed approach-slot g16
    `.dist/reports/got-any-grapes_defender_allmode_leash_g16_20260414.json`:
    `jon-6` **5-11**, a9 **8-8**. This was genuine detriment, not g4 noise.
  - Current post-revert g16
    `.dist/reports/got-any-grapes_role_contract_coretarget_revert_g16_20260414.json`:
    overall **17-15 / 53.1%** across `jon-6` and a9; `jon-6` **9-7**, avg
    TiEq **33,583**, worst **1,460**; a9 **8-8**, avg TiEq **23,740**,
    worst **1,460**. Local replay timing remains all-zero, so timing pressure
    is unavailable locally despite reported 0.0% buckets.
- Interpretation: current live code follows more of the requested role/defender
  contract, but it is not better than the retained baseline and is far below
  the user's 75%+ target. Do not remote test this state. Next ROI should be a
  real replay/map counterfactual on current g16 flips (`corridors`,
  `gaussian`, `default_medium1`, `the_great_divide`) and then either repair
  the role-order implementation or improve first-lane/defender throughput.
- Compaction-safe resume point: preserve unrelated user changes
  (`FIRST_LONGFORM_PROMPT.md`, `.claude/scheduled_tasks.lock`). Live bot edits
  are uncommitted. Cheap validation currently passes: focused role/defender
  tests, runtime substrate + replay analyzer (**186 passed**), compileall, and
  tiling subset (**6 passed**).

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
- A* bridge-gate pruning that treated passable conveyor-family tiles
  as non-bridge triggers. It reduced local debug A* max time in one
  profile, but g16 fell to **26-22 / 54.2%** and regressed key
  `jon-6`/`leeroy` maps (`donut`, `cold`, `thread_of_connection`).
  Do not reintroduce without a map-specific bridge route proof.
- Stale-heap-entry skip in fresh/resumable A* was removed after the
  narrowed batch scored **25-23 / 52.1%** with lower avg TiEq. It is
  plausibly timing/noise-adjacent, but not worth keeping without a
  stronger targeted proof.

### Latest retained batch: navigation debug overhead

- Retained code after the navigation audit:
  - `navigation.DEBUG_PATH_LOGGING` now requires both `DEBUG=true` and
    `DEBUG_PATH_LOGGING=true`, instead of treating any `DEBUG=true` run
    as path logging.
  - A* failure prints and indicator dots are gated by
    `DEBUG_PATH_LOGGING`; `throws_exception_on_failure` still raises.
  - `utils.bump_profile`, `max_profile`, and `set_profile` are
    compile-time no-ops unless `DEBUG_TURN_PROFILE=true`, removing
    repeated `getattr(bot, "turn_profile", None)` overhead in normal
    runs.
- Cheap validation: `tests/test_got_any_grapes_runtime_substrate.py`
  plus `tests/test_analyze_replay.py` **163 passed**; `compileall`
  passed.
- Focused DEBUG profile on `pls_buy_cucats_merch` vs a9 with
  `DEBUG_PATH_LOGGING=false`: A* failure output dropped **74 → 4**
  lines; profiled turns >1ms dropped **506 → 403** and >2ms
  **197 → 187**. A* timeouts themselves remain a separate route-retry
  problem.
- USE_GLOBAL_SEED g16 report:
  `.dist/reports/got-any-grapes_nav_debug_overhead_only_g16_20260413.json`
  scored **29-19 / 60.4%**, avg TiEq **27,121**, worst **0**:
  `jon-6` **10-6**, a9 **10-6**, `leeroy` **9-7**. Keep for
  mechanistic runtime rationale; it is not promotion-grade and remote
  timing is still expected to be high until A* retry/assault scoring
  are addressed.

### 2026-04-13 whole-bot audit follow-up

- ROI target: remove obvious non-debug hot-path waste without changing
  strategy. Retained edits:
  - removed dead `navigation._get_greedy_fallback_action` and its
    old heuristic test; added a regression that the helper stays gone.
  - gated additional `bot.logger.log(...)` f-string construction in
    `mode_tiling_back`, `mode_finding_ore`, `mode_assaulting`,
    `mode_rush`, `mode_hijacking`, `mode_exploring`, `defense`, and
    `healing` behind `utils.DEBUG`.
  - reduced core ore scan SDK calls by caching `ct.get_position()`
    and `ct.get_tile_env(pos)` once per nearby tile.
  - kept small pure call-order/loop savings in rush/assault
    (`_choose_turret_plan` before turret supply classification,
    no temporary set for connected-neighbor count, cached
    `_scout_chunk_radius(ct)` inside frontier metrics).
- Reverted from this batch:
  - direct pending-bridge completion before transit A*. It collapsed
    USE_GLOBAL_SEED g16 to **17-31 / 35.4%**; likely leaves builders
    on the near side and forces worse replans.
  - cached-path aliasing in `navigation.compute_pathfinding_step`.
    After bridge revert, g16 was still **23-25 / 47.9%**; restoring
    the defensive path copy brought the deterministic smoke back to a
    win.
  - assault blocked-ring/enemy-list reuse. With bridge/path fixes but
    assault reuse retained, g16 was **21-27 / 43.8%**; not worth
    keeping without a narrower proof.
- Latest narrowed g16:
  `.dist/reports/got-any-grapes_wholebot_mechanistic_audit_logonly_g16_20260413.json`
  scored **25-23 / 52.1%**, avg TiEq **24,399**, worst **0**:
  `jon-6` **10-6**, a9 **9-7**, `leeroy` **6-10**. This is exactly
  four wins below the **29-19** retained reference, so treat it as
  unresolved/noise-bound rather than promotion evidence. Do not remote
  validate this batch by itself.
- Cheap validation after the final narrowing:
  `tests/test_got_any_grapes_runtime_substrate.py tests/test_analyze_replay.py`
  **163 passed**; tiling regression subset **6 passed**; `compileall`
  passed.
- Next target remains A* retry control / TILING_BACK route completion,
  not direct bridge bypasses or cached-path aliasing.

### 2026-04-13 TILING_BACK A* retry cleanup follow-up

- ROI target: remove safe TILING_BACK navigation waste found during the
  "why is TILING_BACK still timing out" audit, without replacing A* with
  greedy movement.
- Retained edits in this mini-batch:
  - removed the unreachable `if False and allow_bridges and tiling_back`
    bridge-expansion block from `_resume_anytime_astar`; the real
    synchronous A* bridge path remains unchanged.
  - cached `ct.get_current_round()` once when expiring temporary
    obstacles in `navigation.compute_pathfinding_step`.
  - cached `ct.get_current_round()` once in the pending-bridge transit
    branch of `_navigate_and_build`, including cooldown and temp-obstacle
    expiry.
  - added a unit test proving temp-obstacle expiry performs one round read
    while preserving expiry behavior.
- Rejected during this mini-batch:
  - dropping `allow_bridges` / core-bridge flags from the anytime planner
    signature. Even though the disabled anytime planner does not expand
    bridges, removing those invalidation keys caused a deterministic
    `default_small1` smoke versus a9 to collapse to **99 delivered Ti**.
    The signature semantics were restored.
- Cheap validation:
  - `tests/test_got_any_grapes_runtime_substrate.py`: **161 passed**.
  - `tests/test_analyze_replay.py`: **3 passed**.
  - tiling regression subset: **6 passed**.
  - `compileall bots/got-any-grapes tools/analyze_replay.py`: passed.
  - deterministic `default_small1` smoke vs `jon-6-a9bfs-surround`,
    seed 1: won on titanium (**4189** vs **3396**).
- USE_GLOBAL_SEED g16:
  `.dist/reports/got-any-grapes_nav_retry_cleanup_g16_20260413.json`
  scored **23-25 / 47.9%**, avg TiEq **25,192**, worst **0**:
  `jon-6` **9-7**, a9 **7-9**, `leeroy` **7-9**. This is -2 wins
  versus the just-committed **25-23** mechanistic audit batch but within
  the documented ±4 local noise band; not promotion evidence and not a
  remote-validation candidate by itself.
- Decision: keep only if committing for mechanistic remote-safety
  rationale; otherwise fold into the next A* retry-control batch. The
  next substantive target remains repeated full-search retry control and
  first-lane completion, not direct bridge bypasses.

### 2026-04-13 TILING_BACK full-A* retry-control batch

- ROI target: reduce repeated TILING_BACK full-A* retries after an empty
  full-search failure while preserving direct-core routing, bridge
  availability, and the no-greedy-fallback constraint.
- Code changes:
  - added `FULL_ASTAR_RETRY_COOLDOWN_TURNS = 2`.
  - added `_full_astar_retry_signature(...)`, keyed by current position,
    target, cardinal-only flag, builder mode, obstacle counts, pending
    bridge availability, and core-bridge mode flags.
  - after a full A* returns no path, record the retry signature and round;
    when a resumable planner is still active and the same empty full-A*
    signature recurs inside the cooldown, return `None` instead of paying
    another full A* slice that turn.
  - clear empty-full-A* retry state on successful full A* and shared
    pathfinding recovery reset.
- Tests added:
  - repeated empty full-A* is deferred during cooldown.
  - full A* is retried once the cooldown expires.
- Cheap validation:
  - `tests/test_got_any_grapes_runtime_substrate.py tests/test_analyze_replay.py`:
    **166 passed**.
  - tiling regression subset: **6 passed**.
  - `compileall bots/got-any-grapes tools/analyze_replay.py`: passed.
  - deterministic `default_small1` smoke vs a9 seed 1: won on titanium
    (**8508** vs **4128**).
  - targeted hard-map smokes still failed: `pls_buy_cucats_merch` vs a9
    seed `965892706` produced only **168 stored Ti / 0 mined**; `cold`
    vs leeroy seed `44968841` delivered **11 Ti** after mining **2140**.
    This confirms the patch is not a first-lane completion fix.
- USE_GLOBAL_SEED g16:
  `.dist/reports/got-any-grapes_astar_retry_control_g16_20260413.json`
  scored **25-23 / 52.1%**, avg TiEq **24,761**, worst **0**:
  `jon-6` **12-4**, a9 **7-9**, `leeroy` **6-10**. Seat split:
  `jon-6` A **5-3** / B **7-1**; a9 A **4-4** / B **3-5**;
  `leeroy` A **3-5** / B **3-5**. Local timing buckets were all zero,
  so timing pressure is unavailable locally.
- MAE decision: keep as a bounded mechanistic timing-risk reduction
  (+2 wins versus the immediately prior cleanup, within noise), but do
  not remote-validate by itself. The remaining failures are algorithmic
  first-lane acquisition/completion and route repair, not just repeated
  A* retries.

### 2026-04-13 rejected cardinal-role gate experiment

- Hypothesis: late random cardinal spawns were self-assigning as duplicate
  defenders / core rushers because `BuilderBot._init_turn` derives roles
  from `spawn_pos - core_pos` for any cardinal spawn, not only the first
  role batch. This matched replay symptoms where extra builders parked at
  east-cardinal spawn positions for most of the game.
- Full gate tested: record `spawn_round`, apply cardinal defender/rusher
  assignment only through round 4.
  - Cheap smoke `default_small1` vs a9 seed 1: won strongly
    (**16242** vs **7003** delivered Ti).
  - Hard smoke `pls_buy_cucats_merch` vs a9 seed `965892706` changed
    failure from no mining to **5440 mined / 10 delivered**, proving the
    gate can free exploration, but not delivery closure.
  - USE_GLOBAL_SEED g16:
    `.dist/reports/got-any-grapes_cardinal_role_gate_g16_20260413.json`
    scored **21-27 / 43.8%**, avg TiEq **29,088**, worst **0**:
    `jon-6` **10-6**, a9 **6-10**, `leeroy` **5-11**. Avg TiEq rose,
    but wins dropped by four versus the retry-control batch and a9/leeroy
    weakened.
- Narrow gate tested: only prevent duplicate east-cardinal defenders while
  preserving late west-cardinal core rushers. Deterministic
  `default_small1` vs a9 seed 1 lost (**6600** vs **15787** delivered Ti).
- Decision: reverted both role-gate variants. The duplicated-role symptom
  is real, but the current defender/rusher mix appears to contribute to
  combat survival/pressure; do not reintroduce without a replacement that
  preserves a9/leeroy coverage.

### 2026-04-14 resumable-only navigation + opening role correction

- ROI target and rationale: the user clarified the intended opening
  composition is exactly one early defender and one early rusher, with all
  later cardinal spawns staying normal economy builders that opportunistically
  defend/hijack. They also explicitly rejected runtime use of synchronous
  "vanilla" A* and asked for behavior parity tests against the existing A*
  algorithm.
- Full change batch scope:
  - `BuilderBot` now records `spawn_round`; cardinal E/W defender/rusher
    assignment is gated to `CARDINAL_OPENING_ROLE_MAX_ROUND = 4`. Late E/W
    cardinal spawns remain `FINDING_ORE` economy builders.
  - Runtime navigation no longer calls `calculate_astar_path`. The function
    remains only as a synchronous reference oracle for tests.
  - `_resume_anytime_astar` now expands bridge candidates using the same
    bridge gate/filter/cost rules as the reference synchronous A*.
  - `compute_pathfinding_step` orders empty-path planning as exact straight
    TILING_BACK path, micro-plan for near/repeated/low-budget cases, then
    resumable A*. If the resumable planner is active, the turn yields instead
    of paying a synchronous full-search slice.
  - TILING_BACK bridge transit now stores `bridge_transit_planner_state` and
    uses resumable A* with `allow_bridges=False` for the transit leg.
  - A* heap tie-breaking now prefers deeper nodes among equal `f/raw_h/line`
    contours by sorting on `-g`, reducing same-contour expansion without
    changing the cost model.
- Tests added/updated:
  - late east/west cardinal spawn economy-builder invariants.
  - runtime navigation guard that `compute_pathfinding_step` and
    `_navigate_and_build` do not call `calculate_astar_path`.
  - straight TILING_BACK path skips both resumable and sync A* when the
    route is exactly clear, and rejects wrong-way friendly transports.
  - resumable-vs-sync parity tests for clear cardinal path, cardinal detour,
    bridge-required path, and bridge-disabled failure.
  - replaced old full-A* retry cooldown tests with resumable-active and
    resumable-path tests.
- Cheap validation:
  - `tests/test_got_any_grapes_runtime_substrate.py`: **173 passed**.
  - `tests/test_analyze_replay.py`: **3 passed**.
  - tiling subset: **6 passed**.
  - `compileall bots/got-any-grapes tools/analyze_replay.py`: passed.
  - deterministic `default_small1` seed 1 vs a9: won on titanium
    (**33,418** vs **7,837**).
  - deterministic `pls_buy_cucats_merch` seed `965892706` vs a9: won on
    titanium tiebreak but still showed the known route-completion bug
    (**136 delivered / 10,740 mined**).
- USE_GLOBAL_SEED g16:
  `.dist/reports/got-any-grapes_resumable_only_roles_g16_20260414.json`,
  **24-24 / 50.0%**, avg TiEq **32,597**, worst **0**; `jon-6`
  **9-7** avg **42,148**, a9 **8-8** avg **32,280**, leeroy **7-9**
  avg **23,364**. Seat split: jon A **4-4** / B **5-3**; a9 A
  **5-3** / B **3-5**; leeroy A **4-4** / B **3-5**. Local timing
  buckets remain all-zero/unavailable.
- MAE decision: keep as a mechanistic/runtime-safety batch and user-corrected
  role semantics. It is not promotion-grade and should not be remote-tested
  alone. The result is -1 win versus the latest retained retry-control g16
  and inside local noise; a9/leeroy improve slightly while jon-6 drops.
  Remaining zero/near-zero failures are algorithmic route completion and
  delivery closure, not lack of resumability.

### Known catastrophic failure maps (zero / near-zero TiEq losses)

`cold` (vs leeroy, vs a9 partially), `donut`, `git_branches` (vs a9),
`pls-buy-cucats-merch`, `hourglass`, `labyrinth`, `butterfly`,
`minimaze`, `vase`, `metropolitan_dystopia` (mines 18k Ti but delivers
577 — pipeline/TILING_BACK completion bug), `castle_walls`. Fix
priority is first-lane completion and route repair (algorithmic) and
congestion/clumping (emergent) rather than more sentinels.

### 2026-04-14 bugfix/counterfactual iteration after user role-contract reset

- Active retained local baseline before this subsection was the safer
  direct-core/backpressure candidate plus the user's opening-order changes.
  First required g16 under `USE_GLOBAL_SEED=true`:
  `.dist/reports/got-any-grapes_spawn_cap16_interval8_g16_20260414.json`,
  **15-17 / 46.9%**, avg TiEq **34,711**, worst **30**; `jon-6`
  **7-9**, a9 **8-8**. Local timing buckets were all zero, so local
  timing remains unavailable rather than evidence of 0ms turns.
- Retained bugfix batch:
  - `utils.is_passable()` now checks `building_team` for core tiles rather
    than stale/irrelevant `entity_team`.
  - `sentinel_bot.SentinelBot._target_priority()` now honors
    `prefer_core_over_logistics`.
  - `mode_rush._turret_supply_class()` now requires adjacent transports to
    be directed into the gunner tile and accepts enemy directed transports
    as valid stolen supply.
  - g16:
    `.dist/reports/got-any-grapes_bugfix_passability_sentinel_rush_g16_20260414.json`,
    **17-15 / 53.1%**, avg TiEq **37,438**, worst **70**; `jon-6`
    **8-8**, a9 **9-7**.
- Reverted/rejected during this iteration:
  - Hijack port sentinel helper:
    `.dist/reports/got-any-grapes_hijack_port_sentinel_g16_20260414.json`,
    **13-19 / 40.6%**. It produced 10 negative flips vs 6 positive and
    often failed to place the intended sentinel while perturbing
    timing-sensitive route choices.
  - Defender TILING_BACK participation in `core_port_guard_if_needed()`:
    `.dist/reports/got-any-grapes_defender_tiling_core_guard_g16_20260414.json`,
    **14-18 / 43.8%**. It raised average TiEq but turned multiple old
    early core kills into 2000-turn failures.
  - Exact core-lane-slot return target:
    `.dist/reports/got-any-grapes_core_slot_target_g16_20260414.json`,
    **13-19 / 40.6%**. Mechanistic autopsy on gaussian/a9 showed port
    concentration worsened: top1 source share jumped from about **20%** to
    **88%**, and used core approach ports dropped from **11** to **4**.
    Do not reintroduce exact slot targeting without a different spread and
    repair model.
  - Opportunistic core-approach exit repair:
    `.dist/reports/got-any-grapes_opportunistic_core_exit_g16_20260414.json`,
    **12-20 / 37.5%**, avg TiEq **30,657**, worst **0**; `jon-6`
    **7-9**, a9 **5-11**. Reverted. It tried to preserve opportunistic
    core entry while forcing any current approach slot to build coreward,
    but it caused 10 negative flips vs 4 positive, including several early
    core-kill maps becoming 2000-turn losses. Do not reintroduce this local
    completion shortcut without replay proof that it preserves the existing
    core-rush conversion path.
- Retained follow-up bugfixes:
  - `BuilderBot._opening_role_from_spawn_offset()` now classifies the
    center-facing diagonal rusher independently of the round gate. Late
    economy spawns are cardinal-only, so this closes a real delayed-rusher
    role hole without making late cardinal spawns inherit defender roles.
    g16:
    `.dist/reports/got-any-grapes_late_rusher_role_g16_20260414.json`,
    **18-14 / 56.2%**, avg TiEq **42,382**, worst **410**; `jon-6`
    **10-6**, a9 **8-8**.
  - `perception.scan_around()` now refreshes building HP during TILING_BACK
    only for the designated defender or when the builder saw enemies on the
    previous turn. Quiet TILING_BACK still skips HP reads. This fixes the
    contradiction where TILING_BACK builders were eligible lane responders
    but could not reliably observe damaged lane assets. g16:
    `.dist/reports/got-any-grapes_tiling_hp_refresh_g16_20260414.json`,
    **18-14 / 56.2%**, avg TiEq **40,184**, worst **100**; `jon-6`
    **9-7**, a9 **9-7**. Kept because it improves matchup balance toward
    the sustained-pressure target while preserving the aggregate gain over
    the retained bugfix batch.
- Latest cheap validation after retained changes:
  - `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
    tests/test_analyze_replay.py`: **203 passed**.
  - `python -m compileall bots/got-any-grapes tools/analyze_replay.py`:
    passed.
  - Tiling regression subset:
    `tests/test_jon_6_a8bfs_tiling.py`,
    `tests/test_jon_6_a4bfs_tiling.py`,
    `tests/test_jon_6_a4bfsclaude_tiling.py`, and
    `tests/test_leeroy_jonkins_a8bfs_tiling.py`: **6 passed**.
- Current interpretation:
  - Positive/negative flips are dominated by timing-sensitive early core
    kill conversion and fragile first-lane completion, not by one isolated
    combat heuristic.
  - The next core-port distribution fix must not simply force exact approach
    slots. It needs a repair/spread model that avoids concentrating builders
    onto the nearest few ports and that does not discard the existing
    opportunistic core-entry behavior that was producing early kills.
  - Route completion remains the larger algorithmic bug. Keep investigating
    missing final conveyors, orphan approach slots, and "mined but not
    delivered" cases before adding more offense.

### 2026-04-15 seat-order / direct-core slot audit

- The apparent a9 seat split in
  `.dist/reports/got-any-grapes_hijack_lane_gated_port_sentinel_g16_20260415.json`
  was partly a `benchmark_matrix.py` schedule artifact: maps are sampled
  independently after seat shuffling, so Team A drew several known hard
  maps. Use the tournament backend or another paired map+seed schedule when
  judging seat-order claims.
- Paired hard-map a9 baseline on `corridors`, `face`, `git_branches`, and
  `metropolitan_dystopia` with seed 101:
  `.dist/reports/got-any-grapes_a9_seatcheck_hard4_seed101_20260415.json`,
  **1-7**, avg TiEq **17,541**, worst **30**. Same map+seed pairs showed
  no simple Team-A-only bug: Team B was better on some maps, Team A on
  others. The common failure remains low delivery plus huge small-loop
  streaks.
- Re-confirmed rejected direct-core slot variants against the current code:
  - Exact approach-slot return target:
    `.dist/reports/got-any-grapes_core_slot_target_a9_hard4_seed101_20260415.json`
    improved paired hard-map delivered titanium but lost the old
    git_branches core-kill bonus; full g16
    `.dist/reports/got-any-grapes_core_slot_target_g16_20260415.json`
    fell to **23-25 / 47.9%**, avg TiEq **40,237**, worst **0**;
    `jon-6` **10-6**, a9 **6-10**, leeroy **7-9**. Reverted.
  - Inner-core target with widened slot-exit completion helper:
    `.dist/reports/got-any-grapes_core_slot_exit_helper_a9_hard4_seed101_20260415.json`,
    **1-7**, avg TiEq **8,178**, worst **10** on the paired hard-map
    smoke. It also removed the old git_branches core-kill conversion.
    Reverted without g16 because it matched the previously rejected
    opportunistic core-exit failure mode.
- Live code is restored to the retained direct-core behavior after this
  audit. Do not reintroduce slot-target or opportunistic slot-exit helper
  variants without a different mechanism that preserves early core-kill
  conversion and demonstrably reduces small loops.
- Retained mechanistic assault timing batch:
  - `assault.rank_assault_sites_for_harvester()` now accepts a precomputed
    `enemies_by_key` map, and visible-harvester selection builds that map
    lazily once only after seeing a harvester.
  - Ring threat scoring now filters visible enemies down to threatening
    turrets/builders once per harvester instead of scanning every visible
    logistics tile for each ring side. This is behavior-preserving because
    `visible_threat_score()` only used turret and builder enemies already.
  - Focused unit coverage proves non-threatening logistics are excluded
    from threat-score scans.
  - Cheap validation:
    `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
    tests/test_analyze_replay.py`: **210 passed**;
    `python -m compileall bots/got-any-grapes tools/analyze_replay.py`:
    passed; tiling regression subset: **6 passed**.
  - Final-code g16:
    `.dist/reports/got-any-grapes_assault_threat_filter_lazy_g16_20260415.json`,
    **26-22 / 54.2%**, avg TiEq **39,881**, worst **500**, local TLE turns
    **0**; `jon-6` **9-7**, a9 **8-8**, leeroy **9-7**. This is **-3 wins**
    from the retained local 29-19 and therefore inside the known local timing
    noise band, while improving worst TiEq and reducing a known assault hot
    path. Kept on mechanistic remote-safety rationale; not promotion-grade
    and not remote-validated.
- Retained connected-load graph aggregation batch:
  - `perception._recompute_connected_loads()` no longer walks every
    harvester downstream along the full lane. It keeps
    `connected_friendly_conveyors` membership exact first, then computes
    source counts adjacent to friendly harvesters and propagates those counts
    once through the connected forward/reverse topology. Detailed load
    recomputation remains time-gated; under pressure, stale/default loads are
    kept only as a heuristic while the connected membership is still current.
  - Added focused unit coverage for branch-load aggregation and for the
    time-gated membership-sync case.
  - Cheap validation:
    `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
    tests/test_analyze_replay.py`: **212 passed**;
    `python -m compileall bots/got-any-grapes tools/analyze_replay.py`:
    passed; tiling regression subset: **6 passed**.
  - Synthetic equivalence/speed check against the previous formula on a
    300-transport chain with 50 harvesters: exact load-equivalent, roughly
    **10x** faster locally (`0.118s -> 0.012s` over 50 recomputes).
  - Deterministic `default_small1` g2 vs a9:
    `.dist/reports/got-any-grapes_connected_load_graph_default_small1_a9_20260415.json`,
    **1-1**, avg TiEq **51,610**, worst **2,650**, local TLE **0**.
  - USE_GLOBAL_SEED g16:
    `.dist/reports/got-any-grapes_connected_load_graph_g16_20260415.json`,
    **30-18 / 62.5%**, avg TiEq **50,723**, worst **0**, local TLE **0**;
    `jon-6` **12-4** avg **63,734** worst **0**, a9 **9-7** avg
    **38,436** worst **40**, `leeroy` **9-7** avg **49,997** worst
    **6,000**. Seat split: `jon-6` **6-2 A / 6-2 B**, a9 **4-4 A /
    5-3 B**, `leeroy` **4-4 A / 5-3 B**. Local replay timing buckets were
    all zero and remain unavailable as timing truth.
  - Decision: keep. It is +1 win vs the retained 29-19 candidate and +4
    wins vs the prior assault-timing g16, improves average TiEq materially,
    and removes a real hot-path complexity multiplier. The new `git_branches`
    zero vs `jon-6` is a residual first-lane/small-loop failure, not evidence
    of a load-count semantic mismatch; every g16 game still flagged a
    small-loop signal. Not remote-validated.
- Rejected A* exhausted-signature retry cooldown:
  - Tried a short same-position/target/obstacle-signature cooldown after
    `_resume_anytime_astar()` exhausted with no path, intending to avoid
    rebuilding identical failed searches and let bugnav/unclog work instead.
  - Cheap tests passed and `default_small1` g2 vs a9 was unchanged, but full
    USE_GLOBAL_SEED g16 collapsed:
    `.dist/reports/got-any-grapes_astar_retry_cooldown_g16_20260415.json`,
    **20-28 / 41.7%**, avg TiEq **42,167**, worst **20**; `jon-6` **8-8**,
    a9 **7-9**, `leeroy` **5-11**. This is a genuine detriment, especially
    against the early-wreckage stress test, so the code/tests were reverted.
  - Do not reintroduce a blind exhausted-A* cooldown. If retry control is
    revisited, it needs replay evidence that the blocked search is truly
    redundant and must preserve early defense/route repair movement.
- Rejected obstacle-fingerprint rewrite:
  - Tried replacing `_obstacle_fingerprint()`'s `hash(frozenset(obstacles))`
    with an allocation-free Python loop. Focused identity tests passed, but
    the microbenchmark showed the built-in frozenset hash was much faster on
    representative sets (`0.0021s` vs `0.0446s` for 5,000 fingerprints).
    Reverted before smoke; do not reintroduce unless the replacement stays in
    C-level operations or avoids full-set traversal entirely.

### Next-ROI candidates (MAE split, not yet attempted)

- Mechanistic: continue TLE reduction in per-turn hot paths other
  than `defend_lane_if_needed` — perception full scan, assault ring
  rank scoring that still walks `enemies_by_key` N times per site,
  connected-conveyor refresh cadence on large maps.
- Mechanistic/A*: next safe A* target is retry control, not bridge
  removal. Profiles show repeated full A* from the same stuck
  TILING_BACK positions after timeout/best-effort results; add a short
  same-signature cooldown or resumable-first retry path that preserves
  bridge availability and direct-core routing.
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
