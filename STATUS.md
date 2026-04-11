# CODEX Scratchpad

## Active Long-Form Task

- Strategy name: got-any-grapes remote timing first-lane hardening
- Task: Improve `bots/got-any-grapes/` against `jon-6`,
  `jon-6-a9bfs-surround`, and `leeroy-jonkins` under the legal Cambridge
  Battlecode execution model.
- Criteria: prioritize remote safety before new strategy; reduce builder turns
  over 1 ms / 1.5 ms / 2 ms, preserve or improve first titanium lane
  reliability, and track win rate, TiEq, worst TiEq, small loops,
  no-progress/travel-without-build signals, and TLE turns.
- Throughput priority: maximize delivered titanium throughput into the core,
  not just ore discovery, mining, or total conveyor count. Current observed
  failure: many ore lanes converge into only 2-3 final pipelines near the core,
  causing massive pipeline stall even when upstream harvesters and conveyors
  exist. Future batches should prefer fixes that spread returns across more
  core-adjacent ports, reduce last-mile saturation, and diagnose idle/stalled
  delivered-resource lanes.
- Latest evidence: 2026-04-11 remote baseline is 9-21 overall across the
  requested 30 games. By opponent: 4-6 vs `jon-6`, 2-8 vs
  `jon-6-a9bfs-surround`, 3-7 vs `leeroy-jonkins`. Weighted remote builder
  timing pressure is extreme: 74.7%-83.6% over 1 ms, 59.7%-80.1% over 1.5 ms,
  and 51.8%-75.8% over 2 ms depending on matchup. All 30 games flagged
  `high_tle_pressure`, `low_builder_progress`, and `small_loop`; 15 games
  flagged `travel_without_build`; delivered refined axionite was 0.
- Immediate next action: use the failed threat-aware direct-core fallback
  experiment to define practical AFIs that preserve the direct-core economic
  upside while adding local robustness against offensive pressure. Do not add a
  hard "enemy visible means reroute" rule; it collapsed the economic matchup.
- Current active batch, 2026-04-11: strictly mechanistic assault-inference
  runtime cleanup. Maintain an incremental count of known terrain/env tiles
  during perception and use it for assault symmetry cache invalidation instead
  of repeatedly scanning `bot.grid.values()`. This preserves direct-core
  economics and assault target semantics while removing a recurring broad
  whole-grid pass from assault builders.
- Compaction-safe resume point: live code is authoritative and already dirty.
  Current batch surface is `builder_bot.py` for the new private counter default,
  `perception.py` for incrementing that counter on full and fast visible-tile
  writes, `mode_assaulting.py` for reading the counter instead of scanning
  grid values, and `tests/test_got_any_grapes_runtime_substrate.py` for focused
  invariants. Do not benchmark until the implementation, bug audit, targeted
  pytest, and compile checks are complete.
- Active batch result: implementation and cheap validation passed
  (`tests/test_got_any_grapes_runtime_substrate.py`, `tests/test_analyze_replay.py`,
  and compileall on `bots/got-any-grapes`). Local g16 no-TLE failed the
  win-rate gate and should not go remote: 20-28 overall / 41.7%, avg TiEq
  19,719, worst TiEq 0, local TLE turns 0; by opponent `jon-6` 11-5,
  `jon-6-a9bfs-surround` 2-14, `leeroy-jonkins` 7-9. Local replay
  `execTimeUs` was still zero, so no local `% >1ms` timing conclusion is
  available. Deterministic `default_small1` seed 1 vs a9 still won under
  `--tle 2` with 5,928 delivered titanium. Decision: revise locally, no
  commit and no remote validation. The next target is the a9/zero-output
  collapse in live code, using same-schedule local evidence before any remote.
- Rejected marker-disable batch: worst a9 losses showed hundreds of assault
  claim markers and marker removals, so disabling assault claim publishing was
  tested as a construction-safety fix. Targeted tests and compileall passed,
  but the deterministic `default_small1` seed 1 a9 smoke regressed immediately
  from a win with 5,928 delivered titanium to a loss with 204 delivered
  titanium. The change was reverted. Interpretation: assault claim markers are
  ugly and probably expensive, but they are currently carrying enough
  coordination/pressure value that a blunt no-op is a genuine detriment. Any
  marker work must make placement safer without removing the claim signal.
