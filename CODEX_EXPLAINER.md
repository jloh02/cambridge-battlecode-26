# Battlecode Lowdown

This file is the plain-English field manual for this repository.

It has three jobs:

1. explain the current Cambridge Battlecode rules that matter strategically
2. explain how this repository is wired and evaluated
3. record the engineering lessons that transfer from MIT Battlecode and recent
   decentralized multi-agent planning research

When something comes directly from the current Cambridge docs or changelog, it
is treated as documented fact. When something comes from local repo inspection
or bundled package inspection, it is labeled as a repo observation.

As of 2026-04-03 (after re-checking changelog/API docs and local CLI/runtime
`cambc 1.5.4`), prefer this file's reconciled merge of docs/changelog plus SDK
inspection when older examples or signatures disagree.

## 1. Current Rules Snapshot

Cambridge Battlecode is a turn-based programming game on a symmetric rectangular
grid.

Your team wins immediately if the enemy core is destroyed. If both cores survive
to the round cap, the game goes to resource tiebreaks.

Important documented facts:

- maps are between `20x20` and `50x50`
- official maps are symmetric by rotation or reflection
- each game lasts at most `2000` rounds
- ladder matches are exactly `5` games, not best-of-5
- the public ladder time limit is `2 ms` of CPU time per round on AWS
  Graviton3 hardware
- each bot process has a `1 GB` memory limit
- supported Python versions are `3.12` and `3.13`

Current tiebreak order after round `2000`:

1. delivered refined axionite
2. delivered titanium
3. harvesters alive
4. stored axionite
5. stored titanium
6. coinflip

This matters a lot for this repo: low-combat games are often decided by
delivered resources and survival of the logistics economy, not by mined totals.

Primary Cambridge docs:

