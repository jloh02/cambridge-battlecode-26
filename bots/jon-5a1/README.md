# jon-5a1

`jon-5a1` is a `jon-5` descendant that keeps the same core economy skeleton and
adds a fixed-role enemy-harvester assault layer.

## Notes by Ben
This bot is known to only have a marginal (i.e. 65%) win rate against jon-5. Therefore, it is not fit for compeitition use.

## Inherited From `jon-5`

- chunk-based exploration for non-assault builders
- ore finding with remembered local map state
- tiling-back route completion from new harvesters to the core / live conveyor
- bounded A* with greedy fallback and bridge-aware route building
- simple core spawning policy with ore-aware bias

## What `jon-5a1` Adds

- four permanent assault-role builders spawned on diagonal core-adjacent tiles
- a new `ASSAULTING` builder mode
- symmetry-guided enemy-base scouting for assault builders before contact
- per-builder enemy-core memory and recent harvester-anchor memory
- no marker-based assault coordination in this version

## Assault Logic

Assault builders do not mine ore or tile back. They do this instead:

1. scout toward a predicted enemy anchor
2. when a visible enemy titanium harvester is found, evaluate it as an assault anchor
3. enumerate the 4 cardinal ring sites around that harvester
4. enumerate all 8 sentinel facings from each ring site
5. keep only site/facing pairs that:
   - are feed-legal from the harvester
   - have an immediate legal shot
6. score the remaining options and move/build toward the best one

The bot accepts a single useful denial sentinel. It does not require a
multi-site core siege to start attacking.

## Immediate-Shot Heuristic

A ring site is only considered usable if the sentinel can immediately shoot
something valuable. Target priority is:

1. enemy turrets
2. enemy logistics in the harvester's connected local supply structure
3. enemy core

The local enemy logistics structure is the cardinally connected visible enemy
component rooted at the anchor harvester, restricted to:

- harvester
- conveyor
- armoured conveyor
- splitter
- bridge
- foundry

## Builder Execution Rules

- if the chosen ring tile contains a clearable enemy conveyor, clear it only as
  needed to place the sentinel
- if the builder is standing on the chosen ring tile, sidestep off it
- after one live ring sentinel exists, prefer a second valid ring site on the
  same harvester before resuming scouting
- builders do not perform free-standing post-build denial work in this version

## Notes

- helper tests for assault site selection live in
  [tests/test_jon_5a1_assault.py](/Users/benjamin/Documents/CodingProjects/cambridge-battlecode-26/tests/test_jon_5a1_assault.py)
- this bot was benchmarked against `jon-5` and `orange_v1`, but the current
  version did not clear the repo's 80% promotion gate