- Rejected marker-cadence batch: tried preserving assault claim markers while
  reducing refresh frequency from 4 to 8 rounds. Cheap validation passed and
  deterministic `default_small1` seed 1 a9 still won with 9,890 delivered
  titanium in replay analysis, but same-schedule g16 collapsed further:
  14-34 overall / 29.2%, `jon-6` 10-6, `jon-6-a9bfs-surround` 1-15,
  `leeroy-jonkins` 3-13, avg TiEq 18,276, worst TiEq 0, local TLE turns 0.
  Reverted. Interpretation: assault claims are not merely cosmetic; their
  cadence affects coordination enough that even reducing marker volume is a
  real tradeoff. Do not revisit marker cadence without a safer claim placement
  or a replacement coordination primitive.
- Current active batch: early local core defense. User correctly identified
  that the bot had no defensive override against offensive strategies. Added
  a bounded `defense.py` primitive: non-assault economy/explorer builders near
  the own core interrupt greed only when a visible enemy builder/turret is
  inside the core-defense radius, then build a local sentinel aimed at the
  assailant. The helper skips assault roles and `TILING_BACK` so it does not
  peel builders off an active first lane. Cheap validation passed. Smoke
  evidence: `default_small1` seed 1 vs a9 under `--tle 2` won with 22,210
  delivered titanium, up from 5,928 before this patch; `default_small1` seed 1
  vs leeroy also won with 22,290 delivered titanium. Next action: run local
  g16 no-TLE against all three studied opponents before any remote validation.
- Rejected core-halo hygiene batch, 2026-04-11: implemented a tiny
  `core_halo.py` helper called from `BuilderBot.run()` after perception and
  before hijack/economy. It only used current visible grid data, current tile,
  and the 12 own-core approach slots; tests covered quiet no-op, no legality
  calls without visible hostile pressure, underfoot hostile logistics fire,
  hostile approach barriers, own-lane preservation, and no whole-grid scan.
  Cheap tests passed and one smoke won, but the repeat smoke lost and the g16
  no-TLE matrix was a clear detriment: 18-30 overall / 37.5%, avg TiEq
  22,186.5, worst TiEq 0, TLE turns 0; by opponent `jon-6` 10-6,
  `jon-6-a9bfs-surround` 5-11, `leeroy-jonkins` 3-13. The batch was removed.
  Interpretation: even tiny action-priority/barrier changes near core can
  disrupt the current direct-core/economy/assault coupling. Do not reintroduce
  generic core-halo barriers without replay proof that a specific approach
  tile is actively harming the first titanium lane.
- Latest post-revert cheap validation: `python -m pytest
  tests/test_got_any_grapes_runtime_substrate.py tests/test_analyze_replay.py`
  passed 60 tests; the tiling regression subset passed 6 tests; compileall on
  `bots/got-any-grapes` and `tools/analyze_replay.py` passed. Running the
  runtime substrate and tiling tests in one combined pytest process still
  exposes an existing cross-file module contamination issue, so keep using the
  repo's separated validation shape unless that test harness is cleaned up.
- Rejected ore-target cache batch, 2026-04-11: tried a private per-builder
  `FINDING_ORE` cache for the current ore/access pair with a 3-turn TTL and
  validity checks for ore still present, not claimed, not blacklisted, no
  adjacent friendly conveyor, passable access tile, and friend deconfliction.
  Cheap tests and smoke passed, but g16 no-TLE was a clear detriment:
  17-31 overall / 35.4%, avg TiEq 18,463.5, worst TiEq 0, TLE turns 0; by
  opponent `jon-6` 7-9, `jon-6-a9bfs-surround` 6-10, `leeroy-jonkins` 4-12.
  Removed the batch. Interpretation: target freshness and deconfliction are
  more important than the saved BFS work; do not cache the ore target across
  movement turns unless the cache is tied to a stronger progress invariant or
  same-turn/full-perception signature.
- Current immediate next action: avoid more behavior-coupled "cheap" caches or
  barriers. If continuing, focus on strictly behavior-preserving hot-path
  reductions inside existing functions, such as reducing allocation and SDK
  calls in perception/navigation without changing selected ore targets,
  return targets, or action priority.
- Iteration 1 batch: bounded opening escape plus tiling-back fast perception.
  Edited `builder_bot.py` to use local fast perception for non-assault
  `TILING_BACK` turns between 10-round full-perception heartbeats. Edited
  `mode_assaulting.py` to defer repeated shell-escape BFS to a 4-round cadence
  and yield an assault builder to `FINDING_ORE` after 8 blocked opening-escape
  attempts. Added tests in `tests/test_got_any_grapes_runtime_substrate.py`.
