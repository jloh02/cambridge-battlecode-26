This is a long-form task.

You are working with the `cambc` pyenv, on the Cambridge Battlecode bot under `bots/got-any-grapes/`, aiming to improve its match performance against three opponents: `jon-6`, `jon-6-a9bfs-surround`, and `leeroy-jonkins`.

Precedence: live code > this prompt > AGENTS.md > BATTLECODE_EXPLAINER.md > scratchpads. If sources conflict, follow higher precedence and say so.

Before you start, read BATTLECODE_EXPLAINER.md to understand the game.

**Execution model:**
- Each unit has private state only — no shared Python globals.
- Markers (32-bit unsigned ints) are the ONLY inter-unit communication.
- 2ms wall-clock per unit per turn; 1GB total memory.
- Preserve public bot entrypoints and repo workflow.

**Baselines / evidence tiers (read carefully):**

**Tier 0 — Historical local baseline, not decision-grade:**
- vs jon-6: **93.8%** (15-1) on local.
- vs a9bfs-surround: **68.8%** (11-5) on local.
- vs leeroy-jonkins: **62.5%** (10-6) on local.
- This baseline is retained only as context for older claims. It is superseded
  by remote TLE-enforced evidence and later local iteration evidence below.
  Do not use it as the promotion baseline, and do not treat a return to these
  numbers as meaningful unless timing and worst-game TiEq also improve.

**Tier 1 — Initial remote timing/failure baseline (2026-04-11):**
- This is the key evidence that the old bot was not remote-safe. It is not a
  current-code validation after the later local-only retained changes, but it
  remains the best timing-truth baseline for the failure mode.
- Match IDs and scores:
  - `d30605fe-812c-41ac-8401-2275c990c4d7`: `got-any-grapes` as Team A vs `jon-6`, **3-2**.
  - `3c37be48-642b-4e28-9061-6b7576013df2`: `got-any-grapes` as Team B vs `jon-6`, **1-4**.
  - `b9cfd69b-c581-4df5-87d9-e48a9ff5af9b`: `got-any-grapes` as Team A vs `jon-6-a9bfs-surround`, **1-4**.
  - `032b39c5-7cdc-4631-b58f-c1c4c1d443a1`: `got-any-grapes` as Team B vs `jon-6-a9bfs-surround`, **1-4**.
  - `a01c2a51-03d9-4850-9c39-635de041dfe6`: `got-any-grapes` as Team A vs `leeroy-jonkins`, **2-3**.
  - `1b0f9047-635d-40bf-a1c3-cf7a5157d69f`: `got-any-grapes` as Team B vs `leeroy-jonkins`, **1-4**.
- By opponent:
  - vs `jon-6`: **4-6**, avg TiEq **18,086**, worst TiEq **570**, opponent avg TiEq **24,204**.
  - vs `jon-6-a9bfs-surround`: **2-8**, avg TiEq **8,163**, worst TiEq **0**, opponent avg TiEq **24,426**.
  - vs `leeroy-jonkins`: **3-7**, avg TiEq **23,354**, worst TiEq **4,900**, opponent avg TiEq **26,705**.
- Weighted remote builder timing pressure:
  - vs `jon-6`: **83.6% >1ms**, **80.1% >1.5ms**, **75.8% >2ms**.
  - vs `jon-6-a9bfs-surround`: **81.8% >1ms**, **61.4% >1.5ms**, **56.6% >2ms**.
  - vs `leeroy-jonkins`: **74.7% >1ms**, **59.7% >1.5ms**, **51.8% >2ms**.
- Replay analysis files:
  - `.dist/replay_analysis/gag_vs_jon6_A.json`
  - `.dist/replay_analysis/gag_vs_jon6_B.json`
  - `.dist/replay_analysis/gag_vs_a9_A.json`
  - `.dist/replay_analysis/gag_vs_a9_B.json`
  - `.dist/replay_analysis/gag_vs_leeroy_A.json`
  - `.dist/replay_analysis/gag_vs_leeroy_B.json`