- [Cambridge Battlecode](https://docs.battlecode.cam/)
- [Game Overview](https://docs.battlecode.cam/spec/overview)
- [Reference Tables](https://docs.battlecode.cam/spec/reference)
- [Resources](https://docs.battlecode.cam/spec/resources)
- [Controller](https://docs.battlecode.cam/api/controller)
- [Game Constants](https://docs.battlecode.cam/api/constants)
- [Types & Enums](https://docs.battlecode.cam/api/types)
- [Changelog](https://docs.battlecode.cam/changelog)

### Moderator Overrides / Local Authoritative Patch Notes

When moderator patch notes conflict with older examples, treat this list as the
repository's current source of truth.

Short local reconciliation table (docs/changelog vs local runtime `1.5.4`):

| Change | Docs/Changelog | Local runtime 1.5.4 | Note |
| --- | --- | --- | --- |
| `convert(amount)` on core (`1 Ax -> 4 Ti`) | yes | yes | now explicitly documented |
| gunner `rotate(direction)` / `can_rotate(direction)` | yes | yes | 2026-03-31 changelog confirms any-facing rotation for `10 Ti` |
| turret geometry helpers (`get_attackable_tiles*`, `can_fire_from`) | yes | yes | available via injected runtime controller |
| builder/harvester/foundry/breach/starting-passive economy values | yes | yes | values match changelog + `_types.py` |
| `SENTINEL_DAMAGE` value | docs constants page shows `18` | runtime/changelog show `10` | active inconsistency; verify via replay behavior before sentinel-heavy tuning |

Current local authoritative patch baseline:

- cores can `convert(amount)` to turn `1` refined axionite into `4` titanium
- the core occupies a `3x3` footprint for spawning, blocking, and map
  occupancy, but offensive targeting of the core is against the center tile
  only; shots that intersect only outer core tiles do not count as core shots
- sentinel reload is `3`
- gunner ax ammo damage is `30`
- gunner `rotate(direction)` costs `10 Ti`, takes `1` action cooldown, and
  now rotates to any target facing in one action
- harvesters cost `20 Ti` and add `+5%` scaling
- bridges cost `20 Ti` and add `+10%` scaling
- roads have `5 HP`
- builder base cost is `30 Ti`
- starting titanium is `500`
- teams gain passive `10 Ti` every `4` turns
- breach titanium cost is `15`
- foundry titanium cost is `40`
- armoured conveyors cost `5 Ti / 5 Ax`
- raw axionite sent to the core or turrets is destroyed
- builder self-destruct damage is removed
- builder attack is `2 Ti` for `2` damage on the acting tile only
- builder heal is `1 Ti` for `4 HP`
- gunners shoot past markers
- turret attacks hit only the builder bot if one stands on the building
- placing a non-walkable tile under another builder is fixed
- global unit cap is `50`
- in local runtime `1.5.4`, import constants as
  `from cambc import GameConstants`; there is no `cambc.constants` module
- relevant constant names include `MAX_TEAM_UNITS`, `STARTING_TITANIUM`,
  `PASSIVE_TITANIUM_AMOUNT`, `PASSIVE_TITANIUM_INTERVAL`,
  `AXIONITE_CONVERSION_TITANIUM_RATE`, `GUNNER_ROTATE_COST`,
  and `GUNNER_ROTATE_COOLDOWN`

Repo-local guidance tied to this patch:

- titanium-first is still correct, but axionite becomes relevant much earlier
  because harvesters and foundries are cheap and the core can now convert
  refined axionite into titanium
- bridges and sentinels are still not default infrastructure choices
- turret targeting must explicitly reject shots at enemy building tiles that are
  currently occupied by a friendly builder, because the shot will hit the
  builder instead of the building
- markers are unnamed `u32` payloads only; message semantics are repo-defined
- repo "action masks" are solution-local legality filters built from
  visibility, local memory, geometry, and final `can_*` checks
- internal economic diagnostics should track `economic_eq4 =
  delivered_titanium + 4 * delivered_refined_axionite`, while the official
  objective tuple remains authoritative

## 2. Core Game Pieces

This section only records the strategically important parts. Use the official
reference tables for the full stat matrix.

### Core

The core is your central building.

- if your core dies, you lose immediately
- the core acts every round
- it can spawn builder bots on one of its `3x3` core tiles
- the global unit cap includes the core

Useful controller calls:

- `c.can_spawn(position)`
- `c.spawn_builder(position)`
- `c.get_action_cooldown()`
- `c.get_unit_count()`

### Builder bot

The builder bot is the only mobile unit and the backbone of every strategy in
this repo.

It is responsible for:

- exploration
- roads and logistics setup
- harvesters and foundries
- turrets and barriers
- healing and friendly destruction
- local combat on its own tile via `fire()`

Current high-impact balance facts from the Cambridge changelog:

- builder base cost is now `30 Ti`
- builder scaling contribution is now `+20%`
- builder self-destruct no longer deals damage
- builder attack reuses `can_fire()` and `fire()` and costs `2 Ti` to deal `2`
  damage on the acting builder's tile
- builder heal costs `1 Ti` and restores `4 HP`

Practical implication:

- careless builder spam is now much more expensive than older starter code and
  older writeups may suggest

### Harvesters and foundries

Harvesters mine automatically from the ore tile they occupy.

Foundries refine one titanium stack plus one raw axionite stack into refined
axionite, and the core can now convert refined axionite into titanium.

Important documented rule:

- raw axionite sent directly to the core is destroyed
- raw axionite sent directly to turrets is also destroyed

Repo implication:

- a titanium-first opening is still strongly preferred
- axionite becomes worthwhile much earlier than before, but only with a real
  foundry-plus-convert plan

### Conveyors and logistics

Resources move in stacks of `10` during end-of-round distribution.

This repo mostly uses basic conveyors, but the game also includes splitters,
bridges, and armoured conveyors.

Practical implication:

- route direction matters
- bad layouts can stall or even feed the opponent
- there is no point mining resources if the route does not convert them into
  delivered tiebreak advantage

### Roads, barriers, and markers

Roads are cheap walkable infrastructure.

Barriers are cheap high-HP blockers.

Markers are strategically unique:

- they are free
- they do not cost action cooldown
- each unit may place at most one marker per round
- they store one unsigned 32-bit integer payload
- any allied unit can read allied markers
- globals are not shared between `Player` instances

Repo implication:

- markers are the only legal shared communication primitive
- marker "message kinds" are repo conventions layered on unnamed `u32` values
- dense marker spam is usually worse than event-driven marker use

### Turrets

The repo currently uses simple defense more than serious combat micro, but the
turret rules still matter:

- ammo must be fed through logistics
- raw axionite in turrets is destroyed
- sentinels are expensive under current scaling and not a default opening choice
- markers remain targetable by gunners but do not shield occupied tiles behind
  them

That last point matters because older assumptions about marker shielding are now
wrong.

## 3. Resources, Round Order, And Cost Scaling

### Resource objective

There are three practical resource notions:

- mined resources
- stored resources
- delivered resources

The official tiebreak uses delivered refined axionite first and delivered
titanium second. Mined totals are useful diagnostics, but they are not the
objective.

Repo evaluation note:

- internal throughput diagnostics should also track heuristic `economic_eq4` as
  `delivered_titanium + 4 * delivered_refined_axionite`
- this heuristic never replaces the official objective tuple for winner claims

### Round order

High-level documented order:

1. units take turns in spawn order
2. resources distribute after all units act
3. cooldowns tick down at end of round

Repo implication:

- builders can build a lane this round, but the lane only pays off during the
  later distribution phase
- speculative roads and conveyors should be judged by their effect on future
  delivered throughput, not by their existence alone

### Cost scaling

The game uses additive construction scaling.

Useful controller calls:

- `c.get_scale_percent()`
- `c.get_*_cost()`

Practical implication:

- overbuilding low-value roads, spare turrets, or excess builders hurts later
  economy
- foundries and advanced infrastructure are especially punishing if opened too
  early

## 4. Runtime And API Reality

### Runtime constraints

Documented facts:

- the real ladder budget is `2 ms` per round on AWS Graviton3
- local `cambc run` does not emulate that real remote timing budget
- `cambc match test` is the correct current CLI entrypoint for remote
  time-limit-risk checks with TLE enforcement (up to `5` maps per test run)
- `cambc match tests` lists your remote test runs

Repo policy:

- optimize for truthful behavior and objective performance first
- optimize for remote timing only after the strategy is correct and benchmarked

### API drift note

Cross-check against official docs/changelog on 2026-04-03:

- all `build_*` methods and `spawn_builder()` return the new entity's `int` ID
- core `convert(amount)` and gunner `rotate(direction)` are documented
- latest changelog (2026-03-31) clarifies gunner rotation as any-facing in one
  action
- turret geometry queries (`get_attackable_tiles*`) and
  `can_fire_from(...)` are documented

Known mismatch to watch:

- docs constants page currently lists `SENTINEL_DAMAGE = 18`, but changelog and
  local runtime `cambc 1.5.4` expose `SENTINEL_DAMAGE = 10`

When docs and runtime differ, prefer changelog + runtime/SDK evidence and
confirm behavior with replay evidence.

### SDK/runtime binding note (repo observation)

- local CLI in this repo env reports `cambc 1.5.4`
- practical constants import path is `from cambc import GameConstants`
- `cambc._types.Controller` is intentionally a runtime placeholder, and the
  real Rust-backed `Controller` type is injected before bot code runs
- full Python method signatures live in `TYPE_CHECKING` stubs in
  `cambc/_types.py`
- practical implication: `dir(Controller)` is not an authoritative API list;
  use docs/changelog plus `_types.py` signatures for method contracts
- if ad-hoc local Python imports fail outside the bot runner, use
  `cambc --version` plus docs/changelog as the authoritative immediate check
- environment note for this repo workflow: use `PYENV_VERSION=cambc` / `pyenv`
  env (`cambc`) rather than a project `.venv`
- throughput semantics check (docs + local `GameConstants`): there is no
  separate bridge-throughput constant. Conveyors/splitters/armoured/bridges all
  expose the same one-stack storage interface and resources move in stack-size
  quanta (`STACK_SIZE = 10`), so bridge usage should be tuned by route value and
  scaling cost, not by an assumed higher throughput cap

### Controller API in practice

The controller is the only way bots interact with the game.

Important query groups:

- entity info: `get_id`, `get_team`, `get_position`, `get_entity_type`,
  `get_hp`, `get_max_hp`
- tile info: `get_tile_env`, `get_tile_building_id`,
  `get_tile_builder_bot_id`, `is_tile_empty`, `is_tile_passable`
- nearby info: `get_nearby_tiles`, `get_nearby_entities`,
  `get_nearby_buildings`, `get_nearby_units`
- global state: `get_current_round`, `get_global_resources`,
  `get_scale_percent`, `get_unit_count`, `get_cpu_time_elapsed`
- actions: `move`, `build_*`, `spawn_builder`, `fire`, `heal`, `destroy`,
  `place_marker`, `draw_indicator_line`, `draw_indicator_dot`, `resign`

Important strategic truth:

- the API is ID-based and local
- if a strategy depends on invisible global truth that no unit can query or
  communicate, it is probably wrong

## 5. The Real Execution Model

This is the single most important modeling fact in the repo.

Documented facts:

- every unit gets its own isolated Python `Player` instance
- per-instance state persists only for that one unit across rounds
- globals are not shared between units
- markers are the only public shared communication mechanism

This repo is deliberately built around that model.

Bad pattern to avoid:

- a fake team-global Python manager that assumes one shared process controls all
  units

Correct pattern:

- each unit senses locally
- each unit stores only its own private memory
- cross-unit hints move through markers
- team-level evaluation happens offline in benchmarks and replay analysis, not
  inside a bot through illegal shared state

## 6. Repo Layout And Source Of Truth

### Canonical source layout

This checkout is organized around source bots under `bots/`.

- [bots/](bots/): canonical bot source directories; each runnable bot has its
  own folder containing `main.py`
- [bots/jon-5/](bots/jon-5/): current main candidate line
- [bots/jon-4/](bots/jon-4/): previous comparable line
- [bots/starter/](bots/starter/): simple reference bot
- [bots/none/](bots/none/): no-op baseline used for smoke tests
- [maps/](maps/): local map pool for iteration
- [tools/](tools/): repo-local helper scripts for packaging, benchmarking, and
  replay analysis

`cambc.toml` in this repo points directly at `bots/`, so source bot
directories are the current source of truth for local runs and direct
submissions.

### Optional primitive/reference package

`cambattle/` is present in this repo, but it is not the canonical layout that
defines how the current bot line is organized.

Use it as:

- a reference package for newer bot-writing patterns
- a place to collect reusable sensing / planning / execution primitives
- a comparison point when reviewing what `jon-5` does well or poorly

The current main bot, `jon-5`, remains a self-contained bot line under
`bots/jon-5/`.

### Tooling

The `tools/` directory is where repo-local helper scripts live. Some scripts
may drift as the repo evolves, so prefer direct `cambc` commands when in doubt.

Current important scripts in this checkout:

- [tools/build_bots.py](tools/build_bots.py): optional clean-bundle builder for
  `.dist/bots/`
- [tools/benchmark_matrix.py](tools/benchmark_matrix.py): matrix-style
  benchmark and promotion-gate helper
- [tools/analyze_replay.py](tools/analyze_replay.py): replay decoder and
  objective / stall analyzer
- [tools/report.py](tools/report.py): Markdown / CSV report rendering
- [tools/promotion_gate.py](tools/promotion_gate.py): staged promotion
  recommendation helper

### Generated outputs

Generated outputs are optional artifacts, not the repo's source of truth.

- `.dist/bots/`: optional clean bundles for submission or remote tests
- `.dist/replays/`: local replay files when tooling chooses to materialize them
- `.dist/reports/`: benchmark and comparison outputs
- `.dist/replay_analysis/`: decoded replay summaries

## 7. Current Strategy Lessons

### What MIT Battlecode teaches that still transfers

The games differ, but the engineering pattern is similar: decentralized agents,
strict compute limits, partial observability, congestion, and fragile local
coordination.

The most transferable lessons from MIT Battlecode postmortems and guides are:

- robust local primitives beat brittle strategy glue
- bounded local search with a fallback is usually better than aimless wandering
- symmetry inference is high leverage early
- congestion control matters as much as pathfinding elegance
- event-driven communication beats noisy continual signalling
- replay review is a first-class part of development, not an afterthought
- correctness and inspectability should come before bytecode/runtime tricks

Applied to Cambridge, that means:

- prefer bounded visible BFS plus recovery over “keep walking outward”
- avoid fake shared state and heavy coordination machinery
- keep marker protocols compact and intentional
- measure delivered-resource throughput, not just movement or mined totals

MIT Battlecode references worth reading:

- [2025 Just Woke Up postmortem](https://battlecode.org/assets/files/postmortem-2025-just-woke-up.pdf)
- [2024 Guide to Battlecode](https://battlecode.org/assets/files/battlecode-guide-xsquare.pdf)
- [2020 Java Best Waifu postmortem](https://battlecode.org/assets/files/postmortem-2020-java-best-waifu.pdf)
- [2021 Baby Ducks postmortem](https://web.mit.edu/agrebe/www/battlecode/21/index.html)

### What recent research suggests

Recent decentralized multi-agent planning literature points in the same
direction as the MIT practical lessons.

High-signal takeaways for this repo:

- information sharing is valuable under partial observability, but it should be
  compact and structured rather than broad and expensive
- congestion-aware path selection and conflict avoidance outperform agents that
  repeatedly contest the same corridor
- local cached world models or sector memories help under partial observability
  without requiring illegal team-global state
- auditable heuristics are often better engineering choices than opaque heavy
  planning when debugging decentralized bots

Useful research references:

- Liu and Zhang, 2023, “Partially Observable Multi-agent RL with
  (Quasi-)Efficiency: The Blessing of Information Sharing”
  ([PMLR](https://proceedings.mlr.press/v202/liu23ay.html))
- Musić et al., 2024, “Decentralized multi-agent path finding framework and
  strategies based on automated negotiation”
  ([Springer](https://link.springer.com/article/10.1007/s10458-024-09639-8))

Repo implication:

- sector memories, claimant penalties, stale-target TTLs, and replay-auditable
  fallback behaviors are better fits than big monolithic planners

## 8. Evaluation, Replays, And Workflow

### Objective-first evaluation

This repo now tracks more than wins.

The useful metrics split into two categories:

Primary outcome metrics:

- official winner and win condition
- delivered titanium
- delivered refined axionite
- `TiEq = delivered_titanium + 4 * delivered_refined_axionite`
- the early-win bonus policy documented in `CODEX_INSTRUCTIONS.md`

Secondary diagnostics:

- mined titanium and mined axionite
- harvesters alive
- stored axionite and stored titanium
- stall signals such as long no-progress streaks

This is deliberate. In many low-Elo or trap-map games, the decisive difference
is resource conversion quality, not combat or mined totals alone.

### Replay model

Useful replay/debug facts:

- `print()` output is recorded in the replay
- indicator lines and dots are replay-visible
- `cambc watch` opens the local visualizer
- `cambc match replay <match_id>` downloads remote replay files for offline
  inspection
- `cambc match watch <match_id>` opens a remote match replay in the browser
- the local replay analyzer decodes placements, moves, resource distribution,
  cooldowns, indicator usage, turret fire, and objective metrics

### Benchmark expectations

Local strategy work in this repo should:

1. add pytest coverage for the new behavior
2. run a targeted benchmark while iterating
3. run both seat orders before claiming improvement
4. inspect failure replays on the worst maps
5. judge results by objective metrics and worst-case behavior, not just an
   aggregate headline win rate

Current practical benchmark facts:

- the full repo map pool lives under `maps/`
- explicit opponent pinning is preferred when comparing candidate strategies
- the current promotion workflow is defined in `CODEX_INSTRUCTIONS.md`
- promotion claims should be based on randomized maps, seats, and seeds rather
  than one fixed matchup order

### Recommended local loop

Typical commands:

```bash
pyenv activate cambc
cambc run jon-5 none maps/default_small1.map26 --seed 1 --replay replay.replay26
cambc watch replay.replay26
cambc match test bots/jon-5 bots/jon-4 maps/default_small1.map26
python tools/benchmark_matrix.py jon-5 --opponents jon-4 --allow-single-opponent
python tools/report.py .dist/reports/benchmark_matrix.json
```

Local dev environment in this repo:

- pyenv virtualenv `cambc`
- `cambc` CLI
- `pytest`
- `protobuf`

Repo observation on 2026-04-03:

- local CLI currently reports `cambc 1.5.4`
- current CLI help exposes `cambc submission ...` and `cambc match ...`
  management subcommands as the preferred workflow
- legacy top-level aliases (`test-run`, `test-matches`, `matches`, `unrated`,
  `teams`, `init`) still exist as hidden compatibility commands with
  deprecation warnings

The project config in `cambc.toml` points at:

- `bots`
- `maps`
- `replay.replay26`

## 9. Submission Workflow

This repo treats `bots/<name>/` as the canonical source form of a bot.

Optional clean bundles under `.dist/bots/` are still useful when you want a
staged submission directory or a stripped-down remote test artifact, but they
are not the source of truth.

Submit flow:

1. validate the bot from source with `cambc run` or `cambc match test`
2. submit directly with `cambc submit bots/<bot>/` or
   `cambc submission upload bots/<bot>/`
3. `cambc submission list`
4. optional: `cambc submission rename <version> "<name>"`
5. optional: `cambc submission activate <version>`
6. optional: use `python tools/build_bots.py <bot>` first if you explicitly
   want a clean bundle under `.dist/bots/`

Current CLI workflow note:

- `cambc submit` is an alias for `cambc submission upload`
- the submission manager now also supports `list`, `rename`, `activate`, and
  `download`
- the match manager now exposes `info`, `list`, `replay`, `test`, `tests`,
  `unrated`, and `watch`

## 10. Most Important Takeaways

If you only remember a few things, remember these:

- unit Python state is private per unit
- markers are unnamed `u32` values; repo marker schemas are local conventions
- action masks are strategy-local legality filters, not an SDK feature
- raw axionite sent to the core or turrets is wasted
- the official objective is delivered-resource advantage, not mined totals
- internal `economic_eq4 = delivered_titanium + 4 * delivered_refined_axionite`
  can aid evaluation, but the official tiebreak order wins
- speculative infrastructure is only good if it improves future throughput
- local `cambc run` is not the final timing truth; `cambc match test` is
- `bots/` is the canonical layout; `cambattle/*` is a reusable primitive /
  reference package rather than the defining source layout
- MIT-style lessons that transfer best are robust primitives, bounded search,
  fallback recovery, compact communication, and aggressive replay review

## Appendix A. Controller Query Addendum (2026-04-02)

This section appends a clarification that matters for hot-path sensing code.
It does not replace the earlier controller summary; it narrows which query to
prefer when several overlap.

These method names were re-checked against the official current controller docs
and the current `https://docs.battlecode.cam/llms-full.txt` export.

### Prefer these nearby queries

- `get_nearby_units()`:
  use this when you need visible units only. This includes builder bots, cores,
  and turrets. It is usually the right replacement when older code reached for
  `get_nearby_entities()` but only cared about unit occupancy or enemy units.
- `get_nearby_buildings()`:
  use this when you need visible buildings only. This covers conveyors,
  harvesters, markers, foundries, bridges, roads, and barriers.
- `get_nearby_entities()`:
  treat this as the broad but expensive union query. Prefer it only when the
  code genuinely needs both units and buildings and you do not already have a
  cheaper split query or tile-derived snapshot.

### Prefer these tile queries

- `get_tile_builder_bot_id(pos)`:
  this only exposes builder-bot occupancy on a tile. It is useful for
  reconstructing nearby builder positions from a tile scan, but it is not a
  general "get any unit on this tile" helper.
- `get_tile_building_id(pos)`:
  this is the tile-side companion for building occupancy. It is the right way
  to recover visible buildings while iterating nearby tiles.
- `is_in_vision(pos)`:
  use this to cheaply guard local memory updates or stale-map cleanup when the
  code wants to know whether a remembered tile is currently observable without
  re-querying the full neighborhood.

Practical rule of thumb for this repo:

- tile walk plus `get_tile_building_id()` plus `get_tile_builder_bot_id()` is a
  good building/builder snapshot
- `get_nearby_units()` is still required if you need cores or turrets without a
  broader entity scan
- `get_nearby_entities()` should be the fallback, not the default

## Appendix B. Updated Tool Commands

Some older examples above still show the legacy matrix CLI shape. Use these
commands now:

```bash
python tools/benchmark.py jon-5 jon-4 --games 2
python tools/benchmark_matrix.py jon-5o jon-5 --games-per-opponent 4
python tools/analyze_replay.py file replay.replay26
python tools/analyze_replay.py match <match_id>
python tools/analyze_replay.py latest
python tools/report.py .dist/reports/jon-5o_vs_jon-5_matrix.json
```

## Appendix C. `duck-1` AFI integration snapshot

`duck-1` is a `jon-5o`-derived line under `bots/duck-1/` that applies
incremental AFI fixes without replacing the existing FSM.

What is now integrated in `duck-1`:

- **marker discipline restored**
  - marker placement is live (`utils.place_marker_around`)
  - ore/share/explore-claim marker paths are active
- **primitive logistics boundary added**
  - `bots/duck-1/logistics.py` centralizes route-sink tracing and
    conveyor/bridge legality checks
  - mode/navigation call this helper instead of open-coding safety rules
- **typed sensing slice added**
  - perception publishes a per-turn typed snapshot (`TurnSnapshot`) to reduce
    ad hoc state coupling in decisions
- **bottleneck and safety policy hardened**
  - core-adjacent congestion bias helps bridge policy when corridors are crowded
  - no-enemy-feed guard is enforced during pending/live/lookahead builds
- **lightweight survivability**
  - harvester-adjacent barrier placement under nearby enemy pressure

Current local validation snapshot for this revision:

- sampled set: 8 replays (`duck-1` vs `jon-5o`, `jon-5`, `none`)
- observed team-A transport feed events into team-B core tiles: **0**
- sampled foundry activation exists but is sparse
- refined-axionite delivery remains minimal, so `duck-1` is still
  titanium-dominant and not yet promotion-ready versus `jon-5`/`jon-5o`


### 2026-04-03: R1 re-land policy note

Per explicit strategic directive, `duck-1` re-lands the R1 traceback fix bundle even though
head-to-head `jon-5`/`jon-5o` metrics are not a promotion improvement.

R1 code-level effect:
- relaxes bridge-expansion over-pruning in `navigation.calculate_astar_path`
- uses direct bridge-transit A* in `mode_tiling_back` instead of micro-plan-first
- restores unconditional traceback annotations (`indicator_dot` on A* failure,
  `indicator_line` on move target) for replay forensics parity with `jon-5`

Rationale for keeping anyway:
- the stricter `jon-5o` pruning/transit stack appears tuned to those bots' local behavior
  and can under-explore alternate bridge landings under heavy clutter
- R1 restores search breadth and direct transit continuity, which is expected to transfer
  better against unknown opponents that mount stronger assaults and broader map-pressure
- this is a deliberate exploration-vs-stability trade: we accept current matchup regression
  while testing whether longer-horizon logistics adaptability improves against wider fields

Validation artifacts:
- `.dist/reports/duck1_step30_r1_reland_g16_jobs8.json`
  (aggregate: 65.6% WR, avg TiEq 23513.1, worst 3710, TLE 0)
- `.dist/reports/duck1_step30c_r1plusdebug_g16_jobs8.json`
  (aggregate: 53.1% WR, avg TiEq 22129.4, worst 0, TLE 0)

These two g16 reports were run on separate random schedules (`schedule_seed=1`
by default, but with different prior random-state consumption across earlier
runs), so they should be interpreted as a variance band rather than contradictory
measurements of a single fixed schedule.

### 2026-04-03: AFI-9 forensic outcome and AFI-10 policy direction

AFI-9 (core-first traceback before augmentation) was evaluated against the
R1 g64 two-seed baseline and kept on a resilience-first criterion:

- WR was effectively neutral over 256 paired schedule games
  (`127/256` vs baseline `128/256`; paired flips `46` up / `47` down).
- TiEq improved materially and consistently:
  - aggregate avg TiEq: `+2037.7`
  - lower tail improved (`p10`: `+3580`, `<=5k` games `27 -> 21`, zeros `11 -> 8`)
  - bootstrap 95% CI for TiEq delta: `+574.7` to `+3416.1`
- Interpretation: AFI-9 did not solve the win gate, but it reduced catastrophic
  economic collapse frequency while preserving matchup parity.

AFI-10 then follows a specific bridge-policy framing:

- Do **not** assume bridge-specific throughput behavior in game rules.
- Instead, score bridge expansion by immediate route value:
  - exact-target bridge landings are strongly favored,
  - reconnecting known connected logistics lines is favored,
  - sideways/backwards/no-progress bridge jumps remain legal but are penalized.
- This preserves R1’s breadth (avoid over-pruning) while adding explicit
  value-based shaping so bridge use is not blindly aggressive.

### 2026-04-03: AFI-10 outcome and AFI-11 direction

AFI-10 (value-scored bridge expansion) was evaluated over g64 seed1 + seed2 and
**deferred**.

- Against AFI-9 (paired schedules, 256 games):
  - WR: unchanged (`127/256` both variants)
  - avg TiEq: `-1451.2`
  - catastrophic tails worsened (`<=5k`: `21 -> 29`, zeros: `8 -> 14`)
  - bootstrap 95% CI for TiEq delta (`AFI-10 - AFI-9`): `-2904.3` to `+130.5`
- Interpretation: the bridge-value scoring hypothesis had localized upside on
  some maps, but introduced broad tail fragility and did not survive seed2
  confirmation.

AFI-11 now targets architecture hardening with low behavior risk:

- perception now exports a typed `TurnSnapshot` bundle for each turn
  (full-scan and fast-scan paths),
- this tightens the sensing boundary and removes loose tuple plumbing without
  changing macro economy or route policy.

### 2026-04-03: AFI-11 outcome

AFI-11 (typed sensing snapshot boundary) was tested on g64 seed1 + seed2 and
**deferred**.

- Compared with AFI-9 over paired schedules (256 games):
  - WR dropped from `127/256` to `119/256` (`-3.12 pp`)
  - `jon-5` stayed flat (`49.2%` vs `49.2%`), but `jon-5o` regressed
    (`43.8%` vs `50.0%`)
  - avg TiEq delta was mildly negative/inconclusive (`-444.6`, bootstrap 95% CI
    `-1812.3` to `+995.1`)
  - low-tail worsened (`<=5k`: `21 -> 23`, zeros: `8 -> 10`)
- Interpretation: despite being an architecture-focused change, this edit path
  was not behavior-preserving enough for the current ladder and is folded.

### 2026-04-03: AFI-4 second-pass decision (A1 vs A2)

AFI-4 focuses on disconnected-lane recovery: when a builder's last harvester is
still alive but no longer adjacent to any core-connected conveyor tile, the bot
can briefly re-enter `TILING_BACK` to repair that route.

Two AFI-4 variants were run with the same g64 two-seed protocol:

- **A1 (step 37)**: simple cooldown-triggered reconnect attempt.
- **A2 (step 38)**: tighter guards (round, topology size, distance) intended to
  reduce economic regressions.

Outcome:

- A2 did **not** fix AFI-4's quality regressions and also reduced the win uplift.
- Paired vs AFI-9 over 256 games:
  - A1: wins `127 -> 143` (+6.25 pp), avg TiEq `-1.05k`
  - A2: wins `127 -> 132` (+1.95 pp), avg TiEq `-1.11k`
- Direct paired A1 vs A2:
  - wins `143 -> 132` (A2 worse by `-4.30 pp`)
  - no reliable TiEq/tail improvement to compensate.

Decision:

- **Keep AFI-4 A1**, **defer A2**.
- This is a deliberate tradeoff: A1 is win-tilted but still tail-fragile versus
  AFI-9, so follow-up work should target low-tail economics without surrendering
  the recovered matchup pressure.

### 2026-04-03: AFI-13 A1 outcome (`jon-6` primitive port)

AFI-13 A1 ported selected `jon-6` throughput primitives into `duck-1`:

- load-aware connected-conveyor scoring in return-target selection and path cost
- connected-lane load inference from harvester adjacency in perception
- ore deconfliction for already-connected/claimed harvesters

It was tested with the required g64 two-seed protocol against the active
three-opponent set (`jon-5o`, `jon-6`, `jon-5o-a1`) and **deferred**.

- Seed1 (`4101`) improved aggregate WR and TiEq (`44.8%`, `23.07k` avg),
  but seed2 (`4102`) dropped aggregate WR to `36.5%` while TiEq rose to `24.63k`.
- Combined (384 games) vs step40 baseline:
  - WR slipped `41.4% -> 40.6%` (`159 -> 156` wins)
  - avg TiEq improved `21.13k -> 23.85k` (`+2.72k`)
  - worst TiEq stayed `0`
  - low-tail counts improved (`<=5k`: `58 -> 47`, zeros `18 -> 17`)
- Opponent split:
  - `jon-5o`: slight WR lift (`46.1% -> 46.9%`)
  - `jon-5o-a1`: WR drop (`46.9% -> 44.5%`)
  - `jon-6`: still weak and slightly worse (`31.3% -> 30.5%`)

Interpretation: this variant improves economic shape (higher average TiEq and
fewer catastrophe-tail games) but does not improve win outcomes on the hardest
matchups, so it is not a keep candidate under the current ladder decision rule.

### 2026-04-03: AFI-4 A1 repair reland after `jon-5o-a1` import (step42)

After the broad `jon-5o-a1` sync, the disconnected-harvester repair retry path
from AFI-4 A1 was no longer active in `mode_finding_ore.py`. Step42 re-landed
that logic on top of the AFI-13 baseline:

- when the bot's last harvester is still friendly but disconnected from any
  core-connected conveyor neighbor, it re-enters `TILING_BACK`
- retries are cooldown-gated (`90` rounds) to avoid per-turn mode thrash
- reland is integrated with current `jon-5o-a1` state reset helpers so it does
  not fork separate reset code paths

Two-seed g64 confirmation (`4101`, `4102`) versus the active three-opponent set:

- step41 (AFI-13 baseline): `156/384` wins (`40.6%`), avg TiEq `23.85k`
- step42 (AFI-4 A1 reland): `180/384` wins (`46.9%`), avg TiEq `24.78k`
- deltas: WR `+6.25 pp`, avg TiEq `+0.93k`, low-tail `<=5k` improved `47 -> 39`

Opponent split:

- `jon-5o`: WR `46.9% -> 58.6%`, avg TiEq `25.06k -> 26.45k`
- `jon-5o-a1`: WR `44.5% -> 52.3%`, avg TiEq `27.37k -> 28.63k`
- `jon-6`: WR `30.5% -> 29.7%` (flat/slightly down), avg TiEq `19.12k -> 19.25k`

Disposition: **keep** this reland. It restores the strongest AFI-4 behavior on
the imported baseline and materially improves aggregate outcomes, while leaving
the `jon-6` weakness as the next isolated problem.

### 2026-04-04: AFI-13 A2 light assault-gating constants pass (step43)

Before the broader integrated step44 bundle, a narrower AFI-13 A2 constant pass
was evaluated (quota/threshold tuning only).

Two-seed g64 (`4101`, `4102`) vs the active set (`jon-5o`, `jon-6`, `jon-5o-a1`)
was **deferred/folded** because the aggregate signal did not clear keep criteria.

Paired vs step42 over 384 games:

- wins: unchanged `180 -> 180` (`46.9% -> 46.9%`)
- avg TiEq: `24.78k -> 24.59k` (`-0.18k`)
- worst TiEq: unchanged `0`
- low-tail: `<=5k` worsened `39 -> 43` (zeros improved `16 -> 11`)
- paired flips were exactly balanced (`74` up / `74` down)

Opponent split was mixed:

- `jon-5o`: flat WR (`58.6%`) with higher avg TiEq (`+1.11k`)
- `jon-5o-a1`: slight WR drop (`52.3% -> 51.6%`)
- `jon-6`: slight WR lift (`29.7% -> 30.5%`) but avg TiEq down (`19.25k -> 17.47k`)

Interpretation: this pass looked like a parameter shuffle rather than a robust
improvement. It neither improved wins nor strengthened tail economics at the
combined-set level, so it was correctly folded.

### 2026-04-04: AFI-13 A2 integrated assault/symmetry bundle outcome (step44)

A broad AFI-13 A2 pass was evaluated with the new assault stack integrated:

- new assault helper module (`assault.py`) and assault mode (`mode_assaulting.py`)
- builder role wiring (`ASSAULTING` mode activation from spawn-slot identity)
- expanded perception and navigation support for hostile targeting and inference
- supporting marker/state plumbing

Two-seed g64 (`4101`, `4102`) against `jon-5o`, `jon-6`, and `jon-5o-a1`
showed a clear regression versus step42 baseline and was folded.

Combined paired result over 384 games:

- wins: `180 -> 114` (`46.9% -> 29.7%`, `-17.19 pp`)
- avg TiEq: `24.78k -> 16.34k` (`-8.43k`)
- worst TiEq: remained `0`
- low-tail collapse: `<=5k` games `39 -> 101`, zeros `16 -> 45`
- paired flips: `53` up vs `119` down (net strongly negative)

Per-opponent split:

- `jon-5o`: WR `58.6% -> 32.0%`, avg TiEq `26.45k -> 16.74k`
- `jon-5o-a1`: WR `52.3% -> 28.9%`, avg TiEq `28.63k -> 18.57k`
- `jon-6`: WR `29.7% -> 28.1%`, avg TiEq `19.25k -> 13.71k`

Interpretation:

- The regression pattern is economy starvation, not timeout failure (`TLE turns` stayed 0).
- The broad role wiring effectively diverted too many builders into assault
  behavior before a stable throughput base existed, causing catastrophic early
  delivery shortfalls across all opponents.
- This confirms the prior hypothesis from AFI-4/AFI-13 history: broad tactical
  aggression can improve isolated pressure moments but is net-negative when it
  cannibalizes early lane completion.

### 2026-04-04: AFI-13 A3 constrained-assault recovery (step45)

To isolate the root cause from step44, assault activation was narrowed to a
bounded policy instead of removing the assault stack entirely:

- only specific spawn slot(s) are eligible for assault role
- assault mode is disabled before a late-round threshold
- assault mode additionally requires minimum connected-harvester maturity

This preserves the imported assault primitives while preventing early
economy cannibalization.

Two-seed g64 (`4101`, `4102`) vs `jon-5o`, `jon-6`, `jon-5o-a1`:

- seed4101: `57.3%` WR, avg TiEq `25.30k`
- seed4102: `44.3%` WR, avg TiEq `24.65k`

Combined paired vs step42 baseline (384 games):

- wins: `180 -> 195` (`46.9% -> 50.8%`, `+3.91 pp`)
- avg TiEq: `24.78k -> 24.98k` (`+0.20k`)
- worst TiEq: unchanged at `0`
- low-tail: `<=5k` `39 -> 52`, zeros `16 -> 20`
- paired flips: `92` up vs `77` down (net positive)

Per-opponent split:

- `jon-5o`: WR `58.6% -> 59.4%`, avg TiEq `26.45k -> 25.90k`
- `jon-5o-a1`: WR `52.3% -> 60.2%`, avg TiEq `28.63k -> 28.91k`
- `jon-6`: WR `29.7% -> 32.8%`, avg TiEq `19.25k -> 20.12k`

Interpretation:

- The gating fix validates the step44 diagnosis: the main damage came from
  **when and how broadly** assault activated, not from the assault primitives
  themselves.
- The kept A3 variant improves aggregate wins and maintains TiEq level while
  keeping TLE at zero, but still leaves a visible catastrophic-tail gap and
  substantial seed variance. It is therefore a keep-with-caveat, not an end state.

### 2026-04-04: AFI-13 A4 hysteresis/live-load assault gate outcome (step46)

A follow-up pass replaced the step45 assault gate with a live connected-lane
load + entry/hold hysteresis + resource-threshold policy. The hypothesis was to
remove stale historical readiness bias while preserving economic safety.

Two-seed g64 (`4101`, `4102`) vs `jon-5o`, `jon-6`, `jon-5o-a1`:

- seed4101: `46.4%` WR, avg TiEq `24.94k`
- seed4102: `49.0%` WR, avg TiEq `25.91k`

Combined paired vs step45 baseline (384 games):

- wins: `195 -> 183` (`50.8% -> 47.7%`, `-3.12 pp`)
- avg TiEq: `24.98k -> 25.42k` (`+0.45k`)
- worst TiEq: unchanged at `0`
- low-tail: `<=5k` `52 -> 51`, zeros `20 -> 20` (essentially flat)

Opponent split vs step45:

- `jon-5o`: WR `59.4% -> 50.0%` (material regression)
- `jon-5o-a1`: WR `60.2% -> 57.8%` (regression)
- `jon-6`: WR `32.8% -> 35.2%` (improvement)

Cross-check vs step42:

- wins: `180 -> 183` (`+0.78 pp`) only marginally better
- avg TiEq: `24.78k -> 25.42k` (`+0.65k`)
- catastrophic tails worsened: `<=5k` `39 -> 51`, zeros `16 -> 20`

Interpretation:

- Step46 shifted emphasis toward throughput shape but gave back too much matchup
  robustness where current ladder pressure is highest (`jon-5o` family).
- The result does not beat the kept step45 compromise on the combined objective
  (wins first, TiEq second, tails guarded).
- Final disposition: **fold step46 and keep step45 gating as active baseline**.

### 2026-04-04: AFI-13 A5 entry-only titanium assault gate outcome (step47)

A narrower follow-up to step46 added an entry-only titanium guard for assault
activation while keeping the step45 assault structure.

Two-seed g64 (`4101`, `4102`) vs `jon-5o`, `jon-6`, `jon-5o-a1`:

- step47 seed4101: `51.6%` WR, avg TiEq `24.41k`
- step47 seed4102: `48.4%` WR, avg TiEq `25.16k`

Combined paired vs kept step45 baseline (384 games):

- wins: `195 -> 192` (`50.8% -> 50.0%`, `-0.78 pp`)
- avg TiEq: `24.98k -> 24.79k` (`-0.19k`)
- worst TiEq: unchanged at `0`
- low-tail: `<=5k` `52 -> 53`, zeros `20 -> 28`
- paired flips: `68` up vs `71` down (net-negative)

Per-opponent split vs step45:

- `jon-5o`: wins `76 -> 70` (WR `59.4% -> 54.7%`), avg TiEq `25.90k -> 26.01k`
- `jon-5o-a1`: wins `77 -> 79` (WR `60.2% -> 61.7%`), avg TiEq `28.91k -> 29.69k`
- `jon-6`: wins `42 -> 43` (WR `32.8% -> 33.6%`), avg TiEq `20.12k -> 18.66k`

Interpretation:

- The entry-only guard did not produce a robust win/quality improvement over the
  kept step45 compromise.
- The key warning sign is catastrophic-tail worsening (zeros `+8`) with no
  compensating aggregate gain.
- Final disposition: **fold step47 and keep step45 baseline**.

### 2026-04-04: AFI-7 A3 foundry/convert wiring outcome (step48)

Step48 attempted to wire an explicit foundry + convert activation path
(axionite eligibility gates, foundry construction hooks, and core convert policy)
and was first checked with a smoke run before promotion-scale benchmarking.

Smoke g4 (`seed4101`) result:

- aggregate WR `41.7%`, avg TiEq `27.20k`, worst `0`
- but mechanism-activation diagnostics were flatlined:
  - total candidate mined axionite: `0`
  - total candidate delivered refined axionite: `0`
  - all opponents in the smoke had `0` for both metrics

Interpretation:

- This is a mechanism failure, not just a weak top-line metric outcome.
- The intended AFI-7 pathway did not activate at all, so there is no support for
  carrying this variant into full g64 decision runs.
- Final disposition: **fold step48, revert to step45 baseline behavior, and
  redesign AFI-7 around activation-first proof before promotion benchmarking**.

### 2026-04-04: AFI-7 A4 activation-first retry outcome (step49)

Step49 attempted a narrower activation-first retry:

- forced periodic axionite probe targeting in `FINDING_ORE` under mature-economy
  gates
- core-side convert guard for spare axionite under spawn-pressure checks
- no assault-gating changes (kept step45 combat/economy boundary)

Smoke g4 (`seed4101`) vs `jon-5o`, `jon-6`, `jon-5o-a1`:

- aggregate WR `50.0%` (vs post-fold step45 smoke `66.7%`)
- avg TiEq `26.12k` (vs `25.62k`)
- worst TiEq remained `0`

Mechanism diagnostics remained flatlined:

- total candidate mined axionite: `0`
- total candidate delivered refined axionite: `0`
- all three opponents remained `0` for both metrics

Interpretation:

- This retry still failed the AFI-7 intent on first principles: no axionite
  mining, no refined delivery, therefore no foundry-plus-convert activation.
- The small TiEq average uplift is not actionable because it came without the
  target mechanism and with lower smoke wins.
- Final disposition: **fold step49 and restore step45 baseline behavior**.

### 2026-04-04: AFI-7 A5 gated axionite-eligibility retry outcome (step50)

Step50 tested a narrower variant than step49: re-open axionite in ore-eligibility
selection under economy gates (resource/round/connected-harvester maturity),
without adding convert/foundry execution logic.

Smoke g4 (`seed4101`) vs `jon-5o`, `jon-6`, `jon-5o-a1`:

- aggregate WR `50.0%` (vs post-fold step45 smoke `66.7%`)
- avg TiEq `28.36k` (vs `25.62k`)
- worst TiEq remained `0`

Mechanism diagnostics still flatlined:

- total candidate mined axionite: `0`
- total candidate delivered refined axionite: `0`
- all opponents remained `0` for both metrics

Interpretation:

- This confirms the underlying blockage is deeper than simple ore-eligibility
  reopening; the AFI-7 mechanism still never turns on in live games.
- The TiEq average uplift is non-mechanistic under AFI-7 criteria and does not
  justify promotion because activation stayed zero and smoke wins fell.
- Final disposition: **fold step50 and keep step45 baseline behavior**.

### 2026-04-04: AFI-7 A6 axionite probe-cap target-injection outcome (step51)

Step51 tested a stricter activation-first pass: keep step50-style gated axionite
eligibility, then inject a bounded per-bot axionite target probe in
`mode_finding_ore` to force at least some direct axionite-harvester commits.

Smoke g4 (`seed4101`) vs `jon-5o`, `jon-6`, `jon-5o-a1`:

- aggregate WR `50.0%` (vs post-fold step45 smoke `66.7%`)
- avg TiEq `21.57k` (vs `25.62k`)
- worst TiEq remained `0`

Mechanism diagnostics changed from previous AFI-7 retries:

- candidate axionite harvester placements: `50` (titanium harvester placements `133`)
- candidate raw-axionite transfer events observed: non-zero across most games
- candidate foundry placements: `0`
- candidate delivered refined axionite: `0` (all opponents)

Interpretation:

- Step51 is a **partial mechanism activation**: it proves ore-target commitment to
  axionite can be forced, so the previous "never picks axionite tiles" blockage is
  no longer the primary root cause.
- The remaining hard blocker is downstream: foundry/convert pipeline still never
  activates (no foundry placement, no refined delivery), so AFI-7 intent remains
  unmet.
- Because top-line smoke also regressed, final disposition is **fold step51** and
  keep step45 baseline behavior while shifting AFI-7 focus from ore targeting to
  first-foundry activation.

### 2026-04-04: AFI-7 A7 foundry-anchor lifecycle + return/convert wiring outcome (step52)

Step52 explored scaffold repair and lifecycle wiring around AFI-7 activation.

Smoke g4 (`seed4101`) variants:

- step52a (initial wiring): WR `58.3%`, avg TiEq `26.93k`, worst `0`
- step52b (BFS eligibility fix): WR `66.7%`, avg TiEq `31.20k`, worst `0`
- step52c (forced bootstrap axionite): WR `41.7%`, avg TiEq `25.24k`, worst `0`

Mechanism diagnostics remained non-activating across the variants:

- candidate mined axionite: `0`
- candidate delivered refined axionite: `0`

Interpretation:

- Topline movement in step52b did not come with AFI-7 mechanism activation.
- Forcing the bootstrap axis (step52c) hurt outcomes without turning on refined
  throughput.
- Final disposition: **fold step52 AFI-7 behavior** and continue from baseline
  policy.