- Iteration 1 cheap validation: `~/.pyenv/versions/cambc/bin/python -m pytest
  tests/test_got_any_grapes_runtime_substrate.py` passed 42 tests; compileall
  on `bots/got-any-grapes` passed. One deterministic smoke with
  `cambc run got-any-grapes jon-6-a9bfs-surround maps/default_small1.map26
  --seed 1 --tle 2 --replay replay.replay26` completed and won for
  `got-any-grapes`, with no local TLE reported; replay `execTimeUs` fields were
  zero, so this is not timing evidence. Smoke still showed weak delivered
  titanium (76), `small_loop`, `low_builder_progress`, and
  `travel_without_build`.
- Iteration 1 remote validation: 6 seat-paired remote matches completed on
  2026-04-11: `8739a5b4-0bf1-47d8-a3e1-d98625e92f54`,
  `07d9d800-54f7-41e2-a9f6-88f5a2b40e0a`,
  `c6f0dfd2-1197-49b6-a067-4380206017c3`,
  `417fe110-81c5-4b3c-b8c1-61af0ec3a59a`,
  `47b536be-1dcd-4deb-b22c-e14cf77b26d5`, and
  `b584a810-5dac-4cf3-ac95-894c50d64f39`. Overall candidate score was 10-20
  vs the prompt baseline 9-21. By opponent: `jon-6` 3-7, avg TiEq 19,474,
  worst 0, builder timing 76.2% >1ms / 62.4% >1.5ms / 54.9% >2ms;
  `jon-6-a9bfs-surround` 4-6, avg TiEq 26,907, worst 4,920, timing
  83.6% / 74.4% / 68.8%; `leeroy-jonkins` 3-7, avg TiEq 21,490, worst 0,
  timing 72.3% / 59.4% / 53.6%. All games still had `small_loop`,
  `high_tle_pressure`, and `low_builder_progress`; 16/30 had
  `travel_without_build`. Decision: revise, not revert yet. Mechanistic
  changes helped a9 and some jon timing, but remote safety target was not met.
- Iteration 2 immediate target: identify and cheaply disable/reduce expensive
  per-turn work for stationary or no-progress builders while preserving first
  titanium-lane construction, then address last-mile delivery saturation near
  the core by spreading return lanes across more core-adjacent ports.
- Iteration 2 batch: broadened fast perception from assault/tiling-only to
  non-assault `FINDING_ORE` and `EXPLORING` on a heartbeat cadence: full scan
  every 4 rounds while no titanium is known and every 8 rounds once titanium is
  known. Fast inference now records locally visible titanium/axionite so the
  first lane can still be discovered between full scans. Targeted tests passed
  (44 tests) and compileall passed. Deterministic `default_small1` smoke vs
  `jon-6-a9bfs-surround` won with 11,260 delivered/mined titanium in replay
  analysis, up from 76 delivered in the prior smoke; local `execTimeUs` remained
  zero, so local timing is unavailable.
- Iteration 2 g16 local no-TLE matrix: 30-18 overall, avg TiEq 29,667, worst
  0, local reported TLE 0. By opponent: `jon-6` 15-1, avg TiEq 41,656, worst
  4,940; `jon-6-a9bfs-surround` 8-8, avg TiEq 24,314, worst 1,220;
  `leeroy-jonkins` 7-9, avg TiEq 23,031, worst 0. Seat split: jon-6 Team A
  7-1 / Team B 8-0; a9 Team A 3-5 / Team B 5-3; leeroy Team A 4-4 / Team B
  3-5. Decision: keep revising locally before another remote run because
  g16 remains below the 80% per-opponent bar and leeroy/worst-TiEq failures
  remain.
- Rejected follow-up: tried a core-port spreading helper plus stronger
  connected-conveyor load penalties to address final-pipeline saturation.
  Cheapest smoke on the same `default_small1` seed immediately regressed from
  a win with 11,260 delivered titanium to a loss with only 64 scored titanium
  and 1,210 mined, so that change was reverted. Delivery-throughput remains a
  priority, but the next version must preserve the existing first return target
  on early lanes and should probably diagnose port saturation before changing
  core-port selection.
- Rejected follow-up 2: tried a narrower return-target-only load penalty that
  left A* step costs and core-port geometry unchanged, then tried an even more
  conservative version that only rose at load 4+. Both failed the same smoke
  (`default_small1`, seed 1 vs a9), losing with 1,407 and then 2,773 scored
  titanium. Conclusion: the current private connected-load estimate is too
  blunt for direct routing changes; penalizing merges breaks working first-lane
  construction before it fixes final-pipeline stall. Next pipeline work should
  start with replay/diagnostic evidence of core-port saturation and only then
  introduce a construction-safe spread primitive.