- All 30 games flagged `high_tle_pressure`, `low_builder_progress`, and
  `small_loop`. `travel_without_build` appeared in 15 games. Delivered refined
  axionite was **0** throughout. The immediate failure mode is remote execution
  pressure plus weak delivered titanium, not missing late-game polish.

**Tier 2 — Latest remote candidate validation (2026-04-11, partial retained-code ancestor):**
- A later remote seat-paired validation after the first runtime batch scored
  **10-20 overall**. This is newer than Tier 1 but still not a full validation
  of the current local retained code, because additional local-only changes
  were made afterward.
- Match IDs:
  - `8739a5b4-0bf1-47d8-a3e1-d98625e92f54`
  - `07d9d800-54f7-41e2-a9f6-88f5a2b40e0a`
  - `c6f0dfd2-1197-49b6-a067-4380206017c3`
  - `417fe110-81c5-4b3c-b8c1-61af0ec3a59a`
  - `47b536be-1dcd-4deb-b22c-e14cf77b26d5`
  - `b584a810-5dac-4cf3-ac95-894c50d64f39`
- By opponent:
  - vs `jon-6`: **3-7**, avg TiEq **19,474**, worst TiEq **0**,
    builder timing **76.2% >1ms / 62.4% >1.5ms / 54.9% >2ms**
  - vs `jon-6-a9bfs-surround`: **4-6**, avg TiEq **26,907**, worst TiEq
    **4,920**, builder timing **83.6% / 74.4% / 68.8%**
  - vs `leeroy-jonkins`: **3-7**, avg TiEq **21,490**, worst TiEq **0**,
    builder timing **72.3% / 59.4% / 53.6%**
- Decision from this evidence: revise, not promote. It showed slight aggregate
  improvement over Tier 1 but still failed remote safety and worst-game TiEq.

**Tier 3 — Current local retained candidate (not remotely validated):**
- Current live code should be treated as a local candidate only. It retains the
  useful runtime/pipeline changes described below, but there is no completed
  remote validation for this exact code state.
- Best current local g16 no-TLE summary for the retained safer
  direct-core/backpressure candidate: **29-19 overall / 60.4%**, avg TiEq
  roughly **30,228**, worst TiEq **0**, local TLE turns **0**.
  - vs `jon-6`: **14-2**, avg TiEq roughly **49,829**
  - vs `jon-6-a9bfs-surround`: **8-8**, avg TiEq roughly **19,531**
  - vs `leeroy-jonkins`: **7-9**, avg TiEq roughly **21,325**
- Interpretation: current local code preserves a strong economic edge vs
  `jon-6`, but remains weak against offensive opponents and still has
  zero/near-zero failures. It is a better local starting point than the failed
  threat-reroute branch, not a deployable baseline.

**Current local handoff state (2026-04-11, after iteration work):**
- `STATUS.md` is the active scratchpad. Read it after this prompt for
  iteration details, but continue to treat live code as higher precedence.
- Current retained code state includes:
  - bounded assault opening escape and assault fallback to economy after
    repeated blocked opening-escape attempts
  - fast perception cadence for non-assault `FINDING_ORE`, `EXPLORING`, and
    `TILING_BACK` modes
  - fast perception inference that preserves visible ore discovery
  - visible-backpressure secondary return routes when a newly built harvester
    touches an already backpressured friendly transport
  - direct-core preference for close harvesters, plus deterministic alternate
    core tile selection and core-approach-full fallback
  - splitter/passability correctness and bridge capacity realism
  - replay-analysis diagnostics for core delivery port concentration
- Latest cheap validation after cleanup:
  - `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
    tests/test_analyze_replay.py`: **59 passed**
  - `python -m compileall bots/got-any-grapes tools/analyze_replay.py`:
    **passed**
  - Tiling regression subset:
    `tests/test_jon_6_a8bfs_tiling.py`,
    `tests/test_jon_6_a4bfs_tiling.py`,
    `tests/test_jon_6_a4bfsclaude_tiling.py`, and
    `tests/test_leeroy_jonkins_a8bfs_tiling.py`: **6 passed**
