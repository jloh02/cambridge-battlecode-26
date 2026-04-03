# `jon-5` Report And Repo KPI Notes

This file is the working report for `jon-5`: what it does today, how to think
about it, and what the current improvement direction should be.

## 1. What `jon-5` is trying to do

`jon-5` is a self-contained bot line under `bots/jon-5/`.

Its core idea is simple:

1. spawn enough builders to establish an early economy
2. let each builder independently find nearby titanium
3. build a harvester once adjacent to a target ore tile
4. tile a conveyor / bridge route back toward the core or an already-connected
   friendly logistics line
5. return to ore-finding and repeat

It is not a general-purpose combat bot. It is an economy-first bot whose main
goal is to convert visible titanium into delivered-resource throughput quickly
and robustly.

## 2. Core behavior

The core logic in `core_bot.py` is intentionally lightweight.

Current policy:

- keep spawning until a minimum builder count is reached
- after that, continue spawning on a coarse interval when titanium is within a
  target band
- bias some spawns in the direction of known ore markers, but otherwise cycle
  through shuffled adjacent directions

This is a practical, low-compute opener rather than a tightly optimized one.
The core is mostly trying to ensure that builder production does not stall
completely and that newly spawned builders do not all pile into the same lane.

## 3. Builder FSM

Every builder owns its own persistent Python state. There is no shared Python
manager across units. The builder FSM has three modes:

### `FINDING_ORE`

The builder looks for the best visible titanium target.

Important details:

- it prefers titanium over axionite; the axionite plan is still unfinished
- it uses remembered local state plus nearby friendly builder positions to avoid
  obviously redundant ore picks
- once adjacent to the ore, it builds a harvester and switches to `TILING_BACK`

### `TILING_BACK`

This is the most important `jon-5` mode.

The builder plans a route from the new harvester back to either:

- the core area, or
- a friendly conveyor / bridge segment already known to feed the core

Along the way it:

- uses bounded A* rather than unbounded wandering
- prefers snapping onto existing friendly logistics
- may clear roads, markers, or misaligned conveyors that block the intended
  route
- can plan bridge hops when clutter makes a direct conveyor line too awkward

This is the mode that gives `jon-5` most of its strength. The bot is not just
finding ore; it is trying to finish a working route that actually delivers.

### `EXPLORING`

If the builder does not currently have a good ore target, it switches to
chunk-based exploration.

Important details:

- the map is divided into coarse chunks derived from builder vision
- exploration tries to spread builders out using local ally positions
- stuck targets are retried a few times, then blacklisted

This is a pragmatic fog-clearing mode, not a sophisticated scouting system.

## 4. Private memory model

`jon-5` works because each builder keeps a substantial local memory bundle.

The main pieces are:

- `grid`: a sparse remembered world model keyed by `(x, y)` tuples
- ore sets: remembered titanium and axionite locations
- ally locations: nearby friendly builder positions for local deconfliction
- known and connected conveyor sets: remembered friendly logistics structure
- pathfinding cache: current target, cached path, temporary obstacles, replan
  signatures
- exploration state: explored chunks, claimed targets, unreachable chunks
- tiling state: last harvester position, pending build orders, bridge transit
  bookkeeping, current return target

This is still per-unit private memory. Cross-unit coordination only works
through markers on the map.

## 5. Why `jon-5` currently works

The bot's strongest design decisions are architectural rather than flashy:

- it keeps pathfinding bounded, so it does not burn the whole turn budget on
  one failed route
- it caches paths and trims them when only part of the route becomes invalid
- it distinguishes “known friendly conveyor” from “known conveyor that actually
  reaches core”
- it combines movement and logistics construction in the same tiling-back loop,
  which is exactly the right place to spend complexity
- it is robust enough to run directly in the current `bots/` workflow without
  any wrapper layer

In short: `jon-5` does a useful thing repeatedly and usually finishes the last
step that matters, namely a route that delivers.

## 6. Current intended improvement direction

These are the active improvement directions to carry forward. They describe what
we should improve next, not code changes already made.

### Restore useful marker coordination

The bot already has the idea of marker-based coordination:

- ore markers
- exploration claims
- connected-conveyor markers

But this layer is incomplete. In particular, marker placement is currently
stubbed out at the utility level, so some of the intended sharing never leaves
the local bot state.

Priority:

- make marker writes real again
- keep the schema compact
- use markers for deconfliction and route hints, not noisy continuous chatter

### Add an actual axionite plan

`jon-5` is still effectively titanium-first only.

That means it is leaving value on the table now that:

- harvesters and foundries are cheap enough to matter
- refined axionite can be converted by the core into titanium

The next step is not “mine random axionite”. The next step is a real
foundry-plus-convert plan with clear timing and lane-shape rules.

### Improve congestion handling

The bot has decent local obstacle handling, but congestion is still handled by
heuristics rather than explicit lane policy.

Important future work:

- reduce duplicate builders contesting the same ore or return corridor
- reduce accidental damage to useful friendly logistics while reconfiguring
- improve queueing around crowded core-adjacent delivery lanes

### Add defense and survival behaviors

`jon-5` is mostly an economic machine. It does not yet have a convincing
defensive layer.

Important future work:

- protect harvesters and key lanes
- react to rushes on the core
- use healing and cheap blocking infrastructure more intentionally

### Migrate good ideas onto cleaner primitives incrementally

`jon-5` already contains useful tactics. The mistake would be to throw them out
in favor of a clean architecture with weaker behavior.

The right direction is:

- keep the strong local behavior
- extract reusable pieces gradually
- borrow cleaner primitive boundaries from `cambattle` only where they improve
  testability and reasoning

## 7. KPI policy

The repo should track both delivered outcomes and mined/collected diagnostics.

### Primary KPI: `TiEq`

Authoritative definition:

`TiEq = delivered_titanium + 4 * delivered_refined_axionite + early_win_bonus`

where:

- `early_win_bonus = 100000` if the bot wins before turn `2000`
- otherwise `early_win_bonus = 0`

Important note:

- `TiEq` is based on what is actually delivered to the core
- mined / collected totals are useful diagnostics, but they are not the KPI

### Secondary diagnostics

These should still be recorded when possible:

- mined titanium
- mined axionite
- delivered titanium
- delivered refined axionite
- harvesters alive
- stored titanium
- stored axionite
- stall / loop signals from replay analysis

## 8. Promotion rule

A bot is promotion-worthy against a studied opponent set if and only if, for
every opponent in the set, it satisfies all of the following over `32` games:

- random map
- random seat
- random seed
- win rate `>= 80%`
- average `TiEq >= 100000`
- worst-game `TiEq >= 50000`

This is an all-opponents gate, not an aggregate-only gate. One weak matchup
fails promotion.

## 9. Implementation notes for future work

When changing `jon-5`, keep these constraints in mind:

- when evaluating combat pressure on the enemy core, count a core shot only if
  the attack covers the center core tile; the outer tiles of the `3x3` core
  footprint do not count as valid core targets
- do not invent fake shared state across units
- do not optimize around mined totals while ignoring delivery quality
- do not rewrite the whole bot just to get cleaner abstractions
- improve coordination and logistics first; those are the current leverage
  points

If a future bot line supersedes `jon-5`, it should preserve the core lesson
that made `jon-5` viable: finding ore is not enough, and pathfinding is only as
good as the delivered route it creates.