- Pipeline investigation update: added replay-analysis diagnostics for
  core-delivery port concentration. A saved castle replay delivered 78,860
  titanium through exactly 3 core tiles, with top-3 share 100%, confirming the
  user's last-mile glut observation. A first implementation that used private
  inferred harvester-count load to trigger secondary lanes regressed local g16
  (56.2% overall, jon-6 10-6, a9 6-10, leeroy 11-5), so it was revised away
  from inferred global load. Current local approach uses direct visible
  backpressure instead: when a builder is about to claim a harvester because it
  touches existing friendly transport, it only starts a secondary core return
  if that adjacent transport visibly stores a resource. Forced secondary
  returns choose a deterministic alternate core tile from the harvester
  position, without shared Python state or marker dependence. Targeted tests
  pass and the deterministic a9 smoke still wins with 11,260 delivered
  titanium.
- Splitter research update: official rules say splitters accept input only from
  the back and alternate among the primary output plus the two adjacent output
  directions, prioritizing least-recently-used directions. They can relieve a
  final-port delivery glut only when placed before the saturated last-mile
  fan-out and paired with valid downstream branches; they do not multiply the
  capacity of a single upstream trunk by themselves.
- Pipeline heuristic iteration: verified bridges are not infinite-capacity
  pipes. A replay scan over 250 local replays found no bridge emitting more
  than one stack in a distribution phase, so long bridges should be treated as
  long-hop construction tools, not throughput multipliers. A hard no-merge
  direct-core-return heuristic was rejected: broad threshold g16 fell to 12.5%
  overall, while a narrow threshold failed the deterministic a9 smoke. The
  direct-core idea itself remains live: close harvesters prefer direct core,
  visible backpressure can trigger forced secondary returns, visibly full core
  approaches can fall back to a connected pipeline, splitters are handled as
  passable transport, and core-port diagnostics are retained. A clean local
  g16 on the safer backpressure-only candidate was 60.4% overall, with 14-2 vs
  `jon-6`, 8-8 vs `jon-6-a9bfs-surround`, and 7-9 vs `leeroy-jonkins`; no
  local TLE turns. Decision: do not commit yet; next target is a softer
  construction-safe robustness primitive that preserves first-lane construction
  and the `jon-6` direct-core gains.
- Failed adaptive-threat experiment: tried keeping direct-core as the default
  while deferring to a known connected lane when a builder saw local pressure
  near the harvester/route/core. Even after tightening fallback to "nearby
  viable lane only", local g16 collapsed to 19-29 overall: 7-9 vs `jon-6`,
  6-10 vs `jon-6-a9bfs-surround`, and 6-10 vs `leeroy-jonkins`, avg TiEq
  20,061, worst TiEq 10, TLE turns 0. Decision: this was genuine detriment, not
  noise. The implementation was removed. Lesson: offense and logistics are
  delicately coupled; visible threat must not hard-override direct-core routing
  because the direct-core economy is itself the main advantage against pure
  economy and a necessary resource base against offense.
- Offensive scenario musings:
  - Rusher / core leech: a fast enemy builder reaches the core halo or a
    friendly lane and tries to turn friendly logistics into an attack rail.
    Robust response should be local core-halo hygiene: clear enemy logistics,
    block hostile approach tiles, and avoid building final-port infrastructure
    that points into an active enemy builder. Do not globally stop farming.
  - Disruptor / route cutter: enemy builders, sentinels, gunners, or barriers
    contest ore veins and sever pipelines. Robust response should preserve
    independent direct-core lanes in quiet areas, repair or retile broken
    nearby harvesters, and only shorten/merge when the backup is already close
    and construction-safe. The failed fallback shows that "pressure seen,
    reroute" is too blunt.
  - Terminator / tech timing: opponent looks economic, then uses refined
    axionite/foundries to power stronger weapons and late core pressure. Robust
    response should not panic early; it should keep titanium throughput high,
    watch for visible foundry/axionite-chain evidence, then prioritize attacks
    or disruption on foundries, axionite harvesters, and ammo routes rather
    than fighting upgraded weapons head-on.
  - Port blocker / congestion attacker: opponent or friendly overbuilding
    reduces available core-adjacent delivery slots. Robust response should use
    core-port diagnostics and visible ring fullness to fall back to existing
    pipelines only when direct core slots are truly unavailable, not merely
    because an enemy is nearby.
  - Spawn clog / builder trap: pressure or friendly overproduction pins
    builders near the 3x3 core shell. Robust response should be cheap local
    unclogging, road placement, and temporary obstacle memory; broad combat
    planning from every stuck builder is too expensive under the 2 ms budget.