- Important local results:
  - Safer direct-core/backpressure candidate g16 no-TLE: **60.4%**
    overall, with **14-2 vs `jon-6`**, **8-8 vs
    `jon-6-a9bfs-surround`**, and **7-9 vs `leeroy-jonkins`**; no local TLE.
  - A failed visible-threat direct-core reroute experiment collapsed g16 to
    **19-29 overall**, including **7-9 vs `jon-6`**, **6-10 vs
    `jon-6-a9bfs-surround`**, and **6-10 vs `leeroy-jonkins`**, avg TiEq
    **20,061**, worst TiEq **10**, TLE turns **0**. This was genuine detriment,
    not noise; the implementation was removed.
  - A deterministic `default_small1` smoke vs `jon-6-a9bfs-surround` won after
    retained changes, but local smoke `execTimeUs` can be zero, so it is not
    timing evidence.
- Rejected ideas / do not reintroduce blindly:
  - hard no-merge direct-core routing
  - hard "enemy visible means reroute" direct-core fallback
  - broad connected-conveyor load penalties based on private inferred load
  - treating bridges as infinite-capacity pipes
  - assuming splitters multiply a single upstream trunk's capacity
- Strategic interpretation:
  - The direct-core idea must stay. It gives the bot its best economic edge
    against pure economy opponents such as `jon-6`.
  - Offensive opponents expose the missing robustness layer, but hard rerouting
    away from direct-core damages the very economy needed to survive them.
  - The next direction is a deployable-first economy-pressure bot: establish
    direct-core titanium lanes, repair or defend them locally, and only escalate
    heavier offense/axionite after delivered titanium proves the first lane is
    alive.
- Practical next AFI target:
  - Implement a tiny **core-halo hygiene / local pack-behavior** batch rather
    than a global combat mode. Builders near the own core shell should locally
    clear hostile logistics, avoid handing hostile builders an attack rail, and
    optionally block clear hostile approach tiles with barriers. This must be
    cheap, use current visible grid/perception only, avoid broad scans, and not
    steal quiet distant economy turns.
- Suggested implementation surface for the next batch:
  - Add a small helper or module called from `BuilderBot.run()` before hijack
    and before economy movement, but only when this builder is near its own
    core shell.
  - Use only `bot.grid`, `bot.visible_positions`, current/adjacent tiles, and
    the 12 approach slots around the 3x3 core footprint. Do not scan the whole
    map or run A*.
  - Safe actions to consider: builder `fire()` on hostile passable logistics
    underfoot; clear adjacent hostile marker/road/conveyor-family tiles only
    when they plausibly route into the core halo; place a barrier only on a
    visible open hostile approach tile where it will not block own direct-core
    construction or core spawning.
  - Add tests that prove quiet economy builders do nothing, hostile logistics
    near core are cleared/blocked, own lanes are not destroyed, and the helper
    is bounded to a tiny visible neighborhood.
  - Cheap validation first: focused unit tests, compileall, the tiling
    regression subset, then one deterministic `default_small1` smoke vs
    `jon-6-a9bfs-surround`. Only then consider g16; do not remote test this
    batch until g16 is at least not clearly worse and timing analysis is
    acceptable.
- Pack-behavior framing:
  - Do not build a fake central planner. Do build local spatial rules that
    compose: if one friendly occupies an enemy outlet, another seals a side; if
    a ring site is occupied, take a neighboring useful pressure tile; if a
    hostile route reaches the core halo, nearby builders clear/block it while
    quiet builders keep farming.
- Combat component notes from SDK `cambc 1.6.2`:
  - barriers: 3 Ti, 30 HP, most practical immediate defensive blocker
  - gunners: 10 Ti, 40 HP, 10 damage or 40 axionite damage, 2 ammo, rotate for
    10 Ti; useful only with deliberate direction/logistics
  - breaches: 15 Ti / 10 Ax, 60 HP, 40 direct / 20 splash, 5 ammo; defer until
    a real axionite/foundry/ammo plan exists
  - launchers: 20 Ti, throw builder bots via `can_launch`/`launch`; mobility
    tool, not a simple defensive turret

