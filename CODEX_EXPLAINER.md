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