- Practical robust AFIs to consider next:
  - AFI 1, Core-halo hygiene: a very small local routine for builders near
    own core that clears hostile conveyors/markers/roads underfoot or adjacent
    when they form a route into the core shell, and optionally drops a barrier
    on a clearly hostile approach tile. This is practical because it uses only
    current visible grid data and builder `fire`/barrier actions; it should
    not affect quiet distant harvesters.
  - AFI 2, Direct-core route safety as a cost bias, not a hard switch: add a
    small temporary obstacle or path-cost penalty around visible hostile combat
    tiles during direct-core A*, while keeping the same direct target. This
    preserves the economic intent but nudges routes around danger when a safe
    detour is cheap.
  - AFI 3, Broken-lane first aid: strengthen existing disconnected-harvester
    retile logic with a short TTL priority for recently seen own harvesters
    that lost all adjacent transport. This attacks disruptor damage without
    changing quiet direct-core behavior.
  - AFI 4, Core-port saturation fallback: keep the direct-core idea, but when
    the 12 approach slots are visibly full or final-port concentration is
    locally obvious, allow pipeline merge or alternate core tile selection.
    This is practical because it is already partially implemented and tested;
    it does not require global capacity estimates.
  - AFI 5, Offensive flip after first safe lane: keep opportunistic hijack or
    enemy logistics cutting gated behind first safe titanium delivery. The
    target should be enemy harvesters/foundries/ammo routes, not generic core
    assault, because those are higher-leverage and cheaper to recognize.
  - AFI 6, Axionite-chain scouting marker later: after titanium is stable,
    mark visible enemy foundries or axionite harvesters with a sparse event
    marker. This is not first-priority because marker placement can poison
    routes and axionite work is explicitly deferred until titanium is reliable.
  - Combat component notes from SDK `cambc 1.6.2`: barriers are cheap
    3-titanium / 30-HP blockers and are the most practical immediate defensive
    tool beyond builder `fire`; gunners cost 10 titanium, fire every turn for
    10 damage with 2-ammo cost, can rotate for 10 titanium, and line-of-sight
    rules make them useful only when direction and logistics are deliberate;
    breaches cost 15 titanium + 10 axionite, have 60 HP, fire every turn for
    40 direct / 20 splash with 5-ammo cost, but require axionite and therefore
    belong after a real foundry/ammo plan; launchers cost 20 titanium, ignore
    facing, and throw builder bots (`can_launch`/`launch`) rather than firing
    like gunners, so they are a mobility/tactical-delivery tool, not a simple
    defensive turret. Practical implication: near-term robust combat should
    prefer builder fire, barriers, route denial, and selective sentinel/gunner
    geometry only where logistics already exist; breach/launcher plans are
    later AFIs because they need ammo, positioning, and more tests.
  - Non-AFIs for now: broad global threat classification, per-turn combat
    scans from every builder, hard reroute on visible enemy, default gunner or
    breach production without an ammo/refined-axionite plan, and splitter or
    bridge assumptions that pretend to multiply throughput.
- Current-code strategic reflection:
  - Can this bot cheese early-game / econ-focused enemies? Partly yes. Live
    code has forced opening assault spawns on rounds 5 and 6, assault builders
    use symmetry/frontier inference, navigate with road support, publish sparse
    assault claims, and try to capture enemy harvester rings with sentinels.
    Non-assault builders can also opportunistically hijack visible enemy
    harvesters by standing on active outlets, firing underfoot, sealing open
    sides with barriers, and then tiling back from the captured outlet. These
    are real pressure tools. But they are fragile cheese: they depend on
    visible enemy harvesters or successful symmetry navigation, mostly attack
    economy rather than the core, and can waste early builder slots if no good
    target materializes. Against pure economic opponents, the more reliable
    "cheese" is actually direct-core titanium throughput, not combat.
  - Can this bot endure sustained pressure? Not yet at promotion level. It has
    strong navigation primitives (bounded A*, cached/anytime pathing, local
    escape, temporary obstacles, disconnected-harvester retiling, stall
    blacklists, fast perception cadence), and it has some local combat actions
    (builder `fire`, sentinel assault sites, hijack barriers). The missing
    durability layer is a cheap defensive routine around own core/own routes.
    Sustained pressure still causes low builder progress, small loops, and
    travel-without-build; remote builder timing pressure is also high, so
    "superior navigation" is contaminated by runtime cost. Most importantly,
    titanium supply is inconsistent: the bot can create high-output games, but
    worst TiEq remains catastrophic and core-port concentration shows that
    delivered throughput, not mined ore, is the binding constraint.
  - How does this bot exert pressure? It pressures through three channels:
    direct economic pressure by delivering titanium faster than pure farmers;
    assault pressure by building sentinels around enemy harvesters; and hijack
    pressure by stealing/sealing enemy harvester outlets. These tactics work
    best against slow economic opponents and exposed harvester layouts. They
    work worse against offensive opponents because those opponents contest the
    same logistics surface: builders get delayed, routes are cut, and assault
    units that do not quickly find value become deadweight. The failed
    threat-reroute experiment reinforces that pressure must be layered on top
    of a stable titanium engine, not substituted for it.