**Priority goals (in decreasing order of importance):**
1. Make `got-any-grapes` remote-safe before adding strategy.
   The target is fewer than 5% of builder turns over 1ms locally and a major
   reduction in remote `% >1ms`, `% >1.5ms`, and `% >2ms`. Current remote rates
   are above 50% in every matchup, so most macro conclusions are contaminated.
2. Identify and remove hot-path whole-game work.
   Inspect `perception.py`, `navigation.py`, `mode_assaulting.py`,
   `mode_finding_ore.py`, and `mode_tiling_back.py` for broad scans,
   repeated SDK calls, per-turn topology rebuilds, repeated A* work, and
   expensive assault scouting. Prefer cadence gates, cached state, and cheap
   invalidation over new behavior.
3. Preserve the direct-core economic engine while making it deployable.
   Direct-core is not a failed idea. It is the main economic advantage against
   `jon-6`-style opponents. Improve robustness around it; do not replace it
   with hard threat reroutes or broad merge penalties.
4. Reduce remote TLE while preserving the first working titanium lane.
   Do not blindly lower ambition. Keep the earliest reliable economy behavior,
   but cap or defer expensive secondary behavior until the first lane is
   delivering.
5. Fix the zero-output and near-zero-output games.
   Worst TiEq values of 0, 570, 690, 910, and 1,160 are catastrophic. Prioritize
   changes that guarantee at least one harvester-plus-return route over changes
   that only improve already-good games.
6. Stabilize against `jon-6-a9bfs-surround`.
   This is the clearest weak matchup at 2-8 with two zero-TiEq games. Treat it
   as the main stress test for early disruption, route survival, and progress
   under pressure.
7. Improve Team B robustness.
   Team B results were bad against all three opponents: 1-4 vs `jon-6`, 1-4 vs
   `jon-6-a9bfs-surround`, and 1-4 vs `leeroy-jonkins`. Check spawn orientation,
   symmetry assumptions, assault-role slot logic, and core-halo congestion.
8. Improve delivered titanium throughput, not collected totals.
   TiEq is delivered-resource based. Add or preserve diagnostics that reveal
   stalled lanes, saturated core ports, idle harvesters, and travel-without-build
   loops.
9. Treat small loops and travel-without-build as first-class failures.
   Every candidate change should report small-loop counts, no-progress signals,
   and builder timing pressure alongside win rate and TiEq.
10. Keep assault and hijack behavior bounded.
   Assault fallback and opportunistic hijack can stay only if they are cheap and
   do not steal early economy turns. Do not expand late-game disruption until
   remote timing and first-lane reliability improve.
11. Defer axionite foundry-refinery work.
    Delivered refined axionite is currently 0, but the bot is failing earlier on
    remote time and titanium throughput. Axionite should wait until the titanium
    economy is reliable under TLE enforcement.
12. Marker coordination only after construction safety is proven.
    Markers are the legal communication mechanism, but marker placement must not
    poison routes, block construction, or introduce broad scans.

Do not overfit to one opponent if it materially weakens general map/seat
robustness or delivered-resource performance. For now, prefer mechanistic and
algorithmic resilience primitives over matchup-specific tactics.

**Development gating policy (strict):**
- Do not use remote tests or expensive benchmarking as a bug-finding tool.
- Remote testing is validation and timing truth, not exploration.
- Before any expensive test, complete the full intended change batch for the
  current ROI target.
- A change batch means all directly related edits required to make the fix
  coherent end-to-end, including helper functions, callers, state persistence,
  guards, and tests.
- Do not stop after a partial implementation just to benchmark.
- Before remote testing, exhaust cheap bug-finding first: inspect affected call
  paths, reason through edge cases, verify invariants, check time-budget risks,
  and run/update offline tests.
- If obvious follow-on edits are still pending, do not benchmark yet.
- If a bug is found during review or offline testing, fix it immediately and
  continue the batch.

**Benchmark and analysis policy:**
- For promotion-facing work, follow AGENTS.md staged validation.
- For quick strategy checks where runtime is not touched, use the quick workflow
  only after cheap tests pass.