- MAE framework reflection:
  - Mechanistic: the bot has useful runtime work already (fast perception,
    bounded searches, cached pathing), but remote evidence says it is still too
    expensive. Any AFI that adds broad scans, per-turn global classification,
    or extra A* work is suspect. Practical AFIs must be tiny local checks,
    cadence-gated, and reuse current perception/grid data.
  - Algorithmic: the direct-core route heuristic is valuable but brittle when
    converted into hard rules. Better algorithmic AFIs should bias or repair
    existing behavior instead of flipping modes: core-halo hygiene, temporary
    obstacle costs around danger, local retile priority, and visibly-full
    core-port fallback. These preserve the same strategic goals while reducing
    known failure modes.
  - Emergent: the current bot's cooperation is mostly implicit: markers share
    ore/connected conveyors/assault claims, but every builder still has private
    state. Emergent failures are congestion, duplicate routes, too many
    builders entering pressure work, and assault slots stealing economy before
    the first lane is safe. Robustness should come from evidence-gated role
    changes and sparse markers only after construction safety is proven.
  - Strategic conclusion: do not chase a single "anti-offense mode." Use the
    economic direct-core engine as the baseline, add narrow local defensive
    primitives for core/route hygiene, and only flip the script offensively
    after delivered titanium proves the first lane is alive.
- Challenged-fundamentals reassessment:
  - Planning/runtime: assume the bot is not yet remote-safe on AWS Graviton3.
    The current remote baseline has extreme builder timing pressure across all
    studied opponents, with more than half of builder turns over 2 ms in every
    matchup. Local `execTimeUs` may be zero in smoke replays, so remote remains
    timing truth, but remote must not be used as bug-finding. Any next AFI must
    be compatible with fewer scans, fewer broad path searches, and fewer
    repeated SDK calls.
  - Navigation: do not call navigation deployment-ready. The code has strong
    primitives, but replay signals still show `small_loop`,
    `travel_without_build`, poor progress under obstacles, and occasional
    catastrophic TiEq. Treat navigation as adequate for some direct-lane
    construction, not as a solved substrate for combat or large detours.
  - Combat tactics: incomplete because they are not integrated with supply,
    timing, route protection, and role gating. Sentinels can capture enemy
    harvester rings, hijack can steal outlets, and barriers can deny space, but
    these actions can be counter-synergistic with economy when they consume
    early builder turns, titanium, pathfinding budget, or core-halo space before
    a safe lane is delivering. Synergy exists only when combat protects or
    amplifies delivered-resource throughput: clearing a core leech, sealing an
    enemy harvester outlet, defending a live route, or cutting an enemy foundry
    chain after our first lane is safe.
  - SDK/resource use: the bot uses useful SDK pieces (nearby scans, marker
    values, build legality, builder fire, movement, pathing helpers), but it is
    not yet making robust algorithmic/emergent use of the full resource model.
    Delivered titanium is the KPI, yet behaviors still overvalue building,
    traveling, scouting, or assaulting relative to actual delivery. Bridges and
    splitters were initially easy to overinterpret; current evidence says use
    them only with exact construction semantics, not imagined throughput.
  - Emergent path forward: under 2 ms/unit and private state, prefer implicit
    pack-like swarm behavior over central-planner coordination. The right
    analogy is not isolated workers and not telepathic global planning; it is
    wolves taking compatible local roles during a hunt. Practical examples:
    if one friendly occupies an enemy outlet, another seals a side; if a ring
    site is occupied, another builder takes a neighboring useful pressure tile;
    if a hostile route reaches the core halo, nearby builders clear or block it
    while quiet builders keep farming. Complex shared-state plans need
    consensus, broad sensing, and durable shared memory; those are expensive
    and illegal unless encoded through sparse markers. The team should become
    bigger than the sum of its parts through robust local invariants and cheap
    role-compatible spatial rules.
- Roadmap / big direction:
  - Current outlook: `got-any-grapes` has a real strategic kernel but is not
    deployable yet. The kernel is direct-core titanium throughput plus
    opportunistic pressure. It can beat or threaten pure economy when the first
    lanes survive, but remote TLE pressure, small loops, catastrophic worst TiEq,
    and weak robustness against offensive disruption mean it is not
    promotion-close.
  - First deployable target: a boringly reliable titanium bot. It should get at
    least one safe harvester-plus-return lane in almost every game, keep local
    builder turns over 1 ms below the repo safety target, avoid zero/near-zero
    TiEq games, and preserve direct-core gains against `jon-6` while not
    collapsing under `a9bfs-surround` or `leeroy-jonkins`.
  - Mechanistic work required: remove or cadence-gate hot-path broad work in
    perception/navigation/assault, reduce repeated SDK calls, keep pathfinding
    bounded and resumable, avoid per-turn whole-map/topology rebuilding, and
    measure builder timing pressure after every runtime-sensitive batch.
  - Algorithmic work required: make first-lane construction more deterministic
    and recoverable; improve small-loop and travel-without-build escape; keep
    direct-core as the default for close harvesters; use core-port fallback only
    when visibly necessary; improve route repair and local obstacle handling
    before adding heavier combat or axionite.
  - Emergent work required: build implicit pack behavior from cheap local rules:
    core-halo hygiene, outlet sealing/contesting, alternate local pressure tiles,
    local retile priority, and sparse markers only where they cannot poison
    construction. Avoid central-planner fantasies and avoid role changes that
    steal early economy before delivered titanium proves a lane is alive.
  - Final product for this roadmap: not a sophisticated combined-arms bot yet,
    but a remote-safe economy-pressure bot. It should establish direct-core
    titanium lanes quickly, repair or defend them locally, opportunistically
    punish exposed enemy harvesters/logistics, and only escalate into heavier
    offense or axionite/foundry tactics after the titanium engine is stable.
- Compaction-safe resume point: continue from live code, not older notes. User
  precedence is live code > prompt > `AGENTS.md` > `BATTLECODE_EXPLAINER.md` >
  scratchpads. Hard constraints: no shared Python globals for coordination;
  markers are the only cross-unit communication; no hijack peeling before a
  safe titanium lane exists; remote tests are validation only after cheap
  bug-finding and local validation. Current code state: failed visible-threat
  direct-core reroute was removed after g16 collapse; retained code includes
  runtime fast-perception changes, assault opening escape bounding, visible
  backpressure secondary returns, direct-core preference for close harvesters,
  core-approach-full fallback, splitter/passability correctness, bridge
  capacity realism, and core-delivery-port replay diagnostics. Latest cheap
  validation after cleanup: `python -m pytest tests/test_got_any_grapes_runtime_substrate.py
  tests/test_analyze_replay.py` passed 59 tests; `python -m compileall
  bots/got-any-grapes tools/analyze_replay.py` passed. No final commit yet; the
  next practical target is a small core-halo hygiene / local pack-behavior AFI,
  with no remote testing until implementation and cheap validation are complete.

## 2026-04-11 got-any-grapes defense/opportunism iteration

- User correction: offensive opponents need proactive defense, not just greed.
  Important split: `leeroy-jonkins` rushes the core and incidentally saps the
  economy; `jon-6-a9bfs-surround` actively suppresses lanes long-term.
- Implemented and retained for now:
  - new `defense.py`
  - core-rush sentinel response for non-assault FINDING_ORE / EXPLORING
    builders near the core
  - near-core lane sentinel response only when a visible friendly economy asset
    is already visibly damaged by nearby pressure
  - `TILING_BACK` builders are not peeled off lane construction
  - defense uses private unit state and visible perception only; no globals or
    illegal shared coordination
  - README rewritten to document current strategy, implementation map, and MAE
- Tried and rejected:
  - broad lane defense away from core: deterministic a9/leeroy smokes collapsed
  - movement-only shadowing/trailing of local enemies near undamaged lanes:
    deterministic a9 smoke collapsed to 176 delivered Ti and a loss
  - connected-lane gating for hijack and bonus assault: g16 collapsed to 31.2%
    overall, including 7-9 vs `jon-6`; reverted
- Latest cheap tests after reverting failed subideas:
  - `python -m pytest tests/test_got_any_grapes_runtime_substrate.py`: 69 passed
  - `python -m compileall bots/got-any-grapes`: passed