- For this bot, any change touching perception, navigation, assault, tiling, or
  per-turn decision flow is runtime-sensitive and needs timing analysis.
- Rerun replay analysis after remote matches and report:
  - win rate by opponent and seat
  - avg and worst TiEq by opponent
  - `% builder turns >1ms`
  - `% builder turns >1.5ms`
  - `% builder turns >2ms`
  - TLE turns
  - small-loop / no-progress / travel-without-build signals
- Keep remote replay downloads bounded. Analyze at most 10 games at once unless
  there is a specific reason to download more.

**Hard constraints:**
- No fake shared manager or illegal coordination model.
- No global shared Python state for coordination.
- Markers are the only legal cross-unit communication.
- Keep the direct-core idea. Do not remove close-harvester direct-core routing
  just because offensive opponents disrupt it; improve local robustness around
  it instead.
- Do not reintroduce hard "visible enemy -> reroute away from direct core" or
  broad connected-load penalties without new mechanistic evidence. The latest
  local evidence says those variants genuinely harmed performance.
- No hijack peeling before the first safe titanium lane exists.
- Early-threat override: hostile builders/turrets near the core shell force
  defensive action over greed.
- Replace `round >= 80` assault proxy with economy-evidence gating only after
  safe marker placement exists.
- Time-critical modules must contain inexpensive time gates or bounded work.
- Commit when a completed batch has either significant improvement across the
  three matchups or a strong mechanistic rationale plus acceptable validation.

**When you answer during this task:**
1. Start with the single highest-ROI change batch and why.
2. Give exact code-level edits, not abstract advice.
3. List all additional edits required to make the batch complete before
   benchmarking.
4. List the bug-finding pass performed before testing:
   - touched call paths inspected
   - invariants checked
   - edge cases checked
   - time-risk checks
   - execution-model checks
5. List tests added or updated.
6. Give the cheapest validation plan first.
7. Give the remote benchmark plan only after implementation and cheap
   validation are complete.
8. Do not revert on noisy results. Revert only when analysis shows genuine
   detriment or the idea violates hard constraints.

**Procedural workflow:**
1. Identify the highest-ROI fix batch. Before making any change, inspect the
   live code paths; do not infer architecture from old notes.
2. Define the full implementation surface for that batch before testing:
   - functions that must change
   - state transitions that must change
   - invariants that must hold afterward
   - likely failure modes
   - tests that should fail before the fix and pass after it
3. Implement the entire batch first.
4. Perform a bug-finding pass before any expensive test:
   - mechanistic correctness
   - stale state and edge cases
   - illegal coordination assumptions
   - boundedness of loops and scans
   - time-budget risk on hot paths
   - persistence and retry behavior
   - construction churn and self-sabotage
   - map-boundary and visibility assumptions
   - interaction with existing heuristics and fallback logic
5. Add or update cheap validations before live games:
   - unit tests
   - regression tests
   - focused deterministic simulations or local smoke tests
   - assertions or instrumentation where useful
   - static reasoning about 2ms-model risk
6. Only after steps 3-5 are complete, run the benchmark plan.
7. Analyze failures along MAE levels and decide: keep, revise, or revert.
8. Commit when the completed batch has either:
   - significant improvement across all three matchups, or
   - a strong MAE-level rationale plus acceptable validation
9. Repeat from step 1.

For each iteration, report:

ROI target and rationale
-> full change batch scope
-> files/functions changed
-> patch
-> pre-benchmark bug audit
-> cheap tests added/updated
-> offline/smoke validation results
-> benchmark results by opponent and seat
-> timing pressure: `% >1ms`, `% >1.5ms`, `% >2ms`, TLE turns
-> MAE analysis (Mechanistic, Algorithmic, Emergent)
-> decision (keep/revise/revert)
-> commit message
-> next target

Stop **ONLY** when either:
(a) no remaining candidate change is likely to beat noise or materially reduce failure risk, or
(b) the next remaining ROIs require meaningful tradeoffs in win rate, TiEq, or execution safety.