- Best defense-batch g16 evidence before reverting failed subideas:
  - 43.8% overall, avg TiEq 21,729, worst TiEq 0, local TLE turns 0
  - vs `jon-6`: 12-4, avg TiEq 33,429
  - vs `jon-6-a9bfs-surround`: 3-13, avg TiEq 15,934
  - vs `leeroy-jonkins`: 6-10, avg TiEq 15,823
  - local replay execTime fields were zero, so timing-pressure rates read 0.0
    and are not decision-grade for remote safety
- Decision: do not remote. The batch is not promotion- or validation-worthy.
  Keep the narrow defense primitives only as a revised local substrate, and use
  the next iteration for a separate front-patrol/proactive-border concept.
- Next target:
  - design a single bounded front patroller after first-lane evidence, operating
    at the outer logistics/frontier edge rather than chasing enemies inside the
    lane
  - must avoid broad scans, avoid stealing `TILING_BACK`, and must not suppress
    direct-core throughput vs `jon-6`
- Rejected reactionary lane-delay update, 2026-04-11: user suggested allowing
  a lone assault builder to cause a little damage before committing to defense.
  Tested a single-scratch tolerance plus immediate response to multiple nearby
  builders while keeping harvester/outlet hijack active. Smokes were mixed, but
  g16 failed hard at 16-32 overall / 33.3%: `jon-6` 10-6,
  `jon-6-a9bfs-surround` 3-13, `leeroy-jonkins` 3-13, avg TiEq 19,513.5,
  worst 0. Reverted to the prior visible-damage lane-defense gate.
- Rejected generic supply-line hijack, 2026-04-11: added direct sabotage of
  visible enemy conveyor-family tiles, first ungated and then gated to builders
  with no known titanium target. Deterministic smokes looked good, but g16
  exposed real emergent harm: ungated scored 18-30 overall / 37.5%, and the
  budgeted version scored 15-33 overall / 31.2%, including a collapse to 50%
  vs `jon-6`. Interpretation: generic supply sabotage over-peels the flex pool
  and hurts own economy more than it suppresses offensive opponents. Future
  hijack expansion needs legal pressure claims / stronger role budgeting before
  targeting non-harvester supply tiles.
- Rejected fed-sentinel hijack variant, 2026-04-11: tried the user's more
  modest sabotage framing where a builder already at a hijack outlet builds one
  fed sentinel around the enemy harvester only if the gun immediately covers a
  visible enemy builder or conveyor-family target. Focused tests passed, but
  deterministic smokes showed immediate harm: a9 collapsed to 10 scored
  titanium and lost badly, while jon/leery throughput also fell. Interpretation:
  the concept may still be strategically plausible, but this placement/timing
  poisons the hijack site or starves the lane. Reverted before g16.

## Medium-Term Emergent Strategy Notes

- Current emergent shape: the bot is still mostly a collection of strong local
  reflexes rather than a clean implicit team policy. Coordination comes through
  spawn-slot roles, action priority, visible local evidence, and assault claim
  markers, not through shared Python state.
- Current division of labor:
  - core creates early diagonal assault roles and economy roles by spawn slot
  - `TILING_BACK` builders are protected as lane constructors and should remain
    hard to steal because they are the units converting mined ore into TiEq
  - FINDING/EXPLORING builders are the flex pool for ore search, healing,
    hijack, and lane defense
  - assault builders coordinate mostly through claim markers and local anchor
    retirement
  - defense/hijack coordinate implicitly by priority order and visible evidence
- Current emergent weakness: the flex pool is overloaded. The same non-assault
  builder can become explorer, defender, healer, or hijacker based on one
  visible frame, which creates mode churn and inconsistent labor. Hijack also
  lacks a team-level budget, so aggressive sabotage can starve own lane
  construction if too many flex builders see enemy logistics.
- Current strongest implicit coordination rule: `TILING_BACK` is not stolen.
  Preserve that until a stronger legal marker-based construction-safety scheme
  exists.
- Medium-term AFI: role budgeting by local eligibility, not global managers.
  Keep lane constructors sacred; let only unattached FINDING/EXPLORING builders
  with no fresh titanium target take hijack/sabotage; let nearby multi-enemy
  pressure override that; eventually use safe markers as pressure claims so two
  builders do not chase the same enemy supply tile.
- Opponent mapping:
  - vs `jon-6`, avoid over-peeling flex builders so the direct-core economy
    remains intact
  - vs `leeroy-jonkins`, immediate core defense absorbs the rush while nearby
    flex builders punish exposed supply lines only when visible
  - vs `jon-6-a9bfs-surround`, spare/flex builders should apply economic
    sabotage to prevent long-term suppression from standing up
